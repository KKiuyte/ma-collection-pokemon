#!/usr/bin/env python3
"""
Étape 2 du système « bonnes affaires » : enrichit public/vinted-psa.json avec, pour
chaque annonce, le numéro de certification PSA lu sur les photos, puis la fiche PSA
correspondante (carte exacte, grade, estimation de prix).

Chaîne :
  1. pour chaque annonce pas encore traitée : télécharge ses photos (f800) et lit
     le **numéro de cert** par OCR (RapidOCR) avec un vote sur plusieurs recadrages ;
  2. pour chaque cert inconnu du cache : ouvre psacard.com/cert/{n} dans un
     navigateur headless (Chromium/Playwright, seul moyen de passer Cloudflare) et
     récupère sujet, année, n° de carte, grade et **estimation PSA** ($, fourchette,
     confiance) ;
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
    Avec playwright-stealth le challenge Cloudflare se résout en 1-2 s ; on
    laisse quand même jusqu'à 40 s au cas où."""
    page.goto(f"https://www.psacard.com/cert/{cert}/psa",
              wait_until="domcontentloaded", timeout=45000)
    deadline = time.time() + 40
    while time.time() < deadline:
        html = page.content()
        if "Cert Number" in html:
            return html
        time.sleep(2.0)
    return page.content()


def psa_lookup_batch(certs, verbose=False):
    """certs: liste de str. Renvoie {cert: fiche|{'error':...}}.

    ⚠️ Chargement DIRECT par cert (pas de visite d'accueil « de chauffe » : elle
    déclenche un challenge Cloudflare plus strict) + playwright-stealth. Testé :
    5/5 certs passés d'affilée. Sans stealth, Cloudflare bloque dès le 1er ou 2e.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    res = {}
    with Stealth().use_sync(sync_playwright()) as p:
        br = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = br.new_context(user_agent=UA, locale="fr-CA",
                             viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for k, cert in enumerate(certs):
            fiche, attempts = {"error": "cloudflare"}, 0
            while attempts < 2 and fiche.get("error") == "cloudflare":
                attempts += 1
                try:
                    fiche = parse_psa(_load_cert_page(page, cert))
                except Exception as e:
                    fiche = {"error": f"nav: {e.__class__.__name__}"}
                if fiche.get("error") == "cloudflare" and attempts < 2:
                    time.sleep(8.0)
            res[cert] = fiche
            if verbose:
                extra = f" ${fiche['est_usd']}" if fiche.get("est_usd") else ""
                print(f"    PSA {cert}: {fiche.get('Subject') or fiche.get('error')}{extra}")
            if k < len(certs) - 1:
                time.sleep(6.0)
        br.close()
    return res


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
    todo = todo[:args.max_ocr]
    if V:
        print(f"OCR : {len(todo)} annonce(s) à lire (sur {len(items)})")
    for n, it in enumerate(todo, 1):
        photos, err = listing_photos(opener, it["url"])
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
        time.sleep(1.2)

    # --- phase 2 : fiches PSA pour les certs inconnus / périmés ---
    if not args.no_psa:
        wanted = []
        seen = set()
        for it in items:
            cert = (cache["items"].get(it["id"]) or {}).get("cert")
            if not cert or cert in seen:
                continue
            seen.add(cert)
            f = cache["certs"].get(cert)
            if f and "error" not in f and age_days(f.get("checked_at", "")) < CERT_TTL_DAYS \
               and "pop" in f:   # (re)prise si la fiche est d'avant l'ajout de la population
                continue
            if f and f.get("error") and age_days(f.get("checked_at", "")) < 1:
                continue  # échec récent : on laisse reposer
            wanted.append(cert)
        wanted = wanted[:args.max_lookups]
        if V:
            print(f"PSA : {len(wanted)} fiche(s) à ouvrir")
        if wanted:
            got = psa_lookup_batch(wanted, verbose=V)
            for cert, fiche in got.items():
                fiche["checked_at"] = iso()
                cache["certs"][cert] = fiche

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
