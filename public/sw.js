// Service worker de "Ma Collection Pokémon"
// Trois stratégies : l'appli en cache, les données réseau-d'abord, les images en cache.
//
// ⚠️ À CHAQUE MISE À JOUR DE L'APPLI, INCRÉMENTER LE NUMÉRO CI-DESSOUS.
// C'est ce qui déclenche le remplacement de l'ancienne version chez les utilisateurs.
const VERSION = "v15";

const APP_CACHE  = "app-" + VERSION;   // la page, le manifeste, les icônes
const DATA_CACHE = "data-" + VERSION;  // les réponses de l'API TCGdex
const IMG_CACHE  = "img-" + VERSION;   // les images de cartes

const APP_FILES = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
];

// --- installation : on met l'appli en cache ---
// On n'active PAS tout de suite : la nouvelle version attend l'accord de l'utilisateur
// (bandeau « Mettre à jour »), pour ne pas recharger la page en pleine utilisation.
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(APP_CACHE).then((c) => c.addAll(APP_FILES))
  );
});

// Message envoyé par la page quand l'utilisateur accepte la mise à jour
self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "SKIP_WAITING") self.skipWaiting();
});

// --- activation : on supprime les caches des versions précédentes ---
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((n) => !n.endsWith(VERSION)).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Firebase (connexion, base de données) : jamais de cache, toujours le réseau.
  if (/googleapis\.com|firebaseio\.com|firebaseapp\.com|gstatic\.com/.test(url.hostname)) return;

  // 1) Navigation : on sert d'abord la page demandée (depuis le cache si on l'a),
  //    sinon le réseau. Le repli sur index.html n'intervient QUE hors-ligne,
  //    sinon toutes les autres pages du site seraient masquées par l'accueil.
  if (req.mode === "navigate") {
    e.respondWith(
      caches.match(req).then((hit) =>
        hit || fetch(req).catch(() => caches.match("./index.html"))
      )
    );
    return;
  }

  // 2) Images de cartes : le cache d'abord, sinon on télécharge puis on garde.
  if (/assets\.tcgdex\.net/.test(url.hostname) || /\.(png|jpe?g|webp|svg)$/i.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(IMG_CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit))
    );
    return;
  }

  // 3) Données TCGdex : le réseau d'abord (données fraîches),
  //    avec repli sur la dernière version connue si la connexion manque.
  if (/api\.tcgdex\.net/.test(url.hostname)) {
    e.respondWith(
      fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(DATA_CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // 4) Le reste (fichiers de l'appli) : cache d'abord, réseau ensuite.
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});
