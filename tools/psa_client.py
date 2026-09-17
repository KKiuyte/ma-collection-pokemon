#!/usr/bin/env python3
"""
Client psacard.com (compte connecté) : population par série et prix de vente par carte.

Ce que PSA expose, et comment on y accède (vérifié le 2026-09-17) :
- La recherche par nom et les prix sont derrière une CONNEXION (compte PSA gratuit).
- Une fois connecté, deux points d'entrée JSON suffisent, SANS navigateur :
    · POST /Pop/GetSetItems  → toutes les cartes d'une série avec population par note
      et l'identifiant PSA de chaque carte (SpecID)
    · GET  /api/psa/trpc/researchJourney.getPriceSummary → ventes par note d'une carte
      (quantité, moyenne, dernière) sur une fenêtre de N mois (timeRange = mois ; 0 = tout)
- Les pages d'index (années → séries) sont rendues côté serveur : simple GET.
- Seule la CONNEXION exige un navigateur (Playwright + playwright-stealth, Cloudflare).
  Les cookies obtenus sont réutilisés ensuite avec `requests` tant qu'ils sont valides.

Identifiants : variables PSA_EMAIL / PSA_PASSWORD, sinon ~/.psa.env (KEY=VALUE).
Cookies : PSA_COOKIE_FILE (défaut ~/.psa-cookies.json), jamais dans le dépôt.

    python tools/psa_client.py --test      # connexion, correspondance d'une série, pop, prix
"""
import base64
import html as H
import json
import os
import re
import sys
import time
import urllib.parse as up

import requests

BASE = "https://www.psacard.com"
SIGNIN = "https://app.collectors.com/signin?b=psa&r=https%3A%2F%2Fwww.psacard.com%2Fpop"
CATEGORY_TCG = "156940"          # « TCG Cards » dans le rapport de population
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
COOKIE_FILE = os.environ.get("PSA_COOKIE_FILE", os.path.expanduser("~/.psa-cookies.json"))
PAUSE = 1.2                      # entre deux requêtes : usage perso, on reste discret

# marqueurs de langue dans les noms de séries PSA (absence = anglais)
LANG_MARKERS = ["Japanese", "Chinese", "Simplified Chinese", "Korean", "Thai", "Indonesian",
                "German", "Italian", "Spanish", "Portuguese", "Dutch", "French", "Latin American"]
LANG_BY_TCGDEX = {"Français": "French", "Anglais": None, "Japonais": "Japanese", "Allemand": "German",
                  "Italien": "Italian", "Espagnol": "Spanish", "Chinois": "Chinese"}
# séries modernes nommées « Pokemon Mew FR-151 », « Pokemon Svi EN-Scarlet & Violet » : le code
# de langue précède le tiret (vu : EN, FR, It, de, ES, La = Latin American)
CODE_LANG = {"en": None, "fr": "French", "it": "Italian", "de": "German", "es": "Spanish",
             "la": "Latin American", "pt": "Portuguese", "jp": "Japanese", "ko": "Korean"}


# --------------------------------------------------------------------- identifiants
def load_credentials():
    email, pwd = os.environ.get("PSA_EMAIL"), os.environ.get("PSA_PASSWORD")
    if email and pwd:
        return email, pwd
    path = os.path.expanduser("~/.psa.env")
    if os.path.exists(path):
        env = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v
        if env.get("PSA_EMAIL") and env.get("PSA_PASSWORD"):
            return env["PSA_EMAIL"], env["PSA_PASSWORD"]
    raise SystemExit("Identifiants PSA absents : PSA_EMAIL/PSA_PASSWORD ou ~/.psa.env")


# --------------------------------------------------------------------- connexion
def _debug_shot(page, name):
    """Capture d'écran de diagnostic si PSA_DEBUG_DIR est défini (jamais dans le dépôt)."""
    d = os.environ.get("PSA_DEBUG_DIR")
    if not d:
        return
    try:
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, f"psa-{name}.png"))
    except Exception:
        pass


def login_with_browser(email, password, verbose=False):
    """Ouvre la page de connexion Collectors/PSA dans Chromium furtif, renvoie les cookies.
    Flux observé : champ e-mail → « Continue » → champ mot de passe (Vaadin) → Entrée."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    with Stealth().use_sync(sync_playwright()) as p:
        br = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = br.new_context(user_agent=UA, locale="fr-CA", viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto(SIGNIN, wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        # bannière cookies (Osano) : on la ferme pour qu'elle n'intercepte rien
        for label in ("Tout rejeter", "Reject All", "Accepter tout", "Accept All"):
            try:
                b = page.get_by_role("button", name=label)
                if b.count():
                    b.first.click(timeout=2000)
                    time.sleep(0.8)
                    break
            except Exception:
                pass
        box = page.query_selector('input[type="email"], input[name*="mail" i], input[autocomplete="username"]')
        if not box:
            _debug_shot(page, "signin-no-email")
            br.close()
            raise RuntimeError("PSA : champ e-mail introuvable sur la page de connexion")
        box.click()
        box.fill(email)
        time.sleep(0.8)          # les champs Vaadin synchronisent leur valeur avec un léger délai
        pwd = page.query_selector('input[type="password"]')
        if not pwd:
            box.press("Enter")
            for _ in range(10):
                time.sleep(1.5)
                pwd = page.query_selector('input[type="password"]')
                if pwd:
                    break
        if not pwd:
            _debug_shot(page, "signin-no-password")
            br.close()
            raise RuntimeError("PSA : champ mot de passe introuvable")
        pwd.click()
        pwd.fill(password)
        time.sleep(0.8)
        pwd.press("Enter")
        # ⚠️ après connexion l'URL peut rester un moment sur /signin alors que la page cible est
        # déjà affichée : le vrai signal de succès est le cookie accessToken posé sur psacard.com
        ok = False
        for _ in range(25):
            time.sleep(2)
            cookies = ctx.cookies()
            if any(c["name"] == "accessToken" and "psacard.com" in c["domain"] for c in cookies):
                ok = True
                break
            if "Sign In" not in (page.title() or "") and "signin" not in page.url:
                ok = True
                break
        if not ok:
            _debug_shot(page, "signin-refused")
        else:
            # le cookie cf_clearance de psacard.com (celui qui fait passer `requests` devant
            # Cloudflare) est posé par la page cible, un peu après la connexion : on l'attend,
            # en visitant explicitement une page psacard.com si besoin
            for i in range(12):
                cookies = ctx.cookies()
                if any(c["name"] == "cf_clearance" and c["domain"].endswith("psacard.com") for c in cookies):
                    break
                if i == 3:
                    try:
                        page.goto(f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}", wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        pass
                time.sleep(2)
        time.sleep(2)
        cookies = ctx.cookies()
        br.close()
    if not ok:
        raise RuntimeError("PSA : connexion refusée (mot de passe ? vérification ? captcha ?)")
    if verbose:
        print(f"  connexion PSA OK ({len(cookies)} cookies)")
    return cookies


class PsaSession:
    """Session HTTP connectée à PSA. Réutilise les cookies en cache, se reconnecte si besoin."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8"})
        self._years = None
        self._sets_by_year = {}
        self._cookies_loaded = False

    # --- cookies -------------------------------------------------------
    def _apply_cookies(self, cookies):
        self.s.cookies.clear()
        for c in cookies:
            self.s.cookies.set(c["name"], c["value"], domain=c["domain"].lstrip("."), path=c.get("path", "/"))
        self._cookies_loaded = True

    def _load_cookie_file(self):
        try:
            with open(COOKIE_FILE, encoding="utf-8") as f:
                self._apply_cookies(json.load(f))
            return True
        except Exception:
            return False

    def _save_cookie_file(self, cookies):
        try:
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f)
            os.chmod(COOKIE_FILE, 0o600)
        except Exception:
            pass

    def alive(self):
        """Vrai si la session est acceptée (l'index catégorie ne renvoie pas vers la connexion).
        Un refus isolé de Cloudflare ne doit pas passer pour une session morte : deux essais."""
        for attempt in (1, 2):
            try:
                r = self.s.get(f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}", timeout=40, allow_redirects=True)
                if r.status_code == 200 and "signin" not in r.url and "<title>Just a moment" not in r.text:
                    return True
                if "signin" in r.url:
                    return False          # vraiment déconnecté
            except Exception:
                pass
            if attempt == 1:
                time.sleep(6)
        return False

    def ensure(self):
        if not self._cookies_loaded:
            self._load_cookie_file()
        if self._cookies_loaded and self.alive():
            if self.verbose:
                print("  session PSA : cookies en cache valides")
            return self
        email, pwd = load_credentials()
        cookies = login_with_browser(email, pwd, verbose=self.verbose)
        self._apply_cookies(cookies)
        self._save_cookie_file(cookies)
        if not self.alive():
            raise RuntimeError("PSA : connecté mais la session n'est pas acceptée")
        return self

    # --- helpers HTTP ----------------------------------------------------
    def _relogin(self):
        """Cookies périmés ou refusés (403 / renvoi vers la connexion) : on se reconnecte une fois."""
        if self.verbose:
            print("  session PSA refusée : reconnexion…")
        email, pwd = load_credentials()
        cookies = login_with_browser(email, pwd, verbose=self.verbose)
        self._apply_cookies(cookies)
        self._save_cookie_file(cookies)

    def _request(self, method, url, **kw):
        """Cloudflare refuse parfois UNE requête (403 « Just a moment ») alors que la session est
        bonne : on attend et on réessaie deux fois avant d'envisager une reconnexion."""
        time.sleep(PAUSE)
        for attempt in range(4):
            r = self.s.request(method, url, timeout=60, **kw)
            refused = r.status_code in (401, 403) or "signin" in r.url or "<title>Just a moment" in r.text[:2000]
            if not refused:
                return r
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
            elif attempt == 2:
                self._relogin()
            else:
                r.raise_for_status()
        return r

    def _get(self, url, **kw):
        return self._request("GET", url, **kw)

    def _post(self, url, **kw):
        return self._request("POST", url, **kw)

    # --- index des années et des séries ---------------------------------
    def years(self):
        """{ '2022': '/pop/tcg-cards/2022/205607', ... }"""
        if self._years is None:
            t = self._get(f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}").text
            self._years = {y: h for h, y in sorted(set(re.findall(r'href="(/pop/tcg-cards/(\d{4})/\d+)"', t)))}
        return self._years

    def pokemon_sets(self, year):
        """Séries Pokémon d'une année : [{id, slug, name, lang}] (lang = None pour l'anglais)."""
        year = str(year)
        if year in self._sets_by_year:
            return self._sets_by_year[year]
        path = self.years().get(year)
        out = []
        if path:
            t = self._get(BASE + path).text
            for _, slug, sid, name in re.findall(
                    r'href="(/pop/tcg-cards/%s/([^"/]+)/(\d+))"[^>]*>(.*?)</a>' % year, t, re.S):
                if not slug.lower().startswith("pokemon"):
                    continue
                clean = re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', '', name))).strip()
                lang = next((m for m in LANG_MARKERS if re.search(r'\b' + re.escape(m) + r'\b', clean)), None)
                if lang is None:
                    mc = re.match(r'^Pokemon\s+\S+\s+([A-Za-z]{2})-', clean)
                    if mc and mc.group(1).lower() in CODE_LANG:
                        lang = CODE_LANG[mc.group(1).lower()]
                out.append({"id": sid, "slug": slug, "name": clean, "lang": lang, "year": year})
        self._sets_by_year[year] = out
        return out

    # --- population d'une série -----------------------------------------
    def pop_set(self, heading_id):
        """Toutes les cartes d'une série PSA avec population par note.
        Renvoie [{SpecID, SubjectName, CardNumber, Variety, Grade1..Grade10, GradeTotal, ...}]."""
        rows, start = [], 0
        while True:
            r = self._post(f"{BASE}/Pop/GetSetItems",
                           # ⚠️ en-têtes VOLONTAIREMENT minimaux : ajouter Origin/Content-Type/Accept
                           # « comme un navigateur » déclenche le challenge Cloudflare (vérifié 2026-09-17)
                           headers={"X-Requested-With": "XMLHttpRequest",
                                    "Referer": f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}"},
                           data={"draw": 1, "start": start, "length": 500, "search": "",
                                 "headingID": heading_id, "categoryID": CATEGORY_TCG, "isPSADNA": "false"})
            d = r.json()
            batch = [x for x in d.get("data", []) if x.get("SpecID")]
            rows.extend(batch)
            total = int(d.get("recordsFiltered") or 0)
            start += 500
            if start >= total or not batch:
                break
        return rows

    # --- ventes d'une carte -----------------------------------------------
    def price_summary(self, spec_id, months=6):
        """Ventes par note : {grade: {quantity, averagePrice, latestPrice, minimumPrice, maximumPrice}}.
        months=0 → toutes époques."""
        inp = {"json": {"specId": str(spec_id), "department": "psa", "salesSummaryType": "GRADES",
                        "gradingType": "ALL", "qualifiers": "NON_QUALIFIERS", "timeRange": int(months)}}
        q = up.quote(json.dumps({"0": base64.b64encode(json.dumps(inp).encode()).decode()}))
        r = self._get(f"{BASE}/api/psa/trpc/researchJourney.getPriceSummary?batch=1&input={q}",
                      headers={"Accept": "*/*", "Referer": f"{BASE}/spec/psa/{spec_id}"})
        try:
            summary = r.json()[0]["result"]["data"]["json"]["salesSummary"]
        except Exception:
            return {}
        out = {}
        for g in summary:
            grade = g.get("grade")
            m = g.get("metrics") or {}
            if grade is None or not m.get("quantity"):
                continue
            out[float(grade)] = {k: m.get(k) for k in
                                 ("quantity", "averagePrice", "latestPrice", "minimumPrice", "maximumPrice")}
        return out


# --------------------------------------------------------------------- correspondance
def _norm(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


EXTRA_WORDS = ("mini tin", "tin", "collection", "deck", "box", "promo", "prize pack", "championship",
               "insert", "energies", "trainer kit", "battle academy", "starter")


def match_set(session, en_set_name, serie_name, release_year, lang=None):
    """Retrouve la série PSA correspondant à une série TCGdex.
    lang : marqueur PSA ('French', 'Japanese'…) ou None pour l'anglais.
    Renvoie (meilleur candidat ou None, liste des candidats scorés)."""
    target = _norm(en_set_name)
    serie = _norm(serie_name)
    wants_extra = any(w in target for w in EXTRA_WORDS)
    cands = []
    for y in (release_year, release_year + 1, release_year - 1):
        for st in session.pokemon_sets(y):
            if (st["lang"] or None) != (lang or None):
                continue
            name = _norm(st["name"])
            body = re.sub(r'^pokemon ', '', name)
            if st["lang"]:
                body = re.sub(r'\b' + re.escape(_norm(st["lang"])) + r'\b', ' ', body)
            body = re.sub(r'^[a-z0-9]{2,4} (en|fr|it|de|es|la|pt|jp|ko) ', '', body)   # « svi en-… », « mew fr-… »
            body = re.sub(r'\s+', ' ', body).strip()
            score = 0
            if body == target or body == f"{serie} {target}".strip():
                score = 100
            elif target in ("base set", "base") and body in ("game", ""):
                score = 100   # PSA nomme le Set de Base « Pokemon Game » (EN) ou juste « Pokemon French »
            elif re.search(r'\b' + re.escape(target) + r'\b', body):
                score = 60
                if serie and serie in body:
                    score += 10
                if not wants_extra and any(w in body for w in EXTRA_WORDS):
                    score -= 30
                score -= max(0, len(body.split()) - len(target.split()) - len(serie.split())) * 2
            if score > 0:
                score -= abs(int(st["year"]) - release_year) * 5
                cands.append((score, st))
    cands.sort(key=lambda x: -x[0])
    best = cands[0][1] if cands and cands[0][0] >= 40 else None
    return best, cands


# --------------------------------------------------------------------- test
if __name__ == "__main__":
    if "--test" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    ps = PsaSession(verbose=True).ensure()
    print("années :", list(ps.years())[:3], "…", list(ps.years())[-3:])
    for en, serie, year, lang in (("Silver Tempest", "Sword & Shield", 2022, None),
                                  ("Journey Together", "Scarlet & Violet", 2025, None),
                                  ("151", "Scarlet & Violet", 2023, None),
                                  ("Base Set", "Base", 1999, "French")):
        best, cands = match_set(ps, en, serie, year, lang)
        print(f"\n{en!r} ({serie}, {year}, {lang or 'EN'}) → {best['name'] if best else 'AUCUNE'} "
              f"[{best['id'] if best else '-'}]")
        for sc, st in cands[:4]:
            print(f"     {sc:>4}  {st['year']}  {st['name']}  ({st['id']})")
    rows = ps.pop_set(222927)   # Silver Tempest EN
    print(f"\npop Silver Tempest : {len(rows)} cartes ; ex. :",
          [(r['CardNumber'], r['SubjectName'], r['Grade9'], r['Grade10']) for r in rows[:3]])
    lugia = next((r for r in rows if r["SubjectName"].lower().startswith("lugia v") and r["CardNumber"] == "186"), None)
    if lugia:
        print("Lugia V 186 :", lugia["SpecID"], "pop9", lugia["Grade9"], "pop10", lugia["Grade10"])
        print("  ventes 6 mois :", ps.price_summary(lugia["SpecID"], 6))
