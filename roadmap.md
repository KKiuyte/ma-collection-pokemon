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
- [x] Quantité, état et langue gérés **par version**
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
- [ ] Filtre par rareté aussi dans la **recherche globale** et la vue collection
- [ ] **Liste d'échange** : regrouper automatiquement les doubles (quantité ≥ 2)
- [ ] **Partage en lecture seule** d'une collection ou d'une liste de souhaits (facile avec Firebase)

## 💰 Priorité 3 — Prix, suite
- [ ] Suivre l'**évolution de la valeur** dans le temps (relevé mensuel dans Firestore)
- [ ] Surveiller le champ `variants_detailed` annoncé par TCGdex : il apportera les identifiants
      Cardmarket/TCGplayer **par version**, ce qui réglera le cas des Reverse Holo affichées en dollars

## 🎨 Priorité 4 — Finitions
- [ ] **Mode sombre**
- [ ] Statistiques (progression par bloc, ajouts récents, répartition par rareté)
- [ ] Distinguer plusieurs exemplaires d'une **même version** (états différents par copie)

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
  - `cards` : `{ idCarte: { v: { "Normale": {qty, cond, lang}, "Reverse Holo": {...} } } }`
  - `wishlist` : `{ idCarte: true }`
- Les anciens formats sont **convertis automatiquement** au chargement (fonction `migrate`).
- Cache local (localStorage) : collection, souhaits, et infos de carte (versions/rareté/prix,
  clé `collection_pokemon_meta`, rafraîchies toutes les 24 h).
- Données des cartes et prix : **TCGdex**. Rien n'est auto-hébergé (la liste légère ne contient
  que id / numéro / nom / image — versions, rareté et prix nécessitent une requête par carte).
- ⚠️ En CSS, garder le bloc `@media` **en fin de feuille de style** (sinon il est écrasé).

## 🔁 Pour publier une mise à jour
1. **Incrémenter `VERSION`** en haut de `sw.js` (`"v2"` → `"v3"`). Sans ça, l'ancienne version
   reste en cache chez les utilisateurs.
2. Ouvrir **Cloud Shell** depuis la console Firebase, puis `cd collection`
3. Uploader les fichiers modifiés (menu ⋮ → Upload), puis
   `mv -f ~/index.html ~/manifest.json ~/sw.js ~/icon-*.png public/`
4. Vérifier : `ls public/` (6 fichiers) et `grep -c "repeat(3,1fr)" public/index.html` (doit afficher `1`)
5. `firebase deploy --only hosting`

💡 Piège connu : si le navigateur a renommé le téléchargement (`index(1).html`…), le `mv` déplace
un ancien fichier. Vérifier avec `ls -lt ~/*.html`.

## 🗂️ Devenu inutile
- Le système de **code de synchro Cloudflare** (Worker + KV) — remplacé par Firebase.
  ⚠️ **Ne pas supprimer le Worker** : il resservira si on fait la reconnaissance par photo.
