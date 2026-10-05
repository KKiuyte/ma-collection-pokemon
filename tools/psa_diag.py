#!/usr/bin/env python3
"""Diagnostic : depuis cette machine, qu'est-ce que Cloudflare laisse passer une fois connecté à PSA ?
Pour chaque page d'ancrage : challenge ou non, puis appel de l'API des prix par fetch DANS la page.
Sert à choisir la page depuis laquelle psa_client fait ses requêtes navigateur.
    python tools/psa_diag.py
"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psa_client as P

ANCHORS = ["(page après connexion)", "/", "/spec/psa/" + P.PROBE_SPEC, "/priceguide",
           "/cert", "/myaccount", "/pop", "/pop/tcg-cards/" + P.CATEGORY_TCG]

FETCH = """async (url) => { try { const r = await fetch(url, {credentials:'include'});
  const t = await r.text(); return {status:r.status, head:t.slice(0,70)}; }
  catch(e) { return {status:-1, head:String(e).slice(0,70)}; } }"""


def main():
    try:
        ip = P.requests.get("https://api.ipify.org", timeout=10).text
        org = P.requests.get(f"https://ipinfo.io/{ip}/org", timeout=10).text.strip()
        print(f"IP {ip.rsplit('.', 1)[0]}.x — {org}")
    except Exception:
        pass
    email, pwd = P.load_credentials()
    os.environ["PSA_TRACE"] = "1"
    cookies = h = None
    for attempt in (1, 2, 3):
        try:
            entry = [P.SIGNIN, P.BASE + "/myaccount", P.BASE + "/myaccount"][attempt - 1]
            os.environ["PSA_SIGNIN_URL"] = entry
            print(f"--- essai de connexion {attempt} (navigateur neuf) — entrée {entry.split('?')[0]}")
            cookies, h = P.login_with_browser(email, pwd, verbose=True, keep=True)
            break
        except RuntimeError as e:
            print("CONNEXION ÉCHOUÉE :", e)
            time.sleep(15 * attempt)
    if not h:
        return
    page, ctx = h["page"], h["ctx"]
    names = sorted({c["name"] for c in cookies if c["domain"].endswith("psacard.com")})
    print("cookies psacard.com :", ", ".join(n for n in names if n in ("accessToken", "cf_clearance", "__cf_bm")))
    s = P.PsaSession()
    s._apply_cookies(cookies)
    url = s._price_url(P.PROBE_SPEC, 6)
    try:
        r = s.s.get(url, timeout=40, headers={"Accept": "*/*", "Referer": f"{P.BASE}/spec/psa/{P.PROBE_SPEC}"})
        print(f"requests → API prix : {r.status_code} {r.text[:60]!r}")
    except Exception as e:
        print("requests → API prix :", e.__class__.__name__)
    for a in ANCHORS:
        t0 = time.time()
        try:
            if a.startswith("/"):
                page.goto(P.BASE + a, wait_until="domcontentloaded", timeout=45000)
            end = time.time() + 20
            while time.time() < end and P.PsaSession._challenged(page):
                time.sleep(2)
            chal = P.PsaSession._challenged(page)
            html = page.content()
            box = "turnstile" in html.lower()
            res = page.evaluate(FETCH, url)
            ok = res["status"] == 200 and "salesSummary" in res["head"] or '"result"' in res["head"]
            print(f"{a:34s} challenge={'OUI' if chal else 'non'} turnstile={'oui' if box else 'non'} "
                  f"titre={page.title()[:28]!r} → fetch API {res['status']} {'OK' if ok else res['head']!r} "
                  f"({round(time.time() - t0)} s)")
        except Exception as e:
            print(f"{a:34s} ERREUR {e.__class__.__name__}: {str(e)[:80]}")
    h["browser"].close(); h["pw"].stop()


if __name__ == "__main__":
    main()
