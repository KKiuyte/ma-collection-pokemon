#!/usr/bin/env python3
"""
« Et si elle était gradée ? » — estime, pour les cartes de la collection au-dessus d'un
seuil de prix, ce qu'elles vaudraient gradées, d'après les VRAIES ventes PSA.

Chaîne :
  1. collection (Firestore `collections/{uid}`, SDK Admin) → exemplaires (version, état, langue)
  2. TCGdex → nom EN/FR, numéro, série, prix brut Cardmarket par version (mêmes règles que
     priceForVariant() dans index.html — dupliquées ici, à garder alignées)
  3. cartes éligibles : prix ≥ seuil ET état « Neuve » (vise PSA 10) ou « Excellent » (PSA 9)
  4. PSA (tools/psa_client.py) : série correspondante → population (SpecID) → ventes par note
     sur N mois (repli 12 mois, puis toutes époques) → moyenne $ → € → décote « France »
  5. rapport écrit dans Firestore `graded_reports/{uid}` (privé), lu par public/graded-value.html

    python tools/psa_collection_value.py                       # run complet (Firestore)
    python tools/psa_collection_value.py --dry-run --out r.json  # sans écrire Firestore
    python tools/psa_collection_value.py --owned-json coll.json --dry-run --out r.json  # test local

Env : FIREBASE_SERVICE_ACCOUNT (JSON du compte de service) ou GOOGLE_APPLICATION_CREDENTIALS ;
      PSA_EMAIL / PSA_PASSWORD (ou ~/.psa.env) ; GRADED_UID ou GRADED_EMAIL pour choisir la
      collection (défaut : le compte dont l'e-mail = PSA_EMAIL).

⚠️ Pour une carte FRANÇAISE moderne, PSA n'a pas de série FR : on prend la version ANGLAISE
   de la même carte (champ `proxy_lang` = "EN" dans le rapport). La décote sert aussi à ça.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from psa_client import PsaSession, match_set, LANG_BY_TCGDEX, _norm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "tools", "cache")
SETS_MAP = os.path.join(ROOT, "tools", "psa-sets-map.json")   # versionné : correspondances + overrides
TCGDEX = "https://api.tcgdex.net/v2"
UA = "ma-collection-pokemon/graded-value (script perso)"

GRADE_TARGET_BY_COND = {"Neuve": 10, "Excellent": 9}
POP_TTL_DAYS = 7
MIN_SALES = 3        # en dessous, la moyenne d'une fenêtre n'est pas fiable : on élargit
NOW = dt.datetime.now(dt.timezone.utc)


def iso(t=None):
    return (t or NOW).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ collection
def copies_of(rec):
    """Tolère les anciens formats (nombre, {qty,cond,lang}, {v:{version:[...]}}).
    Renvoie [(version, cond, lang), ...] — un élément par exemplaire."""
    out = []
    if isinstance(rec, (int, float)):
        return [("Normale", "Neuve", "Français")] * int(rec)
    if isinstance(rec, dict) and "v" not in rec and ("qty" in rec or "cond" in rec):
        return [("Normale", rec.get("cond", "Neuve"), rec.get("lang", "Français"))] * int(rec.get("qty", 1))
    v = (rec or {}).get("v", {}) if isinstance(rec, dict) else {}
    for version, copies in v.items():
        if isinstance(copies, list):
            for cp in copies:
                if isinstance(cp, dict):
                    out.append((version, cp.get("cond", "Neuve"), cp.get("lang", "Français")))
                else:
                    out.append((version, "Neuve", "Français"))
        elif isinstance(copies, dict):
            out.extend([(version, copies.get("cond", "Neuve"), copies.get("lang", "Français"))] * int(copies.get("qty", 1)))
        elif isinstance(copies, (int, float)):
            out.extend([(version, "Neuve", "Français")] * int(copies))
    return out


def firestore_client():
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
        else:
            raise SystemExit("Firestore : FIREBASE_SERVICE_ACCOUNT ou GOOGLE_APPLICATION_CREDENTIALS manquant")
        firebase_admin.initialize_app(cred)
    return firestore.client()


def resolve_uid(db, uid=None, email=None):
    if uid:
        return uid
    email = email or os.environ.get("GRADED_EMAIL") or os.environ.get("PSA_EMAIL")
    if not email:
        raise SystemExit("Collection : indiquer --uid, GRADED_UID ou GRADED_EMAIL")
    for doc in db.collection("users").where("email", "==", email).limit(1).stream():
        return doc.id
    raise SystemExit(f"Collection : aucun profil users/* avec l'e-mail {email}")


def load_owned(args):
    if args.owned_json:
        with open(args.owned_json, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("cards", d), args.uid or "local"
    db = firestore_client()
    uid = resolve_uid(db, args.uid or os.environ.get("GRADED_UID"))
    snap = db.collection("collections").document(uid).get()
    if not snap.exists:
        raise SystemExit(f"Collection : collections/{uid} introuvable")
    return (snap.to_dict() or {}).get("cards", {}) or {}, uid


# ------------------------------------------------------------------ TCGdex
_http = requests.Session()
_http.headers.update({"User-Agent": UA})


def tcgdex(path):
    for attempt in range(3):
        try:
            r = _http.get(TCGDEX + path, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def fetch_card(card_id):
    fr = tcgdex(f"/fr/cards/{card_id}")
    en = tcgdex(f"/en/cards/{card_id}")
    return card_id, fr, en


_set_cache = {}


def set_info(set_id):
    if set_id not in _set_cache:
        en = tcgdex(f"/en/sets/{set_id}") or {}
        fr = tcgdex(f"/fr/sets/{set_id}") or {}
        _set_cache[set_id] = {
            "id": set_id, "name_en": en.get("name"), "name_fr": fr.get("name") or en.get("name"),
            "serie_en": (en.get("serie") or {}).get("name"),
            "year": int((en.get("releaseDate") or "0000")[:4] or 0),
        }
    return _set_cache[set_id]


def _num(x):
    return x if isinstance(x, (int, float)) and x > 0 else None


def price_for_variant(card, variant):
    """Port de priceForVariant()/detailedCardmarketPrice() d'index.html. (value, unit) ou None."""
    pricing = (card or {}).get("pricing") or {}
    typ = "reverse" if variant == "Reverse Holo" else "holo" if variant == "Holo" else "normal"
    for e in (card or {}).get("variants_detailed") or []:
        if isinstance(e, dict) and str(e.get("type", "")).lower() == typ:
            cm = (e.get("pricing") or {}).get("cardmarket") or {}
            v = (_num(cm.get("trend-holo")) or _num(cm.get("avg-holo")) or _num(cm.get("avg30-holo"))) \
                if variant == "Reverse Holo" else (_num(cm.get("trend")) or _num(cm.get("avg")) or _num(cm.get("avg30")))
            if v:
                return v, "EUR"
    cm, tp = pricing.get("cardmarket"), pricing.get("tcgplayer")
    variants = (card or {}).get("variants") or {}
    has_normal, has_holo = bool(variants.get("normal")), bool(variants.get("holo"))
    is_foil = variant in ("Holo", "Reverse Holo")
    if cm:
        base = _num(cm.get("trend")) or _num(cm.get("avg")) or _num(cm.get("avg30"))
        holo = _num(cm.get("trend-holo")) or _num(cm.get("avg-holo")) or _num(cm.get("avg30-holo"))
        v = None
        if not is_foil:
            v = base
        elif not has_normal:
            v = base or holo
        elif variant == "Holo" or not has_holo:
            v = holo
        if v:
            return v, "EUR"
    if tp:
        key = "reverse-holofoil" if variant == "Reverse Holo" else "holofoil" if variant == "Holo" else "normal"
        b = tp.get(key) or tp.get("holofoil") or tp.get("normal")
        if b:
            v = _num(b.get("marketPrice")) or _num(b.get("midPrice")) or _num(b.get("lowPrice"))
            if v:
                return v, "USD"
    return None


def fx_usd_eur():
    for api in ("https://api.frankfurter.app/latest?from=USD&to=EUR", "https://open.er-api.com/v6/latest/USD"):
        try:
            rate = (_http.get(api, timeout=15).json().get("rates") or {}).get("EUR")
            if rate:
                return round(float(rate), 4)
        except Exception:
            pass
    return 0.9


# ------------------------------------------------------------------ PSA
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def psa_set_for(ps, sets_map, sinfo, lang_marker):
    """Série PSA pour (set TCGdex, langue). Mémorisé dans tools/psa-sets-map.json ; une entrée
    manuelle {"psa_id": ..., "psa_name": ...} y a toujours priorité."""
    key = f"{sinfo['id']}|{lang_marker or 'EN'}"
    ent = sets_map.get(key)
    if ent and (ent.get("psa_id") or ent.get("none")):
        return ent
    if not sinfo.get("name_en") or not sinfo.get("year"):
        ent = {"none": True, "why": "set TCGdex incomplet"}
    else:
        best, cands = match_set(ps, sinfo["name_en"], sinfo.get("serie_en") or "", sinfo["year"], lang_marker)
        ent = ({"psa_id": best["id"], "psa_name": best["name"], "psa_year": best["year"], "auto": True}
               if best else {"none": True, "why": "aucune série PSA trouvée",
                             "candidates": [c[1]["name"] for c in cands[:3]]})
    sets_map[key] = ent
    return ent


def pop_rows(ps, psa_id):
    path = os.path.join(CACHE_DIR, f"psa-pop-{psa_id}.json")
    c = load_json(path, None)
    if c and (NOW - dt.datetime.strptime(c["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).days < POP_TTL_DAYS:
        return c["rows"]
    rows = ps.pop_set(psa_id)
    save_json(path, {"at": iso(), "rows": rows})
    return rows


def _numkey(s):
    m = re.search(r'\d+', str(s or ""))
    return str(int(m.group(0))) if m else _norm(s)


def find_row(rows, local_id, name_en, version="Normale"):
    """Ligne du rapport de population pour un numéro imprimé. PSA liste les Reverse à part
    (« Venonat-Reverse Foil ») : on choisit la ligne qui correspond à la version possédée,
    puis le nom EN départage les homonymes."""
    want, target = _numkey(local_id), _norm(name_en)
    same = [r for r in rows if _numkey(r.get("CardNumber")) == want]
    if not same:
        return None
    is_rev = lambda r: "reverse" in _norm(r.get("SubjectName")) or "reverse" in _norm(r.get("Variety"))
    wanted = [r for r in same if is_rev(r) == (version == "Reverse Holo")]
    same = wanted or same
    if len(same) == 1:
        return same[0]
    def score(r):
        n = re.sub(r'\breverse foil\b', '', _norm(r.get("SubjectName"))).strip()
        if n == target:
            return 3
        if target and (target in n or n in target):
            return 2
        return 1 if not r.get("Variety") else 0
    return max(same, key=score)


def grade_pop(row, grade):
    key = f"Grade{int(grade)}" if float(grade).is_integer() else f"Grade{str(grade).replace('.', '_')}"
    at = int(row.get(key) or 0)
    higher = 0
    for g in (8.5, 9, 9.5, 10):
        if g > grade:
            k = f"Grade{int(g)}" if float(g).is_integer() else f"Grade{str(g).replace('.', '_')}"
            higher += int(row.get(k) or 0)
    return at, higher


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=10.0, help="prix brut minimal en € (défaut 10)")
    ap.add_argument("--months", type=int, default=6, help="fenêtre des ventes PSA en mois (défaut 6)")
    ap.add_argument("--discount", type=float, default=0.15, help="décote « gradée en France » (défaut 0.15)")
    ap.add_argument("--uid")
    ap.add_argument("--owned-json", help="test local : fichier JSON de la collection")
    ap.add_argument("--dry-run", action="store_true", help="ne pas écrire dans Firestore")
    ap.add_argument("--out", help="écrire aussi le rapport JSON ici (chemin NON public)")
    ap.add_argument("--max-cards", type=int, default=0, help="limiter (test)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    owned, uid = load_owned(args)
    ids = list(owned.keys())
    if args.max_cards:
        ids = ids[:args.max_cards]
    log(f"collection {uid} : {len(ids)} carte(s)")

    # --- TCGdex : cartes + prix
    cards = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for cid, fr, en in ex.map(fetch_card, ids):
            if fr or en:
                cards[cid] = {"fr": fr or {}, "en": en or {}}
    log(f"TCGdex : {len(cards)} fiche(s) récupérée(s)")

    # --- éligibilité
    rows, skipped_price, skipped_cond = [], 0, 0
    for cid in ids:
        c = cards.get(cid)
        if not c:
            continue
        fr, en = c["fr"], c["en"]
        src = fr or en
        set_id = (src.get("set") or {}).get("id") or cid.rsplit("-", 1)[0]
        groups = {}
        for version, cond, lang in copies_of(owned[cid]):
            groups.setdefault((version, cond, lang), 0)
            groups[(version, cond, lang)] += 1
        for (version, cond, lang), qty in groups.items():
            target = GRADE_TARGET_BY_COND.get(cond)
            if not target:
                skipped_cond += qty
                continue
            p = price_for_variant(fr, version) or price_for_variant(en, version)
            if not p or p[1] != "EUR" or p[0] < args.threshold:
                skipped_price += qty
                continue
            rows.append({
                "id": cid, "name_fr": fr.get("name") or en.get("name"), "name_en": en.get("name") or fr.get("name"),
                "number": src.get("localId"), "set_id": set_id, "image": src.get("image"),
                "set_name_fr": (fr.get("set") or {}).get("name") or (en.get("set") or {}).get("name"),
                "version": version, "cond": cond, "lang": lang, "qty": qty,
                "raw_eur": round(p[0], 2), "target_grade": target,
            })
    log(f"éligibles : {len(rows)} ligne(s) (ignorées : {skipped_price} sous le seuil / sans prix €, "
        f"{skipped_cond} par l'état)")

    # --- PSA
    ps = PsaSession(verbose=args.verbose).ensure()
    sets_map = load_json(SETS_MAP, {})
    fx = fx_usd_eur()
    pop_cache, price_cache = {}, {}
    unmatched_sets = {}
    for r in rows:
        sinfo = set_info(r["set_id"])
        marker = LANG_BY_TCGDEX.get(r["lang"])
        # séries candidates, dans l'ordre : celle de la langue de la carte, puis l'anglaise
        # (repli si la série FR n'existe pas chez PSA, OU si la carte n'y figure pas)
        candidates = []
        if marker:
            e = psa_set_for(ps, sets_map, sinfo, marker)
            if not e.get("none"):
                candidates.append((e, None))
        e = psa_set_for(ps, sets_map, sinfo, None)
        if not e.get("none") and all(e["psa_id"] != c[0]["psa_id"] for c in candidates):
            candidates.append((e, "EN" if marker else None))
        if not candidates:
            r["status"] = "set_not_found"
            unmatched_sets[r["set_id"]] = sinfo.get("name_en")
            continue
        row, ent, proxy = None, None, None
        for e, px in candidates:
            if e["psa_id"] not in pop_cache:
                pop_cache[e["psa_id"]] = pop_rows(ps, e["psa_id"])
            row = find_row(pop_cache[e["psa_id"]], r["number"], r["name_en"], r["version"])
            if row:
                ent, proxy = e, px
                break
        if not row:
            r["status"] = "card_not_found"
            r["psa"] = {"set_name": " / ".join(c[0]["psa_name"] for c in candidates), "proxy_lang": None}
            continue
        spec = row["SpecID"]
        grade = float(r["target_grade"])
        key = (spec, grade)
        if key not in price_cache:
            # fenêtre demandée, puis 12 mois, puis toutes époques : on retient la première
            # avec au moins MIN_SALES ventes à la note visée ; sinon la plus large qui en a
            picked, fallback = None, None
            for months in (args.months, 12, 0):
                m = ps.price_summary(spec, months).get(grade)
                if m and m["quantity"] >= MIN_SALES:
                    picked = (m, months)
                    break
                if m:
                    fallback = (m, months)
            price_cache[key] = picked or fallback
        pop_at, pop_higher = grade_pop(row, r["target_grade"])
        psa = {"set_name": ent["psa_name"], "spec_id": spec, "subject": row.get("SubjectName"),
               "proxy_lang": proxy, "pop_at_grade": pop_at, "pop_higher": pop_higher}
        if not price_cache[key]:
            r["status"] = "no_sales"
            r["psa"] = psa
            continue
        m, window = price_cache[key]
        est_eur = round(m["averagePrice"] * fx, 2)
        est_fr = round(est_eur * (1 - args.discount), 2)
        psa.update({"sales_qty": m["quantity"], "avg_usd": m["averagePrice"], "latest_usd": m.get("latestPrice"),
                    "window_months": window, "thin": m["quantity"] < MIN_SALES,
                    "est_eur": est_eur, "est_eur_france": est_fr})
        r["psa"] = psa
        r["gain_unit"] = round(est_fr - r["raw_eur"], 2)
        r["gain_total"] = round(r["gain_unit"] * r["qty"], 2)
        r["status"] = "priced"
        if args.verbose:
            log(f"  {r['name_fr']} #{r['number']} {r['version']} ×{r['qty']} : {r['raw_eur']}€ → "
                f"PSA {r['target_grade']} {est_fr}€ (pop {pop_at}, {m['quantity']} ventes/{window}m)")
    save_json(SETS_MAP, sets_map)

    priced = [r for r in rows if r.get("status") == "priced"]
    priced.sort(key=lambda r: -r.get("gain_total", 0))
    others = [r for r in rows if r.get("status") != "priced"]
    report = {
        "generated_at": iso(), "threshold": args.threshold, "months": args.months,
        "discount": args.discount, "fx_usd_eur": fx,
        "stats": {"cards_owned": len(ids), "eligible_rows": len(rows), "priced_rows": len(priced),
                  "no_sales": sum(1 for r in others if r.get("status") == "no_sales"),
                  "card_not_found": sum(1 for r in others if r.get("status") == "card_not_found"),
                  "set_not_found": sum(1 for r in others if r.get("status") == "set_not_found"),
                  "unmatched_sets": unmatched_sets},
        "totals": {"raw_eur": round(sum(r["raw_eur"] * r["qty"] for r in priced), 2),
                   "est_france_eur": round(sum(r["psa"]["est_eur_france"] * r["qty"] for r in priced), 2)},
        "rows": priced + others,
    }
    report["totals"]["gain_eur"] = round(report["totals"]["est_france_eur"] - report["totals"]["raw_eur"], 2)

    if args.out:
        save_json(args.out, report)
        log(f"rapport écrit : {args.out}")
    if not args.dry_run and not args.owned_json:
        db = firestore_client()
        db.collection("graded_reports").document(uid).set(report)
        log(f"rapport écrit dans Firestore graded_reports/{uid}")
    s = report["stats"]
    log(f"→ {s['priced_rows']} chiffrée(s) / {s['eligible_rows']} éligible(s) · sans vente {s['no_sales']} · "
        f"carte absente {s['card_not_found']} · série absente {s['set_not_found']} · "
        f"brut {report['totals']['raw_eur']} € → gradé FR {report['totals']['est_france_eur']} € "
        f"({report['totals']['gain_eur']:+} €)")


if __name__ == "__main__":
    main()
