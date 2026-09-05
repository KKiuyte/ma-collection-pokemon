#!/usr/bin/env python3
"""
Étape 1 du système « bonnes affaires » : récupère les annonces Vinted de cartes
Pokémon gradées PSA et les écrit dans public/vinted-psa.json.

(PSA plutôt que PCA : marché le plus liquide, donc plus de points de comparaison
pour estimer un prix de référence à l'étape 2.)

    python tools/scrape_vinted_psa.py            # 6 pages, écrit public/vinted-psa.json
    python tools/scrape_vinted_psa.py --pages 10 # aller plus loin (prudence, cf. plus bas)
    python tools/scrape_vinted_psa.py --out /tmp/x.json --pages 2 --quiet

Ce que fait le script, et ce qu'il ne fait PAS
----------------------------------------------
- Il lit la **page catalogue HTML** de Vinted (rendue côté serveur), PAS l'API
  `/api/v2/` : celle-ci est bloquée par DataDome. La page HTML, elle, répond
  normalement à un simple client HTTP (vérifié le 2026-09-05).
- Il ne garde que les annonces dont le **titre contient « PSA »** (la recherche
  ramène aussi des correspondances vagues).
- Il extrait, par annonce : id, lien, titre, marque, état, prix affiché, prix
  total (protection acheteurs incluse), photo, et un **grade** (1 à 10) déduit
  du titre quand il est écrit.
- Il **ne cherche pas encore** à identifier la carte exacte dans le catalogue,
  ni à repérer les bonnes affaires. C'est l'étape 2, à décider une fois qu'on
  aura regardé les vraies données produites ici.

Prudence anti-blocage
---------------------
Les IP de GitHub Actions sont des plages datacenter connues. Pour ne pas attirer
DataDome : peu de pages (6 par défaut), une pause entre chaque, des en-têtes de
navigateur réalistes. Si une page revient vide alors que les précédentes avaient
des annonces, on s'arrête. Si la PREMIÈRE page ne donne rien (probable blocage),
le script sort en erreur SANS toucher au fichier existant — le workflow ne
committera donc pas un JSON vidé.

Stdlib uniquement (pas de pip install) : tourne tel quel sur ubuntu-latest.
"""
import argparse
import datetime as dt
import gzip
import html
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

BASE = "https://www.vinted.fr"
CATALOG = BASE + "/catalog"
QUERY = "psa pokemon"          # une seule requête pour l'instant (cf. docstring)
DEFAULT_PAGES = 6
PAUSE_S = 2.0                  # pause entre deux pages

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# --- extraction depuis le HTML (motifs vérifiés sur la vraie page) ---------------
RE_TILE = re.compile(
    r'data-testid="product-item-id-(\d+)--overlay-link"[^>]*?\stitle="([^"]*)"')
RE_URL = re.compile(
    r'<a\s+href="(/items/(\d+)-[^"]*)"[^>]*data-testid="product-item-id-\2--overlay-link"')
RE_IMG = re.compile(
    r'<img\s+src="([^"]*)"[^>]*data-testid="product-item-id-(\d+)--image--img"')

_N = r'(\d[\d\s  ]*[.,]\d{2})'
RE_SPLIT = re.compile(r'^(.*), Marque: ([^,]*), État: ([^,]*), ' + _N + r' €, ' + _N + r' €$')
# PSA note sur 10, entiers (1 à 10). On tolère un « .5 » au cas où un vendeur
# se trompe, mais le barème PSA officiel n'a pas de demi-points.
RE_GRADE = re.compile(r'PSA\s*n?[°o]?\s*(10|[1-9])(?:[.,]5)?', re.I)
RE_HAS_PSA = re.compile(r'\bPSA\b', re.I)
# numéro de carte imprimé : « 202/165 », « 098/SV-P », « 073/067 »…
RE_NUMBER = re.compile(r'\b(\d{1,3}\s*/\s*[A-Za-z0-9-]{1,6})\b')
# marqueurs d'une page de challenge DataDome plutôt que du catalogue
RE_CHALLENGE = re.compile(r'geo\.captcha-delivery\.com|interstitial|DataDome CAPTCHA', re.I)


def _money(s):
    return float(re.sub(r'[\s  ]', '', s).replace(',', '.'))


def make_opener():
    cj = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = list(HEADERS.items())
    return op


def fetch(opener, url, referer=None):
    req = urllib.request.Request(url)
    if referer:
        req.add_header("Referer", referer)
    with opener.open(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return raw.decode("utf-8", "replace")


def parse_page(doc):
    """Renvoie la liste des annonces exploitables d'une page (déjà filtrées PSA)."""
    tiles = {}
    for m in RE_TILE.finditer(doc):
        tiles[m.group(1)] = {"id": m.group(1), "raw": html.unescape(m.group(2))}
    for m in RE_URL.finditer(doc):
        if m.group(2) in tiles:
            tiles[m.group(2)]["url"] = BASE + html.unescape(m.group(1)).split("?")[0]
    for m in RE_IMG.finditer(doc):
        if m.group(2) in tiles:
            tiles[m.group(2)]["image"] = html.unescape(m.group(1))

    out = []
    for t in tiles.values():
        raw = t["raw"]
        sp = RE_SPLIT.match(raw)
        if not sp:
            continue
        title, brand, cond, price, total = sp.groups()
        if not RE_HAS_PSA.search(title):
            continue
        g = RE_GRADE.search(title)
        num = RE_NUMBER.search(title)
        out.append({
            "id": t["id"],
            "url": t.get("url", BASE + "/items/" + t["id"]),
            "title": title.strip(),
            "brand": brand.strip(),
            "condition": cond.strip(),
            "price": _money(price),
            "total_price": _money(total),
            "currency": "EUR",
            "grade": (g.group(1) if g else None),
            "number": (re.sub(r'\s', '', num.group(1)) if num else None),
            "image": t.get("image"),
        })
    return out


def scrape(pages, verbose=True):
    opener = make_opener()
    # 1) page d'accueil : pose les cookies de session (anon_id, tokens…)
    fetch(opener, BASE + "/")
    time.sleep(1.0)

    q = urllib.parse.quote(QUERY)
    by_id = {}
    for p in range(1, pages + 1):
        url = f"{CATALOG}?search_text={q}&order=newest_first&page={p}"
        doc = fetch(opener, url, referer=f"{CATALOG}?search_text={q}")
        rows = parse_page(doc)
        if verbose:
            print(f"  page {p}: {len(rows)} annonces PSA")
        if not rows:
            if p == 1:
                if RE_CHALLENGE.search(doc):
                    raise SystemExit("BLOQUÉ : page de challenge DataDome sur la page 1.")
                raise SystemExit("Aucune annonce sur la page 1 (structure changée ?).")
            break  # plus rien à paginer
        fresh = 0
        for r in rows:
            if r["id"] not in by_id:
                by_id[r["id"]] = r
                fresh += 1
        if fresh == 0:
            break  # pages qui se répètent : on arrête
        if p < pages:
            time.sleep(PAUSE_S)

    items = sorted(by_id.values(), key=lambda r: int(r["id"]), reverse=True)
    return items


def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    ap.add_argument("--out", default=os.path.join(root, "public", "vinted-psa.json"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    verbose = not args.quiet
    if verbose:
        print(f"Vinted — recherche « {QUERY} » — {args.pages} page(s) max")
    items = scrape(args.pages, verbose=verbose)

    with_grade = sum(1 for i in items if i["grade"])
    with_number = sum(1 for i in items if i["number"])
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "vinted.fr",
        "query": QUERY,
        "count": len(items),
        "with_grade": with_grade,
        "with_number": with_number,
        "items": items,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")

    if verbose:
        print(f"→ {len(items)} annonces PSA écrites dans {args.out}")
        print(f"  grade lu : {with_grade}/{len(items)} · numéro lu : {with_number}/{len(items)}")


if __name__ == "__main__":
    main()
