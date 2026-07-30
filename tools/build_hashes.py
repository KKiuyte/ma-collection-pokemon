#!/usr/bin/env python3
"""
Construit le catalogue d'empreintes visuelles d'une ou plusieurs séries Pokémon.

À lancer localement (Python 3 + pillow numpy requests installés) :
    pip install --user pillow numpy requests
    python build_hashes.py sv09              # une série
    python build_hashes.py sv09 sv08         # plusieurs
    python build_hashes.py --all             # toutes (~20 min, 13 Mo)
    python build_hashes.py --all --force     # tout refaire depuis zéro
    python build_hashes.py --merge           # fusionne tout en catalogue-fr.json

Puis copier le catalogue fusionné vers public/ et déployer (git push) :
    ~/hashes/catalogue-fr.json  →  public/catalogue-fr.json

REPRENABLE : les séries déjà traitées sont ignorées. Si le script s'interrompt,
relance simplement la même commande.

Tout est écrit dans  ~/hashes/  — TOUJOURS au même endroit, quel que soit le dossier
depuis lequel tu lances le script. C'est ce qui rend la reprise fiable après une
interruption. (Sous Windows : C:\\Users\\<toi>\\hashes)

⚠️ Le calcul de l'empreinte doit être REPRODUCTIBLE à l'identique en JavaScript.
   C'est pourquoi on n'utilise que du moyennage par blocs, sans interpolation :
   une définition sans ambiguïté, reproductible dans n'importe quel langage.
"""
import sys, os, json, base64, io, time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

API = "https://api.tcgdex.net/v2/fr"
# Dossier de sortie FIXE : le script écrit toujours au même endroit, quel que soit
# le répertoire depuis lequel on le lance. C'est ce qui rend la reprise fiable.
OUTDIR = os.path.expanduser("~/hashes")
GRID = 12          # grille 12x12 : compromis finesse / poids
WORKERS = 6          # modéré : l'API TCGdex est un service communautaire gratuit


# --------------------------------------------------------------- empreinte
def box_resize(arr, grid):
    """Moyenne exacte par blocs — définition identique en Python et en JS."""
    h, w = arr.shape[:2]
    ch = arr.shape[2] if arr.ndim == 3 else 1
    a = arr.reshape(h, w, ch).astype(np.float64)
    ys = (np.arange(grid + 1) * h / grid).astype(int); ys[-1] = h
    xs = (np.arange(grid + 1) * w / grid).astype(int); xs[-1] = w
    out = np.empty((grid, grid, ch), np.float64)
    for i in range(grid):
        y0, y1 = ys[i], max(ys[i + 1], ys[i] + 1)
        for j in range(grid):
            x0, x1 = xs[j], max(xs[j + 1], xs[j] + 1)
            out[i, j] = a[y0:y1, x0:x1].reshape(-1, ch).mean(0)
    return out


def fingerprint(rgb):
    """Renvoie (luma, chroma), deux grilles 12x12 en uint8.

    - chroma : r/(r+g+b) et g/(r+g+b) → la couleur SANS l'intensité,
               donc insensible à l'éclairage. C'est le signal principal.
    - luma   : structure claire/sombre, normalisée. Signal d'appoint,
               utile pour départager deux cartes de couleur voisine.
    """
    small = box_resize(rgb.astype(np.float64), GRID)
    s = small.sum(axis=2, keepdims=True) + 1e-6
    chroma = np.clip(np.round(small[:, :, :2] / s * 255.0), 0, 255).astype(np.uint8)

    lum = 0.299 * small[:, :, 0] + 0.587 * small[:, :, 1] + 0.114 * small[:, :, 2]
    lum = (lum - lum.mean()) / (lum.std() + 1e-6)
    luma = np.clip(np.round(lum * 40 + 128), 0, 255).astype(np.uint8)
    return luma, chroma


def encode(rgb):
    luma, chroma = fingerprint(rgb)
    return (base64.b64encode(luma.tobytes()).decode(),
            base64.b64encode(chroma.tobytes()).decode())


# ------------------------------------------------------------------ réseau
session = requests.Session()
session.headers["User-Agent"] = "ma-collection-pokemon/1.0 (projet perso)"


def fetch_json(url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=30); r.raise_for_status()
            return r.json()
        except Exception:
            if i == tries - 1: raise
            time.sleep(1.5 * (i + 1))


def process_card(card):
    img_url = card.get("image")
    if not img_url:
        return None
    for quality in ("high", "low"):
        try:
            r = session.get(f"{img_url}/{quality}.webp", timeout=30)
            if r.status_code != 200:
                continue
            rgb = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.uint8)
            l, c = encode(rgb)
            return {"id": card["id"], "n": card.get("localId", ""),
                    "t": card.get("name", ""), "i": img_url, "l": l, "c": c}
        except Exception:
            continue
    return None


def build_set(set_id, force=False):
    path = os.path.join(OUTDIR, f"hashes-{set_id}.json")
    if os.path.exists(path) and not force:
        print(f"= {set_id} : déjà fait, ignoré ({os.path.getsize(path)/1024:.0f} Ko)")
        return path
    print(f"\n=== {set_id} ===", flush=True)
    data = fetch_json(f"{API}/sets/{set_id}")
    cards, name = data.get("cards", []), data.get("name", set_id)
    print(f"{name} — {len(cards)} cartes", flush=True)

    out, done = [], 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for res in pool.map(process_card, cards):
            done += 1
            if res:
                out.append(res)
            if done % 25 == 0 or done == len(cards):
                print(f"  {done}/{len(cards)} — {len(out)} empreintes", flush=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"set": set_id, "name": name, "grid": GRID, "version": 1, "cards": out},
                  f, separators=(",", ":"), ensure_ascii=False)
    print(f"→ {path} ({os.path.getsize(path)/1024:.0f} Ko, {len(out)} cartes)")
    if len(out) < len(cards):
        print(f"  ⚠ {len(cards)-len(out)} carte(s) sans image exploitable")
    return path


def merge_all(out=None):
    """Fusionne tous les hashes-*.json en un seul fichier, prêt à déployer."""
    out = out or os.path.join(OUTDIR, "catalogue-fr.json")
    files = sorted(f for f in os.listdir(OUTDIR)
                   if f.startswith("hashes-") and f.endswith(".json"))
    if not files:
        print("Aucun fichier hashes-*.json à fusionner.")
        return
    cards, sets = [], []
    for f in files:
        try:
            d = json.load(open(os.path.join(OUTDIR, f), encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠ {f} illisible ({e}), ignoré")
            continue
        sets.append({"id": d.get("set"), "name": d.get("name")})
        for c in d.get("cards", []):
            c["s"] = d.get("set")          # série d'origine
            cards.append(c)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"name": f"Catalogue FR ({len(sets)} séries)", "grid": GRID,
                   "version": 1, "sets": sets, "cards": cards},
                  f, separators=(",", ":"), ensure_ascii=False)
    print(f"\n→ {out} : {len(cards)} cartes, {len(sets)} séries, "
          f"{os.path.getsize(out)/1024/1024:.1f} Mo")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    done = len([f for f in os.listdir(OUTDIR)
                if f.startswith("hashes-") and f.endswith(".json")])
    print(f"Dossier de travail : {OUTDIR}")
    print(f"Séries déjà traitées : {done}\n")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    force = "--force" in flags

    if "--merge" in flags:
        merge_all()
        return

    if not args and "--all" not in flags:
        print(__doc__)
        sys.exit(1)

    if "--all" in flags:
        sets = [x["id"] for x in fetch_json(f"{API}/sets")]
        todo = [x for x in sets
                if force or not os.path.exists(os.path.join(OUTDIR, f"hashes-{x}.json"))]
        print(f"{len(sets)} séries au total, {len(todo)} à traiter.")
        print("Le script est REPRENABLE : s'il s'interrompt, relance la même commande,")
        print("il reprendra où il s'est arrêté.\n")
    else:
        sets = args

    t0 = time.time()
    ok = fail = 0
    for i, x in enumerate(sets, 1):
        try:
            build_set(x, force)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"✗ Échec sur {x} : {e}")
        if len(sets) > 3 and i % 5 == 0:
            el = time.time() - t0
            eta = el / i * (len(sets) - i)
            print(f"--- {i}/{len(sets)} séries · {el/60:.0f} min écoulées · "
                  f"~{eta/60:.0f} min restantes ---", flush=True)

    files = [f for f in os.listdir(OUTDIR) if f.startswith("hashes-") and f.endswith(".json")]
    total = sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in files)
    print(f"\nTerminé : {ok} série(s) traitée(s), {fail} échec(s).")
    print(f"{len(files)} fichier(s) dans {OUTDIR}, {total/1024/1024:.1f} Mo au total.")


if __name__ == "__main__":
    main()
