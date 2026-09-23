#!/usr/bin/env python3
"""
Étape 2 du système « bonnes affaires » : enrichit public/vinted-psa.json avec, pour
chaque annonce, le numéro de certification PSA lu sur les photos, puis la fiche PSA
correspondante (carte exacte, grade, estimation de prix).

Chaîne :
  1. pour chaque annonce pas encore traitée : télécharge ses photos (f800) et lit
     le **numéro de cert** par OCR (RapidOCR) avec un vote sur plusieurs recadrages ;
  2. pour chaque cert inconnu du cache : **API publique PSA** (jeton PSA_API_TOKEN,
     100 appels/jour) → sujet, année, n° de carte, grade, SpecID, population ; puis
     **ventes PSA** par note via le compte connecté (tools/psa_client.py, PSA_EMAIL/
     PSA_PASSWORD) → estimation = moyenne des ventes 6 mois (sinon 12). Sans jeton :
     repli sur la page psacard.com/cert/{n} en navigateur headless (bloquée par un
     challenge interactif depuis le 2026-09-22, gardée au cas où) ;
  3. compare le prix Vinted (converti en $/€) à l'estimation PSA et marque les
     bonnes affaires.

Le cache (public/psa-cache.json) est versionné : carte/grade d'un cert ne changent
jamais, l'estimation est rafraîchie tous les 30 jours. Ça limite fortement le
nombre d'ouvertures de pages PSA (seulement les nouveaux certs + le rafraîchissement).

    python tools/enrich_psa.py                    # tout : OCR + PSA + calcul
    python tools/enrich_psa.py --max-ocr 40 --max-lookups 20   # bride un passage
    python tools/enrich_psa.py --no-psa           # OCR seul (pas besoin de Playwright)
    python tools/enrich_psa.py --limit 5 --verbose

Dépendances : requests, pillow, numpy, rapidocr-onnxruntime, playwright (+ chromium).
Le workflow GitHub les installe ; en local : pip install + `python -m playwright install chromium`.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT = os.path.join(ROOT, "public", "vinted-psa.json")
CACHE = os.path.join(ROOT, "public", "psa-cache.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

CERT_TTL_DAYS = 30          # au-delà, on re-vérifie l'estimation d'un cert
OCR_RETRY_DAYS = 10         # une annonce sans cert lisible n'est pas re-tentée avant
DEAL_RATIO = 0.80           # prix <= 80 % de l'estimation € => bonne affaire
FX_TTL_HOURS = 20

# API publique officielle de PSA (jeton gratuit, 100 appels/jour) : fiche par n° de cert.
# Depuis le 2026-09-22 la page /cert/{n} est derrière un challenge Cloudflare à case à
# cocher (infranchissable en headless), l'API est donc le chemin normal ; le navigateur
# ne sert plus que de repli quand aucun jeton n'est fourni.
PSA_API = "https://api.psacard.com/publicapi"
PSA_API_TOKEN = os.environ.get("PSA_API_TOKEN", "").strip()
PRICE_MONTHS = (6, 12)      # fenêtres de ventes essayées pour l'estimation (≈ « PSA Estimate »)
MIN_SALES = 3               # en dessous, on n'ose pas d'estimation

NOW = dt.datetime.now(dt.timezone.utc)


def iso(t=None):
    return (t or NOW).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(s):
    try:
        return (NOW - dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)).total_seconds() / 86400
    except Exception:
        return 1e9


# --------------------------------------------------------------------------- HTTP
def make_opener():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "fr-FR,fr;q=0.9,en;q=0.8")]
    return op


def get(opener, url, timeout=25):
    with opener.open(urllib.request.Request(url), timeout=timeout) as r:
        return r.read()


RE_F800 = re.compile(
    r'https://images\d+\.vinted\.net/t/[A-Za-z0-9_]+/f800/[0-9a-f]+\.webp\?s=[a-f0-9]+')


def listing_photos(opener, url, cap=3):
    try:
        html = get(opener, url).decode("utf-8", "replace")
    except Exception as e:
        return [], f"page: {e}"
    if "Just a moment" in html or "geo.captcha-delivery" in html:
        return [], "vinted challenge"
    seen, out = set(), []
    for m in RE_F800.finditer(html):
        base = m.group(0).split("?")[0]
        if base in seen:
            continue
        seen.add(base)
        out.append(m.group(0))
        if len(out) >= cap:
            break
    return out, None


# ---------------------------------------------------------------------------- OCR
_OCR = None
RE_CERT = re.compile(r'(?<!\d)(\d{8,9})(?!\d)')


def ocr_engine():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def _prep(im, scale):
    import numpy as np
    from PIL import Image
    g = im.convert("L").resize((im.width * scale, im.height * scale), Image.LANCZOS)
    a = np.asarray(g).astype("float32")
    lo, hi = a.min(), a.max()
    if hi > lo:
        a = (a - lo) / (hi - lo) * 255.0
    return np.asarray(Image.fromarray(a.astype("uint8")).convert("RGB"))


def read_cert_from_images(blobs, verbose=False):
    """blobs: list of bytes (webp). Renvoie (cert|None, confiance, nb_lectures_concordantes)."""
    import numpy as np
    from PIL import Image
    eng = ocr_engine()
    votes = {}  # cert -> [conf, ...]
    for blob in blobs:
        try:
            im = Image.open(io.BytesIO(blob))
        except Exception:
            continue
        if max(im.size) > 1400:
            r = 1400 / max(im.size)
            im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        w, h = im.size
        # le label PSA est en haut du slab : « top » couvre la face avant,
        # « upband » (un peu plus bas) rattrape le label vu de dos (bande code-barres).
        # On ne fait PAS l'image entière : trop lent pour un gain quasi nul (testé).
        crops = [
            ("top", im.crop((0, 0, w, int(h * 0.30)))),
            ("upband", im.crop((0, int(h * 0.04), w, int(h * 0.38)))),
        ]
        for _, c in crops:
            for scale in (2, 3):
                try:
                    res, _t = eng(_prep(c, scale))
                except Exception:
                    continue
                for row in (res or []):
                    txt = str(row[1]).replace(" ", "")
                    try:
                        conf = float(row[2])
                    except Exception:
                        conf = 0.0
                    for m in RE_CERT.finditer(txt):
                        votes.setdefault(m.group(1), []).append(conf)
    if not votes:
        return None, 0.0, 0
    ranked = sorted(votes.items(), key=lambda kv: (len(kv[1]), sum(kv[1])), reverse=True)
    best, confs = ranked[0]
    score = sum(confs)
    # rejet si le 2e candidat est presque aussi soutenu (ambigu)
    if len(ranked) > 1:
        second = sum(ranked[1][1])
        if second >= 0.75 * score and len(ranked[1][1]) >= len(confs):
            if verbose:
                print(f"      cert ambigu: {ranked[0][0]}({score:.2f}) vs {ranked[1][0]}({second:.2f})")
            return None, 0.0, 0
    n = len(confs)
    ok = n >= 2 or (n == 1 and max(confs) >= 0.90)
    return (best if ok else None), round(max(confs), 2), n


# -------------------------------------------------------------------------- PSA
RE_LABELS = ("Cert Number", "Item Grade", "Year", "Subject", "Card Number",
             "Category", "Brand", "Variety", "Pedigree")
GRADE_NUM = re.compile(r'(\d{1,2})')
GRADE_VAL = re.compile(r'(\d{1,2}(?:\.5)?)')   # « MINT 9 », « NM-MT+ 8.5 », « 10 »


def _unescape(s):
    # les paires de champs de la page PSA sont dans un flux RSC où les guillemets
    # sont échappés en \" — on défait juste ça (pas de unicode_escape global qui
    # casserait sur \/ et mélangerait l'unicode).
    return (s.replace('\\"', '"').replace("\\/", "/")
             .replace("\\n", "\n").replace("\\t", "\t"))


def parse_psa(html):
    u = _unescape(html)
    if "Just a moment" in html or "cf-chl" in html:
        return {"error": "cloudflare"}
    out = {}
    for lbl in RE_LABELS:
        m = re.search(r'"children":"' + re.escape(lbl)
                      + r'"\}\],\["\$","dd",null,\{[^}]*"children":"([^"]*)"', u)
        if m:
            out[lbl] = m.group(1).strip()
    if not out.get("Cert Number"):
        return {"error": "no data"}
    i = u.find("Estimate Confidence")
    if i != -1:
        win = u[i - 500:i + 60]
        amts = re.findall(r'\$\$?\s?([\d,]+\.\d{2})', win)
        conf = re.search(r'Estimate Confidence:\s*([A-Za-z]+)', win)
        vals = [float(a.replace(",", "")) for a in amts[:3]]
        if vals:
            out["est_usd"] = vals[0]
            if len(vals) >= 3:
                out["est_low"], out["est_high"] = vals[1], vals[2]
            out["confidence"] = conf.group(1) if conf else None

    # --- population : « PSA Population » (nombre gradé à ce grade) et
    #     « PSA Pop Higher » (nombre gradé au-dessus). Les deux sont juste après
    #     leur libellé, dans une balise dont on prend le premier "children" numérique.
    for label, key in (("PSA Population", "pop"), ("PSA Pop Higher", "pop_higher")):
        m = re.search(re.escape(label) + r'".{0,220}?"children":"([\d,]+)"', u)
        if m:
            out[key] = int(m.group(1).replace(",", ""))
    mp = re.search(r'"(https://www\.psacard\.com/pop/[^"]+)"', u)
    if mp:
        out["pop_url"] = mp.group(1)
    return out


def _load_cert_page(page, cert):
    """Charge une page de cert et attend que le vrai contenu soit rendu.
    Avec playwright-stealth le challenge automatique se résout en 1-2 s ; un challenge
    à case à cocher, lui, ne se résoudra jamais : on n'attend pas plus de 20 s."""
    page.goto(f"https://www.psacard.com/cert/{cert}/psa",
              wait_until="domcontentloaded", timeout=30000)
    deadline = time.time() + 20
    while time.time() < deadline:
        html = page.content()
        if "Cert Number" in html:
            return html
        time.sleep(2.0)
    return page.content()


def psa_lookup_batch(certs, verbose=False):
    """REPLI sans jeton d'API : page de cert dans un navigateur headless.
    certs: liste de str. Renvoie {cert: fiche|{'error':...}} — les certs non tentés
    (arrêt après 2 blocages Cloudflare consécutifs) n'y figurent pas.

    ⚠️ Chargement DIRECT par cert (pas de visite d'accueil « de chauffe » : elle
    déclenche un challenge Cloudflare plus strict) + playwright-stealth. Depuis le
    2026-09-22 la page reçoit un challenge interactif : ce chemin échoue en général,
    on le garde au cas où PSA relâche le blocage.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    res, blocked = {}, 0
    with Stealth().use_sync(sync_playwright()) as p:
        br = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = br.new_context(user_agent=UA, locale="fr-CA",
                             viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for k, cert in enumerate(certs):
            try:
                fiche = parse_psa(_load_cert_page(page, cert))
            except Exception as e:
                fiche = {"error": f"nav: {e.__class__.__name__}"}
            res[cert] = fiche
            if verbose:
                extra = f" ${fiche['est_usd']}" if fiche.get("est_usd") else ""
                print(f"    PSA {cert}: {fiche.get('Subject') or fiche.get('error')}{extra}")
            blocked = blocked + 1 if fiche.get("error") == "cloudflare" else 0
            if blocked >= 2:
                if verbose:
                    print("    Cloudflare bloque la page de cert : on arrête pour ce passage")
                break
            if k < len(certs) - 1:
                time.sleep(6.0)
        br.close()
    return res


def _grade_value(g):
    m = GRADE_VAL.search(g or "")
    return float(m.group(1)) if m else None


def psa_price_for(session, spec_id, grade, verbose=False):
    """Estimation à partir des ventes PSA (compte connecté) pour une note donnée :
    moyenne sur 6 mois, sinon 12. Renvoie {} si trop peu de ventes ou si la session
    est refusée. La « confiance » imite l'échelle de la page de cert d'après le nombre
    de ventes (≥ 20 High, ≥ 8 Moderate, sinon Low)."""
    if not session or not spec_id or grade is None:
        return {}
    for months in PRICE_MONTHS:
        try:
            summary = session.price_summary(spec_id, months)
        except Exception as e:
            if verbose:
                print(f"    ventes {spec_id}: {e.__class__.__name__}")
            return {}
        row = summary.get(float(grade)) or {}
        q = row.get("quantity") or 0
        if q >= MIN_SALES and row.get("averagePrice"):
            return {"est_usd": round(float(row["averagePrice"]), 2),
                    "est_low": row.get("minimumPrice"), "est_high": row.get("maximumPrice"),
                    "sales": q, "sales_months": months,
                    "confidence": "High" if q >= 20 else "Moderate" if q >= 8 else "Low"}
    return {}


def psa_lookup_api(certs, session, verbose=False):
    """Chemin normal : API publique PSA (jeton) pour la fiche, puis ventes via le compte.
    Renvoie {cert: fiche}. Un dépassement de quota (429) arrête le lot : les certs
    restants ne sont pas dans le résultat et seront repris au passage suivant."""
    import requests
    res = {}
    hdrs = {"authorization": f"bearer {PSA_API_TOKEN}", "Accept": "application/json"}
    for k, cert in enumerate(certs):
        try:
            r = requests.get(f"{PSA_API}/cert/GetByCertNumber/{cert}", headers=hdrs, timeout=30)
        except Exception as e:
            res[cert] = {"error": f"api: {e.__class__.__name__}"}
            continue
        if r.status_code == 429:
            if verbose:
                print("    API PSA : quota journalier atteint, on reprendra demain")
            break
        if r.status_code in (401, 403):
            if verbose:
                print(f"    API PSA : jeton refusé (HTTP {r.status_code})")
            break
        try:
            c = (r.json() or {}).get("PSACert") or {}
        except Exception:
            c = {}
        if not c.get("CertNumber"):
            res[cert] = {"error": "no data"}
            continue
        grade = str(c.get("CardGrade") or "").strip()
        desc = str(c.get("GradeDescription") or "").strip()
        item_grade = f"{desc} {grade}".strip() if grade and not GRADE_VAL.search(desc) else (desc or grade)
        fiche = {
            "Cert Number": str(c["CertNumber"]),
            "Subject": c.get("Subject"),
            "Item Grade": item_grade,
            "Year": str(c.get("Year") or ""),
            "Card Number": str(c.get("CardNumber") or ""),
            "Category": c.get("Category"),
            "Brand": c.get("Brand"),
            "Variety": c.get("Variety"),
            "spec_id": c.get("SpecID"),
            "pop": c.get("TotalPopulation"),
            "pop_higher": c.get("PopulationHigher"),
            "source": "api",
        }
        fiche.update(psa_price_for(session, fiche["spec_id"], _grade_value(item_grade), verbose))
        res[cert] = fiche
        if verbose:
            extra = f" ${fiche['est_usd']} ({fiche['sales']} ventes)" if fiche.get("est_usd") else ""
            print(f"    PSA {cert}: {fiche.get('Subject')} {item_grade}{extra}")
        if k < len(certs) - 1:
            time.sleep(1.0)
    return res


def open_psa_session(verbose=False):
    """Session PSA connectée (tools/psa_client.py) pour les ventes ; None si pas
    d'identifiants ou connexion impossible — la fiche reste alors sans estimation."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import psa_client
        psa_client.load_credentials()
        return psa_client.PsaSession(verbose=verbose).ensure()
    except (Exception, SystemExit) as e:    # load_credentials() lève SystemExit
        if verbose:
            print(f"  session PSA indisponible ({e.__class__.__name__}: {e}) : pas d'estimation")
        return None


# -------------------------------------------------------------------------- FX
def refresh_fx(cache, opener, verbose=False):
    meta = cache.setdefault("_meta", {})
    if meta.get("fx_usd_eur") and age_days(meta.get("fx_at", "")) * 24 < FX_TTL_HOURS:
        return meta["fx_usd_eur"]
    for api in ("https://api.frankfurter.app/latest?from=USD&to=EUR",
                "https://open.er-api.com/v6/latest/USD"):
        try:
            d = json.loads(get(opener, api, timeout=15))
            rate = (d.get("rates", {}) or {}).get("EUR")
            if rate:
                meta["fx_usd_eur"] = round(float(rate), 4)
                meta["fx_at"] = iso()
                if verbose:
                    print(f"  FX USD→EUR = {meta['fx_usd_eur']}")
                return meta["fx_usd_eur"]
        except Exception:
            continue
    return meta.get("fx_usd_eur") or 0.92


def psa_phase(items, cache, args, V):
    """Fiches PSA : API (jeton) + ventes (compte), ou navigateur en repli sans jeton.
    Une fiche venue de l'API mais restée sans estimation (session refusée ce jour-là)
    est reprise au passage suivant sans reconsommer le quota de l'API."""
    wanted, price_only, seen = [], [], set()
    for it in items:
        cert = (cache["items"].get(it["id"]) or {}).get("cert")
        if not cert or cert in seen:
            continue
        seen.add(cert)
        f = cache["certs"].get(cert)
        if f and f.get("error") and age_days(f.get("checked_at", "")) < 1:
            continue  # échec récent : on laisse reposer
        if f and "error" not in f and "pop" in f and age_days(f.get("checked_at", "")) < CERT_TTL_DAYS:
            if f.get("spec_id") and not f.get("est_usd") and age_days(f.get("priced_at", "")) >= 1:
                price_only.append(cert)
            continue
        wanted.append(cert)
    wanted = wanted[:args.max_lookups]
    if V:
        print(f"PSA : {len(wanted)} fiche(s) à ouvrir, {len(price_only)} estimation(s) à reprendre")
    if not wanted and not price_only:
        return

    if not PSA_API_TOKEN:
        if V:
            print("  pas de jeton PSA_API_TOKEN : repli navigateur (souvent bloqué par Cloudflare)")
        for cert, fiche in psa_lookup_batch(wanted, verbose=V).items():
            fiche["checked_at"] = iso()
            cache["certs"][cert] = fiche
        return

    session = open_psa_session(verbose=V)
    try:
        for cert, fiche in psa_lookup_api(wanted, session, verbose=V).items():
            fiche["checked_at"] = iso()
            if session:
                fiche["priced_at"] = iso()
            cache["certs"][cert] = fiche
        if session:
            for cert in price_only[:args.max_lookups]:
                f = cache["certs"][cert]
                f.update(psa_price_for(session, f["spec_id"], _grade_value(f.get("Item Grade")), V))
                f["priced_at"] = iso()
    finally:
        if session:
            session.close()


# ------------------------------------------------------------------------- main
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_psa_field(item, cache, fx):
    cert = (cache["items"].get(item["id"]) or {}).get("cert")
    if not cert:
        st = (cache["items"].get(item["id"]) or {}).get("status", "no_cert")
        return {"cert": None, "status": st}
    fiche = cache["certs"].get(cert)
    if not fiche or "error" in fiche:
        return {"cert": cert, "status": "pending"}
    est = fiche.get("est_usd")
    out = {
        "cert": cert,
        "subject": fiche.get("Subject"),
        "grade": fiche.get("Item Grade"),
        "grade_num": _grade_num(fiche.get("Item Grade")),
        "year": fiche.get("Year"),
        "card_number": fiche.get("Card Number"),
        "category": fiche.get("Category"),
        "confidence": fiche.get("confidence"),
        "pop": fiche.get("pop"),                 # gradés à ce grade
        "pop_higher": fiche.get("pop_higher"),   # gradés au-dessus
        "pop_url": fiche.get("pop_url"),
        "sales": fiche.get("sales"),             # nb de ventes derrière l'estimation (API)
        "sales_months": fiche.get("sales_months"),
    }
    if est:
        est_eur = round(est * fx, 2)
        out["est_usd"] = est
        out["est_low_usd"] = fiche.get("est_low")
        out["est_high_usd"] = fiche.get("est_high")
        out["est_eur"] = est_eur
        if est_eur > 0:
            ratio = round(item["price"] / est_eur, 2)
            out["ratio"] = ratio
            # PSA note la confiance « High / Moderate / Low »
            out["deal"] = bool(ratio <= DEAL_RATIO
                               and (fiche.get("confidence") in ("High", "Moderate")))
        out["status"] = "priced"
    else:
        out["status"] = "no_estimate"
    return out


def _grade_num(g):
    if not g:
        return None
    m = GRADE_NUM.search(g)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=INPUT)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--max-ocr", type=int, default=40,
                    help="annonces à passer à l'OCR par exécution (montée en charge)")
    ap.add_argument("--max-lookups", type=int, default=20,
                    help="pages PSA à ouvrir par exécution")
    ap.add_argument("--no-psa", action="store_true", help="OCR seulement")
    ap.add_argument("--limit", type=int, default=0, help="ne traiter que N annonces (test)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    V = args.verbose

    data = load_json(args.input, None)
    if not data or "items" not in data:
        sys.exit(f"{args.input} illisible")
    cache = load_json(args.cache, {})
    cache.setdefault("_meta", {})
    cache.setdefault("items", {})
    cache.setdefault("certs", {})

    opener = make_opener()
    try:
        get(opener, "https://www.vinted.fr/")
    except Exception:
        pass
    fx = refresh_fx(cache, opener, V)

    items = data["items"]
    if args.limit:
        items = items[:args.limit]

    # --- phase 1 : OCR du cert sur les annonces pas encore décidées ---
    todo = []
    for it in items:
        c = cache["items"].get(it["id"])
        if c and c.get("cert"):
            continue
        if c and c.get("status") in ("no_cert",) and age_days(c.get("at", "")) < OCR_RETRY_DAYS:
            continue
        todo.append(it)
    # les annonces chères d'abord : c'est là que se jouent les vraies affaires, et le
    # flux Vinted (~1 000 annonces PSA/jour) dépasse ce qu'un passage peut lire
    todo.sort(key=lambda it: -(it.get("price") or 0))
    todo = todo[:args.max_ocr]
    if V:
        print(f"OCR : {len(todo)} annonce(s) à lire (sur {len(items)})")
    # DataDome (Vinted) renvoie des 403 au bout de ~30 pages d'annonce en 5 min depuis une
    # même IP (vu le 2026-09-23 sur GitHub Actions) : on souffle 60 s puis 120 s, et au
    # 3e refus consécutif on arrête la phase pour ce passage — sans rien écrire dans le
    # cache pour les annonces non lues, elles seront reprises au passage suivant.
    refused = 0
    for n, it in enumerate(todo, 1):
        photos, err = None, None
        while True:
            photos, err = listing_photos(opener, it["url"])
            blocked = err and ("403" in err or "challenge" in err)
            if not blocked:
                refused = 0
                break
            refused += 1
            if refused >= 3:
                break
            if V:
                print(f"  [{n}/{len(todo)}] Vinted refuse ({err}) : pause {60 * refused} s")
            time.sleep(60 * refused)
        if refused >= 3:
            print(f"  Vinted bloque les pages d'annonce : OCR arrêté à {n - 1}/{len(todo)} pour ce passage")
            break
        if err or not photos:
            cache["items"][it["id"]] = {"cert": None, "status": "no_photo" if not photos else "no_cert",
                                        "at": iso(), "note": err}
            if V:
                print(f"  [{n}/{len(todo)}] {it['id']} : {err or 'aucune photo'}")
            continue
        blobs = []
        for u in photos:
            try:
                blobs.append(get(opener, u, timeout=25))
            except Exception:
                pass
        cert, conf, k = read_cert_from_images(blobs, verbose=V)
        cache["items"][it["id"]] = {
            "cert": cert, "conf": conf, "votes": k, "at": iso(),
            "status": "ok" if cert else "no_cert"}
        if V:
            print(f"  [{n}/{len(todo)}] {it['id']} : {cert or '—'} (conf {conf}, {k} lectures)")
        time.sleep(3.0)

    # --- phase 2 : fiches PSA pour les certs inconnus / périmés ---
    # Tout est protégé : quoi qu'il arrive côté PSA, les certs lus en phase 1 sont écrits.
    if not args.no_psa:
        try:
            psa_phase(items, cache, args, V)
        except Exception as e:
            print(f"  phase PSA interrompue ({e.__class__.__name__}: {e}) — on garde l'OCR",
                  file=sys.stderr)

    # --- phase 3 : fusion + calcul bonne affaire ---
    for it in data["items"]:
        it["psa"] = build_psa_field(it, cache, fx)

    def sort_key(it):
        p = it.get("psa", {})
        if p.get("deal"):
            return (0, p.get("ratio", 9))
        if p.get("status") == "priced":
            return (1, p.get("ratio", 9))
        return (2, -int(it["id"]))
    data["items"].sort(key=sort_key)

    priced = [i for i in data["items"] if i["psa"].get("status") == "priced"]
    data["enriched_at"] = iso()
    data["fx_usd_eur"] = fx
    data["psa_stats"] = {
        "cert_read": sum(1 for i in data["items"] if i["psa"].get("cert")),
        "priced": len(priced),
        "deals": sum(1 for i in data["items"] if i["psa"].get("deal")),
        "cache_certs": len(cache["certs"]),
    }

    with open(args.input, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with open(args.cache, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
        f.write("\n")

    s = data["psa_stats"]
    print(f"→ cert lu : {s['cert_read']}/{len(data['items'])} · "
          f"estimé : {s['priced']} · bonnes affaires : {s['deals']} · "
          f"cache {s['cache_certs']} certs · FX {fx}")


if __name__ == "__main__":
    main()
