import React, { useState, useEffect, useMemo, useCallback } from "react";

// ---------------------------------------------------------------------------
// Ma Collection Pokémon — V1
// Données : TCGdex (api.tcgdex.net) en français.
// Ta collection est sauvegardée d'une session à l'autre.
// ---------------------------------------------------------------------------

const API = "https://api.tcgdex.net/v2/fr";
const STORE_KEY = "collection_pokemon_v1";

// --- petit utilitaire de sauvegarde (tolérant aux erreurs) -----------------
async function loadOwned() {
  try {
    if (!window.storage) return {};
    const res = await window.storage.get(STORE_KEY);
    return res && res.value ? JSON.parse(res.value) : {};
  } catch {
    return {};
  }
}
async function saveOwned(owned) {
  try {
    if (!window.storage) return;
    await window.storage.set(STORE_KEY, JSON.stringify(owned));
  } catch {
    /* on ignore : la collection reste au moins en mémoire */
  }
}

const styles = `
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap');

* { box-sizing: border-box; }
.pk-root {
  --ink: #232a3d;
  --muted: #7b8494;
  --bg: #eef1f7;
  --surface: #ffffff;
  --gold: #ffcb05;
  --gold-deep: #f0a500;
  --navy: #2a3550;
  font-family: 'Nunito', system-ui, sans-serif;
  color: var(--ink);
  background: var(--bg);
  min-height: 100vh;
  padding: 20px 16px 64px;
}
.pk-wrap { max-width: 940px; margin: 0 auto; }

.pk-head { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.pk-ball {
  width: 34px; height: 34px; border-radius: 50%; flex: none;
  background: linear-gradient(#ee4b3b 0 50%, #fff 50% 100%);
  border: 3px solid var(--navy); position: relative;
}
.pk-ball::after {
  content: ""; position: absolute; inset: 0; margin: auto;
  width: 10px; height: 10px; background: #fff;
  border: 3px solid var(--navy); border-radius: 50%;
}
.pk-title { font-weight: 900; font-size: 26px; letter-spacing: -0.5px; }
.pk-sub { color: var(--muted); font-weight: 600; font-size: 14px; margin: 0 0 20px 46px; }

.pk-panel {
  background: var(--surface); border-radius: 18px; padding: 16px 18px;
  box-shadow: 0 6px 20px rgba(42,53,80,0.07); margin-bottom: 18px;
}
.pk-label { font-size: 12px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 1px; color: var(--muted); display: block; margin-bottom: 8px; }
.pk-select {
  width: 100%; font-family: inherit; font-weight: 700; font-size: 15px;
  color: var(--ink); padding: 12px 14px; border-radius: 12px;
  border: 2px solid #e2e6ef; background: #fbfcfe; -webkit-appearance: none;
}
.pk-select:focus { outline: none; border-color: var(--gold); }

.pk-progwrap { display: flex; align-items: center; gap: 14px; margin-top: 14px; }
.pk-bar { flex: 1; height: 14px; border-radius: 20px; background: #e6e9f1; overflow: hidden; }
.pk-fill {
  height: 100%; border-radius: 20px;
  background: linear-gradient(90deg, var(--gold-deep), var(--gold));
  transition: width .5s cubic-bezier(.2,.8,.2,1);
  box-shadow: 0 0 12px rgba(240,165,0,.5);
}
.pk-count { font-weight: 900; font-size: 15px; white-space: nowrap; }
.pk-count small { color: var(--muted); font-weight: 700; }

.pk-filters { display: flex; gap: 8px; margin-bottom: 16px; }
.pk-chip {
  font-family: inherit; font-weight: 800; font-size: 13px; cursor: pointer;
  padding: 8px 15px; border-radius: 999px; border: 2px solid #e2e6ef;
  background: var(--surface); color: var(--muted); transition: .15s;
}
.pk-chip.on { background: var(--navy); color: #fff; border-color: var(--navy); }

.pk-grid {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
}
.pk-slot {
  position: relative; cursor: pointer; border-radius: 10px;
  aspect-ratio: 63 / 88; border: none; padding: 0; background: none;
  transition: transform .12s ease;
}
.pk-slot:active { transform: scale(.94); }
.pk-slot img {
  width: 100%; height: 100%; object-fit: contain; border-radius: 8px;
  display: block; transition: filter .2s, opacity .2s;
}
.pk-slot.missing img { filter: grayscale(1) contrast(.9); opacity: .38; }
.pk-slot.missing::before {
  content: ""; position: absolute; inset: 0; border-radius: 10px;
  border: 2px dashed #c2c8d6;
}
.pk-slot.owned {
  box-shadow: 0 0 0 3px var(--gold), 0 6px 16px rgba(240,165,0,.35);
  animation: pop .3s ease;
}
@keyframes pop { 0%{transform:scale(.9)} 60%{transform:scale(1.05)} 100%{transform:scale(1)} }
.pk-check {
  position: absolute; top: -7px; right: -7px; width: 24px; height: 24px;
  background: var(--gold); color: var(--navy); border-radius: 50%;
  display: grid; place-items: center; font-weight: 900; font-size: 14px;
  box-shadow: 0 2px 6px rgba(0,0,0,.2);
}
.pk-num {
  position: absolute; bottom: 4px; left: 4px; font-size: 10px; font-weight: 800;
  color: #fff; background: rgba(35,42,61,.75); padding: 1px 6px; border-radius: 6px;
}

.pk-msg { text-align: center; padding: 48px 16px; color: var(--muted); font-weight: 700; }
.pk-spin {
  width: 28px; height: 28px; margin: 0 auto 12px; border-radius: 50%;
  border: 4px solid #e2e6ef; border-top-color: var(--gold); animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 480px) {
  .pk-grid { grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); }
  .pk-title { font-size: 22px; }
}
`;

export default function App() {
  const [sets, setSets] = useState([]);
  const [setId, setSetId] = useState("");
  const [cards, setCards] = useState([]);
  const [owned, setOwned] = useState({});
  const [filter, setFilter] = useState("all"); // all | owned | missing
  const [loadingSets, setLoadingSets] = useState(true);
  const [loadingCards, setLoadingCards] = useState(false);
  const [error, setError] = useState("");

  // Charger la collection sauvegardée + la liste des séries au démarrage
  useEffect(() => {
    loadOwned().then(setOwned);
    fetch(`${API}/sets`)
      .then((r) => r.json())
      .then((data) => {
        const list = Array.isArray(data) ? [...data].reverse() : []; // récent → ancien
        setSets(list);
        if (list.length) setSetId(list[0].id);
      })
      .catch(() => setError("Impossible de charger les séries. Vérifie ta connexion, puis recharge."))
      .finally(() => setLoadingSets(false));
  }, []);

  // Charger les cartes quand la série change
  useEffect(() => {
    if (!setId) return;
    setLoadingCards(true);
    setError("");
    fetch(`${API}/sets/${setId}`)
      .then((r) => r.json())
      .then((data) => setCards(data.cards || []))
      .catch(() => setError("Impossible de charger cette série. Réessaie."))
      .finally(() => setLoadingCards(false));
  }, [setId]);

  const toggle = useCallback((cardId) => {
    setOwned((prev) => {
      const next = { ...prev };
      if (next[cardId]) delete next[cardId];
      else next[cardId] = 1;
      saveOwned(next);
      return next;
    });
  }, []);

  const ownedInSet = useMemo(
    () => cards.filter((c) => owned[c.id]).length,
    [cards, owned]
  );
  const totalOwned = useMemo(() => Object.keys(owned).length, [owned]);
  const pct = cards.length ? Math.round((ownedInSet / cards.length) * 100) : 0;

  const shown = useMemo(() => {
    if (filter === "owned") return cards.filter((c) => owned[c.id]);
    if (filter === "missing") return cards.filter((c) => !owned[c.id]);
    return cards;
  }, [cards, owned, filter]);

  return (
    <div className="pk-root">
      <style>{styles}</style>
      <div className="pk-wrap">
        <div className="pk-head">
          <span className="pk-ball" />
          <span className="pk-title">Ma Collection</span>
        </div>
        <p className="pk-sub">
          {totalOwned} carte{totalOwned > 1 ? "s" : ""} dans ta collection
        </p>

        <div className="pk-panel">
          <label className="pk-label" htmlFor="set">Série</label>
          <select
            id="set"
            className="pk-select"
            value={setId}
            onChange={(e) => { setSetId(e.target.value); setFilter("all"); }}
            disabled={loadingSets}
          >
            {loadingSets && <option>Chargement…</option>}
            {sets.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>

          <div className="pk-progwrap">
            <div className="pk-bar">
              <div className="pk-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="pk-count">
              {ownedInSet}<small> / {cards.length}</small>
            </span>
          </div>
        </div>

        <div className="pk-filters">
          {[["all", "Toutes"], ["owned", "Possédées"], ["missing", "Manquantes"]].map(
            ([key, lbl]) => (
              <button
                key={key}
                className={`pk-chip ${filter === key ? "on" : ""}`}
                onClick={() => setFilter(key)}
              >
                {lbl}
              </button>
            )
          )}
        </div>

        {error && <div className="pk-msg">{error}</div>}

        {loadingCards && !error && (
          <div className="pk-msg"><div className="pk-spin" />Chargement des cartes…</div>
        )}

        {!loadingCards && !error && shown.length === 0 && (
          <div className="pk-msg">
            {filter === "missing"
              ? "Bravo, tu as toutes les cartes de cette série !"
              : filter === "owned"
              ? "Aucune carte de cette série pour l'instant. Touche une carte pour l'ajouter."
              : "Aucune carte à afficher."}
          </div>
        )}

        {!loadingCards && !error && shown.length > 0 && (
          <div className="pk-grid">
            {shown.map((c) => {
              const have = !!owned[c.id];
              const img = c.image ? `${c.image}/low.webp` : null;
              return (
                <button
                  key={c.id}
                  className={`pk-slot ${have ? "owned" : "missing"}`}
                  onClick={() => toggle(c.id)}
                  title={c.name}
                  aria-pressed={have}
                >
                  {img ? (
                    <img src={img} alt={c.name} loading="lazy" />
                  ) : (
                    <div style={{
                      width: "100%", height: "100%", display: "grid",
                      placeItems: "center", fontSize: 11, fontWeight: 800,
                      color: "#9aa2b1", padding: 6, textAlign: "center"
                    }}>{c.name}</div>
                  )}
                  {have && <span className="pk-check">✓</span>}
                  <span className="pk-num">{c.localId}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
