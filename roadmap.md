# 🗺️ Roadmap — Ma Collection Pokémon

Liste des évolutions possibles. Rien n'est figé : on pioche dedans au fur et à mesure, **une chose à la fois**.

## ✅ Déjà fait

**Base**
- [x] Afficher les cartes d'une série (données TCGdex, en français)
- [x] Barre de progression + compteur par série
- [x] Filtres Toutes / Possédées / Manquantes / Souhaits
- [x] Fonctionne sur téléphone et ordinateur

**Recherche & navigation**
- [x] Recherche par nom
- [x] Recherche par numéro (« 066 » ou « 066/063 », le total ciblant la bonne série)
- [x] Recherche globale sur toutes les séries, résultats regroupés par série
- [x] Sélecteur de série avec recherche
- [x] Regroupement des séries par bloc / génération
- [x] Écran « toute ma collection » regroupé par série
- [x] Tri par numéro et par nom
- [x] Filtre par rareté (dans la série affichée)

**Fiche carte**
- [x] Fiche en grand au clic (image, nom, série, numéro)
- [x] Rareté affichée sur la fiche
- [x] Versions de carte (Normale, Reverse Holo, Holo, 1re édition, Promo)
- [x] Quantité, état et langue gérés **par exemplaire individuel** (au sein de chaque version)
- [x] Liste de souhaits (♥ + filtre dédié + vue globale)

**Prix & valeur**
- [x] Prix estimé **par version** (Cardmarket en €, repli TCGplayer en $)
- [x] Valeur totale de la collection, avec cache local rafraîchi une fois par jour
- [x] Cartes sans prix comptées à part (le total est un minimum, pas une estimation faussée)

**Compte & synchro (Firebase)**
- [x] Connexion Google et email/mot de passe
- [x] Stockage en ligne par utilisateur (Firestore), synchro temps réel entre appareils
- [x] Hébergement en ligne (Firebase Hosting)

**Application installable (PWA)**
- [x] Manifeste, icônes, mode plein écran
- [x] Service worker : appli en cache, données réseau-d'abord, images conservées
- [x] Fonctionnement hors-ligne (consultation, ajouts locaux)
- [x] Bouton d'installation dans l'en-tête (natif Android, instructions sur iPhone)
- [x] Bandeau « Nouvelle version disponible » avec mise à jour sur accord

**Design**
- [x] Palette beige/orange, panneau de contrôles regroupé
- [x] Barre latérale sur ordinateur, panneau compact sur mobile
- [x] Filtres en haut, 3 cartes par ligne sur mobile
- [x] Mode sombre (bascule mémorisée, suit le système par défaut)
- [x] Bouton retour en haut (apparaît après défilement)
- [x] **Navigation par onglets** (Série / Ma collection / Statistiques / Échange) au lieu de
      liens texte sous le titre — une ligne, défilement horizontal si besoin
- [x] **Icônes SVG inline** (thème, compte, installation, recherche, chevrons) à la place des
      emoji, qui rendaient différemment selon l'appareil
- [x] **États vides soignés** : icône discrète + texte, centrés dans l'espace disponible sur
      ordinateur
- [x] Noms de blocs de statistiques sur deux lignes plutôt que tronqués ; barre de progression
      empilée sous le nom sur écran étroit

**Statistiques**
- [x] Progression par bloc / génération
- [x] Répartition par rareté
- [ ] Ajouts récents (nécessite d'enregistrer une date d'ajout par carte — pas encore fait)

---

## 📸 En attente — Reconnaissance de carte par photo
Mise de côté après étude. **Les recherches sont consignées ici pour ne pas refaire le travail.**

Point clé : TCGdex ne fait **pas** de reconnaissance d'image. C'est un métier à part.

| Piste | Coût | Verdict |
|---|---|---|
| **A — OCR du numéro** (Tesseract.js dans le navigateur) | Gratuit, sans serveur | Réutilise la recherche « XXX/YYY » déjà en place. Fiabilité imparfaite (petit texte, reflets, angle). Inopérant sur cartes anciennes sans numéro. |
| **B — Ximilar** | ⚠️ **59 €/mois** (plan Business 100K obligatoire) | Excellent mais hors budget perso. Accès d'essai temporaire possible en écrivant à tech@ximilar.com. L'identification coûte 10 crédits/carte, mais le plan gratuit n'ouvre **pas** l'accès au service. |
| **B bis — CardSight AI** | Palier gratuit annoncé : **750 appels/mois** | 🔍 **À vérifier en premier si on relance le sujet.** Catalogue 12M cartes, API REST. Chiffres non vérifiés (marketing du fournisseur). |
| **C — Modèle de vision via le Worker** | Quelques centimes par appel | Souple, moins précis qu'un système entraîné sur les cartes. |
| **D — Empreintes visuelles en local** | Gratuit mais plusieurs Go | Écarté : revient au miroir complet de la base. |

⚠️ Dans tous les cas sauf A : la **clé d'API ne doit jamais être dans la page web**. Il faudrait
réactiver le Worker Cloudflare (`collection-sync.ariesam.workers.dev`) comme intermédiaire.

---

## 🛟 Priorité 1 — Sécurité des données
- [ ] **Exporter / importer** sa collection dans un fichier (sauvegarde indépendante du compte)
- [ ] Message d'avertissement avant toute action qui pourrait tout effacer

## 🔎 Priorité 2 — Confort
- [x] **Filtre par rareté aussi dans la recherche globale et la vue collection** : le filtre
      chargeait jusque-là les ids d'une seule série (celle affichée). Généralisé en
      `ensureRarityIdsForSets(setIds)` : précharge (en parallèle, en cache par
      `idSérie|rareté`) toutes les séries présentes dans les résultats, quelle que soit la vue.
      Recherche globale et Ma collection pouvant mélanger beaucoup de séries, le premier
      filtrage par une rareté rare peut déclencher plusieurs requêtes réseau (mise en cache
      ensuite, donc sans coût les fois suivantes dans la session).
- [x] **Liste d'échange** : regrouper automatiquement les doubles (≥ 2 exemplaires d'une
      **même version** — Normale et Holo comptent comme deux cartes distinctes)
- [ ] **Partage — accès géré entre comptes** (choix retenu plutôt que le lien anonyme) :
      ID1 autorise ID2 à voir ses souhaits / échanges / collection, par personne, révocable ;
      ID2 pourra aussi demander l'accès. Construit **par étapes** :
  - [x] **1a — Pseudo** : chaque compte a un pseudo unique (insensible à la casse, 3-20
        caractères `[A-Za-z0-9_-]`), stocké dans `users/{uid}` + registre `pseudos/{minuscule}`
        (unicité + recherche). Champ dans « Mon compte », réservation atomique par transaction.
        ⚠️ **Règles Firestore à publier** (`firestore.rules`, console) pour que ça fonctionne.
  - [x] **1b-1 — Octroi (côté propriétaire)** : dans « Mon compte », autoriser/révoquer par
        pseudo, périmètres **Souhaits** et **Échanges** (collection complète prévue plus tard,
        structure extensible via `SHARE_SCOPES`). Publication dans `shared_wishlist/{uid}` et
        `shared_trades/{uid}` (données du périmètre + liste `viewers`), tenues à jour à chaque
        sauvegarde. ⚠️ **Règles Firestore à republier** (`firestore.rules`).
  - [x] **1b-2 — Lecture seule (côté destinataire)** : nouvel onglet « Partagé » qui liste ce
        qu'on t'a partagé (requête `viewers array-contains moi` sur `shared_wishlist` /
        `shared_trades`), groupé par pseudo du propriétaire. Réutilise `cardButton` (grille) pour
        les souhaits et le style `trade-row` pour les échanges — cliquer sur une carte ouvre la
        fiche habituelle, qui agit sur TA collection (ex. l'ajouter à tes souhaits), jamais sur
        celle de la personne qui partage. Chargé une fois par connexion, bouton « Actualiser ».
  - [x] **2 — Demandes d'accès** : dans « Mon compte », ID2 demande l'accès (par pseudo, par
        périmètre) — document `share_requests/{proprio}_{demandeur}_{périmètre}` (id déterministe,
        redemander après refus republie le même document). ID1 voit ses demandes reçues en haut de
        « Mon compte » avec Accepter/Refuser ; Accepter réutilise `grantAccess()` (même octroi
        qu'à la main) puis supprime la demande. ID2 voit ses demandes envoyées en attente
        (chips, annulables). ⚠️ **Nouvelle collection Firestore `share_requests` : règles à
        publier** (`firestore.rules`) comme pour les étapes précédentes.
  - [x] **3 — Suggestions d'échange automatiques** : dans l'onglet « Partagé », nouvelle section
        « Suggestions d'échange » (fonction `tradeSuggestions()`) calculée à partir des données
        déjà chargées (`sharedList` + ta wishlist locale + `tradeEntries()`), sans rien stocker
        de plus. Par personne qui partage : « tu pourrais demander » (ses échanges partagés
        présents dans ta wishlist, nécessite qu'elle partage ses **Échanges**) et « tu pourrais
        proposer » (tes doubles présents dans sa wishlist partagée, nécessite qu'elle partage ses
        **Souhaits**). Un même vrai échange gagnant-gagnant apparaît dans les deux listes
        seulement si les deux périmètres sont partagés dans les deux sens ; sinon une seule
        direction s'affiche, ce qui reste utile. Réutilise le style `trade-row` existant
        (helper `tradeRow()` factorisé, aussi utilisé par les listes brutes de la même vue).
  - [x] **4 — Réorganisation : tout dans l'onglet « Partagé »** : l'octroi d'accès et les
        demandes vivaient dans « Mon compte », mélangés avec le pseudo — déplacés dans l'onglet
        « Partagé », qui gagne 3 sous-onglets : **Partages** (ce qu'on te partage, ex-contenu
        unique de l'onglet), **Comptes partagés** (à qui tu donnes accès, ex-« Partage en lecture
        seule ») et **Demandes d'accès** (reçues + en envoyer une nouvelle). « Mon compte » ne
        garde que le pseudo et la déconnexion. Au passage : le pseudo déjà enregistré s'affiche en
        lecture seule avec un bouton **Modifier**, qui ouvre le champ puis demande confirmation
        (`confirm()`) avant d'écraser un pseudo existant — évite un changement accidentel en un
        clic, vu que c'est ce qui permet aux autres de te retrouver. Corrigé au passage : un bouton
        `.big-btn` avec `flex:0 0 auto` sans `width:auto` gardait son `width:100%` comme base flex
        (`flex-shrink:0` empêchant de rétrécir) → débordement horizontal sur mobile.

  > **Écarté :** lien anonyme (pas de contrôle par personne) et intermédiaire serveur
  > (Cloud Function / Worker : surdimensionné pour de la lecture seule). Approche B « copie
  > publiée par périmètre avec liste d'autorisés » retenue : pas de backend, révocable,
  > n'expose jamais la collection principale.

## 💰 Priorité 3 — Prix, suite
- [ ] Suivre l'**évolution de la valeur** dans le temps (relevé mensuel dans Firestore)
- [ ] Surveiller le champ `variants_detailed` annoncé par TCGdex : il apportera les identifiants
      Cardmarket/TCGplayer **par version**, ce qui réglera le cas des Reverse Holo affichées en dollars

## 📈 Suivi (admin)
- [x] **Google Analytics for Firebase activé** (`measurementId` présent depuis le début mais
      jamais branché : le SDK n'était ni importé ni initialisé). Ajouté dans `index.html` :
      import de `firebase-analytics.js`, initialisation conditionnelle via `isSupported()`
      (ne casse rien si le navigateur bloque Analytics — navigation privée stricte, bloqueurs),
      et événements `login` / `sign_up` (avec `method: "google"` ou `"password"`) envoyés sur
      les 3 boutons de connexion. Pour Google, `getAdditionalUserInfo(result).isNewUser`
      distingue une première connexion (`sign_up`) d'un retour (`login`). Les métriques
      « nouveaux utilisateurs / utilisateurs actifs » apparaissent dans la console Firebase →
      Analytics (délai de traitement ~24-48 h, normal côté Google). Pas de page admin dans
      l'appli : la console Firebase suffit et ne demande aucune donnée en plus à stocker.
      ⚠️ **Analytics à activer dans le projet Firebase (console) si ce n'est pas déjà le cas**,
      sinon les événements sont envoyés mais rien ne s'affiche.

## 🐛 Corrigé — mise à jour invisible hors navigation privée
- [x] Le service worker incrémentait bien `VERSION`, mais son installation utilisait
      `caches.addAll()` : un `fetch()` simple, qui pouvait renvoyer la page déjà présente dans
      le **cache HTTP du navigateur** au lieu du réseau — la nouvelle version du service worker
      recachait alors l'ANCIENNE page. D'où le besoin systématique de la navigation privée
      (aucun cache HTTP à contourner) pour voir un déploiement. Corrigé par deux changements
      complémentaires : `sw.js` fetch chaque fichier avec `{ cache: "reload" }` (force le
      réseau, contourne le cache HTTP) ; `firebase.json` envoie désormais
      `Cache-Control: no-cache` sur les fichiers `*.html` et `sw.js` (le navigateur revalide
      toujours avant de réutiliser une copie en cache, au lieu de la servir telle quelle).

## 🎨 Priorité 4 — Finitions
- [x] Distinguer plusieurs exemplaires d'une **même version** (état/langue par copie individuelle,
      ajout via un petit formulaire qui redemande état/langue à chaque fois)

---

## 📱 Publication sur les stores — étudié, non retenu pour l'instant
- **Google Play** : faisable via TWA (Bubblewrap/PWABuilder), compte à 25 € une fois.
  ⚠️ Obstacle principal : pour un compte personnel créé après le 13/11/2023, il faut un
  **test fermé avec 12 testeurs pendant 14 jours consécutifs** avant la mise en production.
  Astuce : le test fermé permet déjà de distribuer l'appli à des proches sans passer en production.
- **App Store** : très difficile. Apple rejette les simples enveloppes de site (directive 4.2).
  99 $/an, Mac + Xcode nécessaires, et il faudrait de vraies fonctions natives.
  ⚠️ De plus, la connexion Google ne fonctionne pas dans une vue web embarquée sur iOS.
- ⚠️ **Propriété intellectuelle** : l'appli affiche des images et noms Pokémon. TCGdex précise
  n'être ni affilié ni approuvé par Nintendo/The Pokémon Company. Usage perso ≠ publication publique.

---

## 📝 Notes techniques
- Appli = **fichier HTML unique** (`index.html`) + `manifest.json` + `sw.js` + 3 icônes,
  hébergés sur **Firebase Hosting**.
- Connexion via **Firebase Authentication** (Google + email).
- Données dans **Firestore**, document `collections/{identifiant utilisateur}` :
  - `cards` : `{ idCarte: { v: { "Normale": [{cond, lang}, ...], "Reverse Holo": [...] } } }`
    (un objet `{cond, lang}` par exemplaire, la quantité = longueur du tableau)
  - `wishlist` : `{ idCarte: true }`
- Les anciens formats sont **convertis automatiquement** au chargement (fonction `migrate`).
- Cache local (localStorage) : collection, souhaits, et infos de carte (versions/rareté/prix,
  clé `collection_pokemon_meta`, rafraîchies toutes les 24 h).
- Données des cartes et prix : **TCGdex**. Rien n'est auto-hébergé (la liste légère ne contient
  que id / numéro / nom / image — versions, rareté et prix nécessitent une requête par carte).
- ⚠️ En CSS, garder le bloc `@media` **en fin de feuille de style** (sinon il est écrasé).

## 🔁 Pour publier une mise à jour
**Déploiement automatique depuis fin juillet 2026** : chaque `git push origin main` déclenche
un déploiement Firebase Hosting tout seul via GitHub Actions (`.github/workflows/deploy.yml`).
Plus besoin de Cloud Shell ni d'upload manuel.

1. **Incrémenter `VERSION`** en haut de `sw.js` (`"v4"` → `"v5"`…) si `index.html` ou `sw.js` a changé.
   Sans ça, l'ancienne version reste en cache chez les utilisateurs.
2. `git add`, `git commit`, `git push origin main`
3. Suivre le déploiement (1-2 min) sur https://github.com/KKiuyte/ma-collection-pokemon/actions
4. Vérifier en **navigation privée** sur https://ma-collection-pokemon.web.app (le cache navigateur est tenace)

Dépannage : le déploiement s'appuie sur un compte de service Google Cloud (`github-deploy@ma-collection-pokemon.iam.gserviceaccount.com`,
rôle `roles/firebasehosting.admin`) dont la clé est stockée dans le secret GitHub `FIREBASE_SERVICE_ACCOUNT`.
Si le déploiement échoue côté authentification, il faut régénérer une clé (`gcloud iam service-accounts keys create`)
et la ranger avec `gh secret set FIREBASE_SERVICE_ACCOUNT --repo KKiuyte/ma-collection-pokemon`.

**Méthode manuelle (dépannage uniquement, si GitHub Actions est indisponible) :**
Cloud Shell → `cd ~/collection` → uploader les fichiers modifiés (menu ⋮ → Upload) → `mv -f ~/index.html ~/sw.js public/`
→ `firebase deploy --only hosting`. 💡 Piège connu : si le navigateur a renommé le téléchargement
(`index(1).html`…), le `mv` déplace un ancien fichier — vérifier avec `ls -lt ~/*.html` avant.

## 🗂️ Devenu inutile
- Le système de **code de synchro Cloudflare** (Worker + KV) — remplacé par Firebase.
  ⚠️ **Ne pas supprimer le Worker** : il resservira si on fait la reconnaissance par photo.
