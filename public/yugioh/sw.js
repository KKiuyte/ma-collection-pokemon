// Service worker de « Ma Collection Yu-Gi-Oh! » (public/yugioh/), indépendant de celui
// de l'appli Pokémon (portée ./ = /yugioh/ seulement).
//
// ⚠️ À CHAQUE MISE À JOUR DE CETTE APPLI, INCRÉMENTER LE NUMÉRO CI-DESSOUS (y1 → y2 …).
const VERSION = "y3";

const APP_CACHE  = "ygo-app-" + VERSION;   // la page, le manifeste, les icônes
const DATA_CACHE = "ygo-data-" + VERSION;  // db.json (base de cartes + prix)
const IMG_CACHE  = "ygo-img-" + VERSION;   // vignettes img/*.webp

const APP_FILES = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
];

// cache:"reload" force le réseau (sinon le cache HTTP du navigateur peut resservir l'ancienne page)
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(APP_CACHE).then((c) =>
      Promise.all(APP_FILES.map((url) =>
        fetch(url, { cache: "reload" }).then((res) => c.put(url, res))
      ))
    )
  );
});

self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((n) => n.startsWith("ygo-") && !n.endsWith(VERSION)).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Firebase : jamais de cache
  if (/googleapis\.com|firebaseio\.com|firebaseapp\.com|gstatic\.com/.test(url.hostname)) return;
  // taux de change : réseau seulement (l'appli a son propre cache local)
  if (/frankfurter\.(app|dev)|er-api\.com/.test(url.hostname)) return;

  // navigation : page en cache si on l'a, sinon réseau ; repli sur l'accueil hors-ligne seulement
  if (req.mode === "navigate") {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).catch(() => caches.match("./index.html")))
    );
    return;
  }

  // vignettes : cache d'abord (elles ne changent jamais)
  if (/\.(png|jpe?g|webp|svg)$/i.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.ok) { const copy = res.clone(); caches.open(IMG_CACHE).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => hit))
    );
    return;
  }

  // base de cartes : réseau d'abord (prix frais), repli sur la dernière copie hors-ligne
  if (/db\.json$/.test(url.pathname)) {
    e.respondWith(
      fetch(req).then((res) => {
        if (res && res.ok) { const copy = res.clone(); caches.open(DATA_CACHE).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});
