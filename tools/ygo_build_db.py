#!/usr/bin/env python3
"""Construit la base de cartes Yu-Gi-Oh de l'appli (public/yugioh/db.json) et, sur demande,
télécharge + convertit les vignettes (public/yugioh/img/{id}.webp).

Source : API communautaire YGOPRODeck (https://ygoprodeck.com/api-guide/), gratuite, sans clé.
Ses règles : ≤ 20 requêtes/seconde, stocker les données localement (ce fichier), et NE PAS
afficher ses images en direct depuis le site (blocage d'IP) → on les réhéberge nous-mêmes.

    python tools/ygo_build_db.py              # db.json seulement (2 appels API + sets)
    python tools/ygo_build_db.py --images     # + vignettes manquantes (≈ 13 000 au 1er passage)

Format de db.json (compact, ~4 Mo, servi gzippé) :
  { "built": "2026-11-02T…", "rar": ["Common", "Rare", …],
    "sets": [ {"c":"LOB", "n":"Legend of Blue Eyes White Dragon", "d":"2002-03-08", "k":355} ],
    "cards": [ {"id":46986414, "n":"Magicien Sombre", "en":"Dark Magician", "t":"normal",
                "ty":"Normal Monster", "eur":"0.02", "s":[["LOB-EN005", 7, "12.30", 412], …],
                "im":[46986414, 36996508, …]} ] }
  s = impressions : [code anglais, index de rareté dans rar, prix TCGplayer en $, index du set dans sets]
  im = identifiants d'image (illustration de base puis illustrations alternatives)
"""
import argparse
import concurrent.futures as cf
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

try:
    from PIL import Image  # requis seulement pour --images
except ImportError:  # pragma: no cover
    Image = None

API = "https://db.ygoprodeck.com/api/v7/"
IMG = "https://images.ygoprodeck.com/images/cards_small/{}.jpg"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "public", "yugioh")
UA = "ma-collection-pokemon/yugioh (usage personnel, cache local)"


def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"  réessai ({e})", file=sys.stderr)
            time.sleep(3 * (i + 1))


def get_json(url):
    return json.loads(get(url).decode("utf-8"))


def build_db():
    print("API : cartes FR…")
    fr = get_json(API + "cardinfo.php?language=fr")["data"]
    time.sleep(0.5)
    print("API : cartes EN…")
    en = get_json(API + "cardinfo.php")["data"]
    time.sleep(0.5)
    print("API : sets…")
    sets = get_json(API + "cardsets.php")

    en_by_id = {c["id"]: c for c in en}
    fr_by_id = {c["id"]: c for c in fr}
    rarities = []
    rar_idx = {}

    def ridx(name):
        if name not in rar_idx:
            rar_idx[name] = len(rarities)
            rarities.append(name)
        return rar_idx[name]

    set_list = [{"c": s.get("set_code", ""), "n": s["set_name"], "d": s.get("tcg_date", ""),
                 "k": s.get("num_of_cards", 0)} for s in sets]
    set_idx = {s["n"]: i for i, s in enumerate(set_list)}

    def sidx(name, code):
        if name not in set_idx:  # set cité par une carte mais absent de cardsets.php
            set_idx[name] = len(set_list)
            set_list.append({"c": code.split("-")[0], "n": name, "d": "", "k": 0})
        return set_idx[name]

    cards = []
    # Toutes les cartes EN (certaines n'ont pas de nom FR : on garde le nom anglais)
    for c in en:
        f = fr_by_id.get(c["id"])
        imp = []
        for s in c.get("card_sets", []):
            price = s.get("set_price") or "0"
            imp.append([s["set_code"], ridx(s["set_rarity"]), price, sidx(s["set_name"], s["set_code"])])
        prices = (c.get("card_prices") or [{}])[0]
        entry = {
            "id": c["id"],
            "n": (f or c)["name"],
            "en": c["name"],
            "t": c.get("frameType", ""),
            "ty": c.get("type", ""),
            "s": imp,
            "im": [i["id"] for i in c.get("card_images", [])] or [c["id"]],
        }
        if prices.get("cardmarket_price") not in (None, "0", "0.00"):
            entry["eur"] = prices["cardmarket_price"]
        if prices.get("tcgplayer_price") not in (None, "0", "0.00"):
            entry["usd"] = prices["tcgplayer_price"]
        cards.append(entry)

    db = {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rar": rarities,
        "sets": set_list,
        "cards": cards,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "db.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"db.json : {len(cards)} cartes ({len(fr)} avec nom FR), {len(sets)} sets, "
          f"{len(rarities)} raretés, {os.path.getsize(path)/1e6:.1f} Mo")
    return db


THUMB_W = 168       # largeur des vignettes réhébergées (268 px à la source) : ~8 Ko/carte en webp q70
THUMB_Q = 70        # 14 800 vignettes → ~130 Mo dans le dépôt ; q78 plein format aurait fait 320 Mo


def shrink(im):
    """Réduit une image à THUMB_W de large (jamais agrandie)."""
    if im.width > THUMB_W:
        im = im.resize((THUMB_W, round(im.height * THUMB_W / im.width)), Image.LANCZOS)
    return im


def fetch_images(db, workers=6, quality=THUMB_Q):
    img_dir = os.path.join(OUT_DIR, "img")
    os.makedirs(img_dir, exist_ok=True)
    wanted = sorted({i for c in db["cards"] for i in c["im"]})
    todo = [i for i in wanted if not os.path.exists(os.path.join(img_dir, f"{i}.webp"))]
    print(f"images : {len(wanted)} au total, {len(todo)} à télécharger")
    failed = []

    def one(i):
        try:
            raw = get(IMG.format(i))
            im = shrink(Image.open(io.BytesIO(raw)).convert("RGB"))
            im.save(os.path.join(img_dir, f"{i}.webp"), "WEBP", quality=quality, method=6)
            time.sleep(0.15)  # 6 fils × ~0.15 s ≈ bien sous 20 req/s
            return None
        except Exception as e:  # noqa: BLE001
            return (i, str(e))

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for n, res in enumerate(ex.map(one, todo), 1):
            if res:
                failed.append(res)
            if n % 500 == 0:
                print(f"  {n}/{len(todo)} ({time.time()-t0:.0f} s)")
    size = sum(os.path.getsize(os.path.join(img_dir, f)) for f in os.listdir(img_dir))
    print(f"images : terminé, {len(failed)} échec(s), dossier {size/1e6:.0f} Mo")
    for i, e in failed[:20]:
        print(f"  échec {i} : {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true", help="télécharger les vignettes manquantes")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    database = build_db()
    if args.images:
        fetch_images(database, workers=args.workers)
