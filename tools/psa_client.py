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
# index année → séries Pokémon, versionné dans le dépôt : les pages « pop » sont derrière un
# challenge Cloudflare interactif (case « je suis humain ») qui apparaît selon l'IP ; on ne les
# redemande donc que rarement, et on garde l'index même périmé si PSA refuse.
SETS_INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa-sets-index.json")
SETS_INDEX_TTL_DAYS = 60
PROBE_SPEC = "7922033"           # Radiant Charizard : sert à tester l'API des prix (session vivante ?)

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


class _Resp:
    """Réponse minimale (même surface que requests.Response) pour les requêtes faites
    depuis le navigateur."""

    def __init__(self, status, text, url):
        self.status_code, self.text, self.url = status, text, url

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} pour {self.url}", response=None)


def login_with_browser(email, password, verbose=False, keep=False):
    """Ouvre la page de connexion Collectors/PSA dans Chromium furtif, renvoie (cookies, handles).
    handles = navigateur laissé OUVERT si keep=True (pour faire les requêtes depuis le
    navigateur quand Cloudflare refuse `requests`), sinon None.
    Flux observé : champ e-mail → « Continue » → champ mot de passe (Vaadin) → Entrée."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    pw = sync_playwright().start()
    br = p_ctx = page = None
    try:
        br = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        p_ctx = br.new_context(user_agent=UA, locale="fr-CA", viewport={"width": 1366, "height": 900})
        page = p_ctx.new_page()
        Stealth().apply_stealth_sync(page)
        if os.environ.get("PSA_TRACE") == "1":
            # trace réseau SANS paramètres d'URL (jetons) : redirections et refus pendant la connexion
            def _resp(r):
                try:
                    if r.status >= 300 and r.request.resource_type in ("document", "xhr", "fetch"):
                        loc = (r.headers.get("location") or "").split("?")[0][:70]
                        print(f"      {r.status} {r.request.method} {r.url.split('?')[0][:80]}"
                              + (f" → {loc}" if loc else ""))
                except Exception:
                    pass
            page.on("response", _resp)
        cookies, ok = _login_flow(page, p_ctx, email, password)
    except Exception:
        for h in (br,):
            try:
                h.close()
            except Exception:
                pass
        pw.stop()
        raise
    if not ok:
        br.close()
        pw.stop()
        raise RuntimeError("PSA : connexion refusée (mot de passe ? vérification ? captcha ?)")
    if verbose:
        print(f"  connexion PSA OK ({len(cookies)} cookies)")
    if keep:
        return cookies, {"pw": pw, "browser": br, "ctx": p_ctx, "page": page}
    br.close()
    pw.stop()
    return cookies, None


def _login_flow(page, ctx, email, password):
    """Renvoie (cookies, ok). Voir login_with_browser."""
    if True:
        page.goto(os.environ.get("PSA_SIGNIN_URL") or SIGNIN, wait_until="domcontentloaded", timeout=45000)
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
            raise RuntimeError("PSA : champ mot de passe introuvable")
        pwd.click()
        pwd.fill(password)
        time.sleep(0.8)
        pwd.press("Enter")
        # ⚠️ après connexion l'URL peut rester un moment sur /signin alors que la page cible est
        # déjà affichée : le vrai signal de succès est le cookie accessToken posé sur psacard.com
        # ⚠️ (2026-10-05) SEUL ce cookie fait foi. L'ancien second critère « le titre n'est plus
        # Sign In » se déclenchait sur un état transitoire (page blanche entre deux redirections)
        # et annonçait « connexion OK » sans session : 2 runners sur 3 au diagnostic, d'où les
        # « connecté mais la session n'est pas acceptée » à répétition.
        ok = False
        trace = os.environ.get("PSA_TRACE") == "1"
        last = None
        for i in range(45):
            time.sleep(2)
            cookies = ctx.cookies()
            if any(c["name"] == "accessToken" and "psacard.com" in c["domain"] for c in cookies):
                ok = True
                break
            try:
                if i >= 6 and "signin" in page.url and "brandsignin" not in page.url \
                        and not page.query_selector('input[type="password"]') \
                        and page.query_selector('input[type="email"], input[autocomplete="username"]'):
                    break                  # refus silencieux : retour au formulaire e-mail vide
            except Exception:
                pass
            if trace:
                try:
                    state = (page.title() or "")[:40], page.url.split("?")[0][:70]
                except Exception:
                    state = ("(navigation en cours)", "")
                if state != last:
                    last = state
                    err = ""
                    try:
                        err = " | ".join(t.strip()[:80] for t in page.locator(
                            '[role="alert"], [class*="error" i], [slot="error-message"]').all_inner_texts() if t.strip())
                    except Exception:
                        pass
                    print(f"    [{2 * (i + 1):3d} s] {state[0]!r} {state[1]} {('— ' + err) if err else ''}")
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
        return cookies, ok


class PsaSession:
    """Session HTTP connectée à PSA. Réutilise les cookies en cache, se reconnecte si besoin."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8"})
        self._years = None
        self._sets_by_year = {}
        self._cookies_loaded = False
        self.handles = None            # navigateur gardé ouvert après connexion
        self.use_browser = os.environ.get("PSA_FORCE_BROWSER") == "1"   # requêtes via le navigateur

    def close(self):
        h, self.handles = self.handles, None
        if h:
            for k in ("browser",):
                try:
                    h[k].close()
                except Exception:
                    pass
            try:
                h["pw"].stop()
            except Exception:
                pass

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

    def _price_url(self, spec_id, months):
        inp = {"json": {"specId": str(spec_id), "department": "psa", "salesSummaryType": "GRADES",
                        "gradingType": "ALL", "qualifiers": "NON_QUALIFIERS", "timeRange": int(months)}}
        q = up.quote(json.dumps({"0": base64.b64encode(json.dumps(inp).encode()).decode()}))
        return f"{BASE}/api/psa/trpc/researchJourney.getPriceSummary?batch=1&input={q}"

    def alive(self, attempts=2, wait=6):
        """Vrai si la session est acceptée. On teste l'API des prix (pas les pages « pop », qui
        peuvent être derrière un challenge interactif même avec une session valide).
        Un refus isolé ne doit pas passer pour une session morte : plusieurs essais."""
        url = self._price_url(PROBE_SPEC, 6)
        hdrs = {"Accept": "*/*", "Referer": f"{BASE}/spec/psa/{PROBE_SPEC}"}
        for attempt in range(1, attempts + 1):
            try:
                if self.use_browser:
                    r = self._browser_request("GET", url, headers=hdrs)
                else:
                    r = self.s.get(url, timeout=40, headers=hdrs, allow_redirects=True)
                if r.status_code == 200 and "salesSummary" in r.text:
                    return True
                if "signin" in r.url or r.status_code == 401:
                    return False          # vraiment déconnecté
            except Exception:
                pass
            if attempt < attempts:
                time.sleep(wait)
        return False

    def ensure(self):
        if not self._cookies_loaded:
            self._load_cookie_file()
        if self._cookies_loaded and not self.use_browser and self.alive():
            if self.verbose:
                print("  session PSA : cookies en cache valides")
            return self
        self._relogin()
        return self

    def _relogin(self):
        """Reconnexion par navigateur. Si, même connecté, Cloudflare refuse `requests` (fréquent
        depuis une IP de datacenter), on garde le navigateur ouvert et on passe par lui."""
        if self.verbose:
            print("  session PSA : connexion par navigateur…")
        self.close()
        email, pwd = load_credentials()
        # la page de connexion peut elle aussi recevoir un challenge selon l'IP : on retente
        # avec un navigateur neuf, en laissant passer un peu de temps entre les essais
        last = None
        for attempt in range(1, 4):
            try:
                cookies, self.handles = login_with_browser(email, pwd, verbose=self.verbose, keep=True)
                break
            except RuntimeError as e:
                last = e
                if self.verbose:
                    print(f"  connexion PSA refusée (essai {attempt}/3) : {e}")
                if attempt < 3:
                    time.sleep(20 * attempt)
        else:
            raise last
        self._settle(self.handles["page"])
        cookies = self.handles["ctx"].cookies()
        self._apply_cookies(cookies)
        self._save_cookie_file(cookies)
        if not self.use_browser and self.alive(attempts=3, wait=8):
            self.close()               # `requests` passe : pas besoin de garder le navigateur
            return
        self.use_browser = True
        if self.verbose:
            print("  Cloudflare refuse `requests` : les requêtes passeront par le navigateur")
        if not self.alive(attempts=3, wait=8):
            raise RuntimeError("PSA : connecté mais la session n'est pas acceptée, même via le navigateur")

    @staticmethod
    def _challenged(page):
        t = (page.title() or "")
        return "Just a moment" in t or "Un instant" in t or "__cf_chl" in page.url

    def _settle(self, page, timeout=45):
        """Cloudflare interpose parfois un challenge automatique (« Un instant… ») à chaque
        navigation : on attend qu'il se résolve avant de faire quoi que ce soit."""
        end = time.time() + timeout
        reloaded = False
        while time.time() < end:
            if not self._challenged(page):
                return True
            time.sleep(2)
            if not reloaded and time.time() > end - 15:
                reloaded = True
                try:
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
        return not self._challenged(page)

    def _browser_goto(self, url):
        page = self.handles["page"]
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._settle(page)
        return _Resp(200 if not self._challenged(page) else 403, page.content(), page.url)

    def _browser_request(self, method, url, data=None, headers=None):
        """Requête exécutée DANS la page (fetch same-origin sur psacard.com), donc avec
        l'empreinte du vrai navigateur validée par Cloudflare. Une page HTML en GET passe par
        une vraie navigation (le challenge peut s'y résoudre) ; les appels JSON par fetch,
        après s'être assuré que la page courante n'est pas un challenge."""
        page = self.handles["page"]
        is_api = "/api/" in url or "/Pop/" in url
        if method == "GET" and not is_api:
            return self._browser_goto(url)
        if not page.url.startswith(BASE) or self._challenged(page):
            self._browser_goto(f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}")
        body = up.urlencode(data) if data else None
        hdrs = dict(headers or {})
        if body is not None:
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        for attempt in (1, 2):
            res = page.evaluate(
                """async ({url, method, body, headers}) => {
                     const r = await fetch(url, {method, headers, body, credentials: 'include', redirect: 'follow'});
                     return {status: r.status, url: r.url, text: await r.text()};
                   }""",
                {"url": url, "method": method, "body": body, "headers": hdrs})
            if res["status"] != 403 or attempt == 2:
                break
            # challenge servi au fetch : une navigation le résout, puis on réessaie
            self._browser_goto(f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}")
        return _Resp(res["status"], res["text"], res["url"])

    # --- helpers HTTP ----------------------------------------------------
    def _request(self, method, url, **kw):
        """Cloudflare refuse parfois UNE requête (403 « Just a moment ») alors que la session est
        bonne : on attend et on réessaie deux fois, puis on se reconnecte (et on bascule sur le
        navigateur si `requests` reste refusé)."""
        time.sleep(PAUSE)
        for attempt in range(4):
            if self.use_browser:
                r = self._browser_request(method, url, data=kw.get("data"), headers=kw.get("headers"))
            else:
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

    def _sets_index(self):
        if not hasattr(self, "_index"):
            try:
                with open(SETS_INDEX_FILE, encoding="utf-8") as f:
                    self._index = json.load(f)
            except Exception:
                self._index = {}
        return self._index

    def _save_sets_index(self):
        try:
            with open(SETS_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=1)
                f.write("\n")
        except Exception:
            pass

    def pokemon_sets(self, year):
        """Séries Pokémon d'une année : [{id, slug, name, lang}] (lang = None pour l'anglais).
        Cache versionné (psa-sets-index.json) : re-téléchargé après SETS_INDEX_TTL_DAYS, gardé
        tel quel si PSA refuse la page (challenge interactif)."""
        year = str(year)
        if year in self._sets_by_year:
            return self._sets_by_year[year]
        idx = self._sets_index()
        ent = idx.get(year)
        fresh = False
        if ent:
            try:
                age = time.time() - time.mktime(time.strptime(ent["at"], "%Y-%m-%dT%H:%M:%SZ"))
                fresh = age < SETS_INDEX_TTL_DAYS * 86400
            except Exception:
                fresh = False
        if ent and fresh:
            self._sets_by_year[year] = ent["sets"]
            return ent["sets"]
        out = None
        try:
            path = self.years().get(year)
            if path:
                t = self._get(BASE + path).text
                out = []
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
            else:
                out = []
        except Exception as e:
            if self.verbose:
                print(f"  index PSA {year} indisponible ({e.__class__.__name__}) : "
                      f"{'cache périmé conservé' if ent else 'aucun cache'}")
            out = ent["sets"] if ent else []
        else:
            idx[year] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sets": out}
            self._save_sets_index()
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

    # --- tRPC « researchJourney » (découvert le 2026-09-23 : le nom d'une procédure
    #     inconnue renvoie NOT_FOUND, une entrée incomplète renvoie le schéma attendu) ---
    def _trpc(self, proc, inp, referer=None):
        q = up.quote(json.dumps({"0": base64.b64encode(json.dumps({"json": inp}).encode()).decode()}))
        r = self._get(f"{BASE}/api/psa/trpc/{proc}?batch=1&input={q}",
                      headers={"Accept": "*/*", "Referer": referer or f"{BASE}/pop/tcg-cards/{CATEGORY_TCG}"})
        try:
            return r.json()[0]["result"]["data"]["json"]
        except Exception:
            return None

    def cert_details(self, cert):
        """Fiche d'un cert SANS passer par la page /cert (bloquée par un challenge interactif) :
        {certNumber, specId, grade:'MINT 9', gradeValue:'9', year, category, description,
         attributes:{subject, brand, cardNumber, variety,…}, isValid, voided}. None si inconnu."""
        d = self._trpc("researchJourney.getCertDetails",
                       {"certNumber": str(cert), "department": "PSA", "funkoLookup": False},
                       referer=f"{BASE}/cert/{cert}/psa")
        return d if d and d.get("certNumber") else None

    def population_summary(self, spec_id):
        """{grade10:{itemCount,…}, grade9:…, grade8_5:…, total:{…}, gemRate} pour une carte."""
        return self._trpc("researchJourney.getPopulationSummary",
                          {"specId": str(spec_id), "department": "psa"},
                          referer=f"{BASE}/spec/psa/{spec_id}")

    def spec_details(self, spec_id):
        """{specId, headingId, set:{setId, name, populationUrl,…}, longDescription,…}"""
        return self._trpc("researchJourney.getSpecDetails",
                          {"specId": str(spec_id), "department": "psa"},
                          referer=f"{BASE}/spec/psa/{spec_id}")

    # --- ventes d'une carte -----------------------------------------------
    def price_summary(self, spec_id, months=6):
        """Ventes par note : {grade: {quantity, averagePrice, latestPrice, minimumPrice, maximumPrice}}.
        months=0 → toutes époques."""
        r = self._get(self._price_url(spec_id, months),
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
