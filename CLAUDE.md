# Ma Collection Pokémon — mémoire du projet

> Ce fichier est lu automatiquement par Claude Code. Il contient tout ce qu'il faut
> savoir pour reprendre le projet sans rien redécouvrir. **À jour au moment du passage
> depuis le chat vers Claude Code.**

## Qui, quoi

Application web **personnelle** de suivi d'une collection de cartes Pokémon, faite pour
et avec **Ariel** (francophone, débutant en code, sur Android). L'interface, les textes
et les échanges sont **en français**.

Attentes de travail (important) : avancer **une fonctionnalité à la fois**, tester avant
de livrer, être **honnête sur les limites** plutôt que sur-vendre, expliquer les étapes
clairement. Pas de jargon inutile. Quand une approche a un défaut, le dire.

## Nature technique — à lire avant de toucher au code

- L'application est **un seul fichier HTML autonome** : `public/index.html`. Tout y est
  (HTML, CSS dans un `<style>`, JS dans un `<script type="module">`). **Ce n'est pas**
  une application React/Vue/bundlée. Il n'y a **pas** d'étape de build, pas de `npm run`,
  pas de dépendances à installer pour l'appli elle-même.
- On édite donc **directement `public/index.html`**. (Historiquement il existait un
  doublon `ma-collection-pokemon.html` recopié vers `index.html` ; ce doublon est
  **supprimé** — il n'y a plus qu'un seul fichier source.)
- Les bibliothèques externes sont chargées par CDN à l'exécution : Firebase (gstatic
  v10.12.0) dans l'appli, et Tesseract.js (jsdelivr) dans la page de scan.

## Structure du dépôt

```
public/                 ← ce qui est déployé (le site)
  index.html            ← L'APPLICATION (fichier unique, source de vérité)
  manifest.json         ← PWA
  sw.js                 ← service worker (cache + hors-ligne)
  icon-192/512/maskable ← icônes PWA
  test-scan.html        ← banc d'essai de la reconnaissance par photo (autonome)
tools/
  build_hashes.py       ← génère les empreintes visuelles (à lancer en local, Python 3)
archive/                ← obsolète, conservé volontairement (voir plus bas)
roadmap.md              ← feuille de route détaillée + notes
```

**Catalogue d'empreintes** (`public/catalogue-fr.json`, ~13 Mo) : le fichier lu par la page
de reconnaissance (`test-scan.html`). Il est **versionné dans Git** (donc déployé
automatiquement) — indispensable depuis le passage au déploiement auto GitHub, qui ne publie
que ce qui est dans Git. Il est **régénérable localement** avec `tools/build_hashes.py`
(Python 3 + `pillow numpy requests`). Les fichiers intermédiaires par série
`public/hashes-*.json` restent git-ignorés (seul le catalogue fusionné compte).

**Régénérer / améliorer le catalogue** (ex. ajouter des séries ou, plus tard, des langues
étrangères) :
```
python tools/build_hashes.py --all         # régénère toutes les séries dans ~/hashes
python tools/build_hashes.py --merge        # fusionne en ~/hashes/catalogue-fr.json
cp ~/hashes/catalogue-fr.json public/       # (Windows : copier vers public\)
git add public/catalogue-fr.json && git commit && git push   # déploie
```

## Infrastructure en ligne

- **Hébergement** : Firebase Hosting → https://ma-collection-pokemon.web.app/
- **Projet Firebase** : `ma-collection-pokemon`
  - apiKey `AIzaSyCiGgrj28Jrqn8jEGM9pWFsVhnfs-VKyiU` (clé publique, non secrète)
  - messagingSenderId `1058168439830`
  - appId `1:1058168439830:web:9b3c787f9286e888112137`
- **Auth** : Firebase Authentication — Google + email/mot de passe (activés).
- **Base** : Firestore, document `collections/{uid}` (chaque personne n'accède qu'à la
  sienne, via les règles de sécurité). Champs `cards` et `wishlist`.
- **Partage — étapes 1a, 1b-1 et 1b-2 faites** :
  - **Pseudo (1a)** : `users/{uid}` (`{pseudo, pseudoLower, email}`, profil public lisible par
    tout membre connecté) + registre `pseudos/{minuscule} = {uid}` (unicité insensible à la casse
    + recherche pseudo→compte). Réservation atomique par `runTransaction`.
  - **Octroi côté propriétaire (1b-1)** : copies publiées par périmètre `shared_wishlist/{uid}` et
    `shared_trades/{uid}` = `{ owner, ownerPseudo, viewers:[uid…], data, updatedAt }`. Lisibles par
    le propriétaire ou une personne dans `viewers`. `SHARE_SCOPES` liste les périmètres (extensible
    à la collection complète). Autoriser/révoquer par pseudo dans « Mon compte » ; `saveCloud()`
    republie les copies (`refreshPublishedShares`) pour les garder à jour.
  - **Lecture seule côté destinataire (1b-2)** : onglet « Partagé » (`renderShared()`), requête
    `query(collection(db, s.col), where("viewers","array-contains", uid))` sur chaque périmètre de
    `SHARE_SCOPES` (`loadShared()`). Groupé par pseudo du propriétaire ; réutilise `cardButton`
    (souhaits, en grille) et le style `trade-row` (échanges). Cliquer sur une carte ouvre la fiche
    habituelle — elle modifie TA collection à toi, jamais celle du propriétaire. Chargé une seule
    fois par connexion (`sharedLoaded`), bouton « Actualiser » pour reforcer. Reste **étape 2**
    (demandes d'accès, ID2 demande / ID1 approuve) — voir `roadmap.md`.
  - **Règles de sécurité versionnées dans `firestore.rules`** — ⚠️ NON déployées par le workflow
    (hosting seulement) : à (re)publier à la main dans la console Firebase (Firestore → Règles) ou
    `firebase deploy --only firestore:rules` **à chaque modification de ce fichier**.
- **Données des cartes et prix** : API communautaire **TCGdex** (`https://api.tcgdex.net/v2/fr`).
  Rien n'est auto-hébergé.

## Modèle de données

```js
// owned : cartes possédées, PAR VERSION, chaque exemplaire ayant son propre état/langue
owned[idCarte] = { v: { "Normale":     [ {cond, lang}, {cond, lang} ],
                        "Reverse Holo": [ {cond, lang} ], ... } }
// wishlist : liste de souhaits, par carte
wishlist[idCarte] = true
```

- Versions possibles (libellés FR) : `Normale`, `Reverse Holo`, `Holo`, `1re édition`, `Promo`.
- `CONDITIONS = [Neuve, Excellent, Très bon, Bon, Moyen, Mauvais]`
- `LANGUAGES = [Français, Anglais, Japonais, Allemand, Italien, Espagnol, Chinois, Autre]`
- Chaque **exemplaire** d'une version est un objet indépendant `{cond, lang}` dans un tableau —
  deux exemplaires « Normale » de la même carte peuvent avoir un état et une langue différents.
  La quantité affichée est simplement `tableau.length`.
- La fonction **`migrate()`** convertit automatiquement les anciens formats de données
  (nombre seul, `{qty,cond,lang}` groupé, ou déjà en tableau) vers ce format par exemplaires.
  Elle est appliquée au chargement local ET aux données venues de Firestore. **Ne pas la
  casser** : d'anciennes collections en dépendent.
- Une carte est « possédée » si son entrée existe avec ≥ 1 version (≥ 1 exemplaire). Quand on
  retire le dernier exemplaire d'une version, la version disparaît ; quand il ne reste plus
  aucune version, on **supprime** l'entrée `owned[id]`.

## TCGdex — points clés

- La **liste légère** des cartes (`/cards`, `/sets/{id}`) ne contient que
  `id / localId / name / image`. **Ni versions, ni rareté, ni prix.**
- Versions, rareté et **prix** nécessitent une requête **par carte** : `/cards/{id}`.
  On met donc ces infos en cache local (clé `collection_pokemon_meta`, TTL 24 h).
- **Prix** (champ `pricing` de `/cards/{id}`) : Cardmarket en € (priorité, marché
  européen) et TCGplayer en $ (repli). Règles fines dans `priceForVariant()` :
  - carte à version unique → le prix « de base » Cardmarket lui revient ;
  - Reverse Holo d'une carte **sans** Holo distincte → prix `-holo` Cardmarket (€) ;
  - Reverse Holo d'une carte **avec** Holo distincte → repli TCGplayer ($), car
    Cardmarket ne distingue pas les deux. Limite des données, pas un bug.
  - Surveiller le futur champ `variants_detailed` de TCGdex : il donnera les prix par
    version et réglera ce dernier cas.
- Regroupement des séries par **bloc/génération** via `/series` et `/series/{id}`.

## ⚠️ Pièges connus (déjà rencontrés — ne pas refaire)

1. **CSS : le bloc `@media` doit être en FIN de feuille de style.** À priorité égale,
   la dernière règle gagne. Une media-query placée avant la règle de base `.grid` était
   silencieusement écrasée → le responsive ne s'appliquait pas. Toute règle responsive
   va après les règles de base.
2. **PWA : incrémenter `VERSION` dans `public/sw.js` à CHAQUE déploiement** (`"v3"` → `"v4"`…).
   Sinon l'ancienne version reste en cache chez les utilisateurs. Un bandeau
   « Nouvelle version disponible » gère la bascule côté client.
3. **Service worker et navigation** : ne PAS renvoyer `index.html` pour toute navigation
   (ça masquait `test-scan.html`). Le repli sur l'accueil ne doit se faire que **hors-ligne**.
4. **Cache navigateur tenace** : après un déploiement, tester en **navigation privée**
   pour voir la vraie version.
5. **Empreintes visuelles : le calcul Python (`tools/build_hashes.py`) et le calcul
   JavaScript (`test-scan.html`) doivent être identiques OCTET POUR OCTET.** Ils utilisent
   un moyennage par blocs sans interpolation (`box_resize`) et des arrondis harmonisés
   (`round`, pas de troncature). Toute modification d'un côté doit être répercutée et
   revérifiée de l'autre.

## Déploiement

**Automatique depuis fin juillet 2026** : chaque `git push origin main` déclenche un
déploiement Firebase Hosting via GitHub Actions (`.github/workflows/deploy.yml`). Suivre
la progression sur https://github.com/KKiuyte/ma-collection-pokemon/actions.

1. Incrémenter `VERSION` dans `public/sw.js` si `index.html` ou `sw.js` a changé.
2. `git add`, `git commit`, `git push origin main`.
3. Vérifier en navigation privée sur https://ma-collection-pokemon.web.app (cache tenace).

Le workflow s'authentifie via un compte de service GCP (`github-deploy@ma-collection-pokemon.iam.gserviceaccount.com`,
rôle `roles/firebasehosting.admin`), dont la clé est dans le secret GitHub `FIREBASE_SERVICE_ACCOUNT`.
Si l'authentification échoue, régénérer une clé (`gcloud iam service-accounts keys create`) et la
poser avec `gh secret set FIREBASE_SERVICE_ACCOUNT --repo KKiuyte/ma-collection-pokemon`.

**Dépannage manuel** (si GitHub Actions est indisponible) : Cloud Shell → `cd ~/collection` →
uploader les fichiers modifiés (menu ⋮ → Upload) → `mv -f ~/index.html ~/sw.js public/` →
`firebase deploy --only hosting`. Piège connu : le navigateur renomme les téléchargements
(`index(1).html`), vérifier `ls -lt ~/*.html` avant tout `mv`.

## État d'avancement

Voir `roadmap.md` pour le détail. En résumé :

**Fait** : navigation par série/bloc, recherche (nom, numéro « 074/159 », globale),
filtres, tri, rareté, **versions de carte** avec **exemplaires individuels** (état/langue
propres à chaque copie), liste de souhaits, **prix par version**, **valeur totale** de la
collection (cache 24 h), compte + synchro Firebase temps réel, **PWA** complète (installable,
hors-ligne, bouton d'installation, mise à jour), **mode sombre**, bouton retour en haut,
**statistiques** (progression par bloc, répartition par rareté — les ajouts récents restent
à faire), **liste d'échange** (doubles regroupés par version), **déploiement continu**
(GitHub Actions).

**En cours — reconnaissance de carte par photo** (`public/test-scan.html`) :
- Approche **gratuite, locale** : empreinte visuelle (grille 12×12, chromaticité
  r/(r+g+b),g/(r+g+b) insensible à l'éclairage) + **lecture du numéro par OCR** (Tesseract.js).
- Idée maîtresse : le **numéro imprimé** « 074/159 » restreint le champ (le total /159
  cible la série par correspondance exacte du `cardCount.official`), l'**empreinte tranche**.
- Résultats mesurés sur une série : ~67 % en 1er (communes 88 %, holos 67 %, full art 43 %).
  La marge distingue bien vrai/faux (~0.012 vs ~0.002) → un **seuil de confiance ~0.005**
  permet de dire « je ne reconnais pas » plutôt que de proposer faux.
- OCR : exiger le motif complet `nombre/nombre`, modes PSM ['6','11','7','4'] SANS arrêt
  anticipé, SANS liste blanche de caractères (sinon les lettres deviennent des chiffres
  parasites), langue 'fra', corrections de confusions (O→0, S→5, B→8, Z→2).
- **Retour d'Ariel après test réel** : l'OCR lit mal des numéros pourtant lisibles à l'œil nu.
  Le mode « lecture complète ou rien » gaspillait toute information dès qu'un seul chiffre
  était mal lu, forçant un repli sur l'image seule *sur tout le catalogue*.
- **Ajouté (non testé en conditions réelles) — lecture partielle par confiance** : si la
  lecture complète échoue, on exploite la confiance par caractère de Tesseract
  (`data.blocks[].paragraphs[].lines[].words[].symbols[].confidence`, seuil `CONF_THRESHOLD = 60`)
  pour construire un motif à trous (ex. `0?4/159`). Les totaux connus (petit ensemble via
  `setOfficial`) et les numéros de série sont filtrés par ce motif AVANT l'empreinte visuelle,
  qui ne tranche plus que parmi les candidats restants au lieu de tout le catalogue. Logique
  testée unitairement (fonctions pures) mais **jamais essayée avec de vraies photos** — la
  structure `data.blocks`/`symbols` de Tesseract.js n'a pas pu être vérifiée en conditions
  réelles depuis cet environnement (pas d'appareil photo). Le diagnostic affiché à l'écran
  (`ocrInfo`) indique si le détail par caractère était disponible ou non.
- **Prochaine étape** : Ariel teste avec de vraies cartes sur son téléphone (page déployée),
  vérifie que la lecture partielle se déclenche bien, puis campagne de test ~30 cartes contre
  le catalogue complet pour décider de l'intégration dans l'appli. Services payants étudiés
  puis écartés (Ximilar 59 €/mois obligatoire ; CardSight à revérifier).

**Décidé, non retenu** : publication sur les stores (obstacle des 12 testeurs 14 j pour
Google Play ; App Store très difficile + connexion Google KO en webview ; risque de
propriété intellectuelle Nintendo).

## archive/ — à ne PAS supprimer

- `worker-sync.js` : ancien Worker Cloudflare (synchro par code, remplacé par Firebase).
  **Conservé** car il resservira d'intermédiaire si on branche un service de
  reconnaissance payant (la clé d'API ne doit jamais être dans la page web).
- `ma-collection-pokemon.jsx` : tout premier prototype React (Claude Design), jamais
  utilisé. L'appli n'a jamais été en React.

## Conventions de code

- Français pour l'UI, les commentaires et les messages.
- Pas de framework, pas de build. Rester en HTML/CSS/JS simple et lisible.
- CSS : palette beige/orange (variables CSS en tête de `<style>`), formatage sobre.
- Tester la logique avant de livrer (le projet a été construit en validant chaque étape).

## Interface — points de structure

- **Navigation par onglets** : une seule variable `view` (`"set"` | `"collection"` | `"stats"`
  | `"trade"`) pilote la vue affichée, et `render()` synchronise la classe `.on` des onglets
  `#viewTabs`. Il n'y a plus de booléens séparés par vue (`collectionView`/`statsView`/…) :
  ne pas les réintroduire, un seul état évite les combinaisons impossibles.
  Les onglets restent sur **une ligne** avec défilement horizontal (`overflow-x:auto`,
  `white-space:nowrap`) — un onglet supplémentaire défilera au lieu de casser la mise en page.
- **Icônes** : petites SVG inline, construites par `svgIco(paths, cls)` à partir du
  dictionnaire `ICONS`. Trait fin, `stroke="currentColor"` → la couleur est héritée du parent,
  donc compatible clair/sombre sans règle supplémentaire. Plus d'emoji dans les commandes
  (ils rendaient différemment selon l'OS) ; ♡/♥ sont conservés car porteurs de sens et colorés.
- **États vides / erreurs** : passer par `emptyMsg(icon, html)` pour garder icône + texte
  cohérents. La hauteur minimale qui les centre verticalement est **réservée au desktop**
  (`@media (min-width:821px)`) : sur mobile le panneau empilé occupe déjà le haut de l'écran,
  et centrer dans 360 px de plus poussait le texte sous la ligne de flottaison.
- **Statistiques** : les noms de blocs passent à la ligne (pas de troncature `…`). Sous 560 px,
  `grid-template-areas` fait passer la barre de progression **sous** le nom, qui récupère toute
  la largeur. Toute modification de `.stat-row` / `.stat-block-summary` doit garder les deux
  jeux d'aires cohérents (desktop en ligne, mobile empilé).
- **Commandes contextuelles par onglet** : `syncControls()` (appelée dans `render()`) n'affiche
  que les commandes qui **agissent réellement** sur l'onglet courant — jamais de commande visible
  mais sans effet. Deux familles distinctes dans la colonne de gauche : **Navigation** (recherche toujours
  présente ; le bloc sélecteur de série + progression `#serieField` n'apparaît que sur `set`,
  car il montrerait sinon la progression d'une seule série sans rapport avec la vue d'ensemble ;
  l'indice `#navHint` s'affiche hors `set`) et **Filtres de la vue** (`#filterSection` : rareté + tri). Règles : les puces
  Possédées/Manquantes n'existent que sur `set` ; `collection` ne garde que Toutes + Souhaits ;
  la rareté n'agit que sur `set` (calcul propre à la série) ; le tri sur `set` + `collection` ;
  `stats`/`trade` masquent puces + rareté + tri (ne restent que Navigation + Valeur estimée).
  Si le `filter` courant n'est plus disponible dans la vue, `syncControls()` le ramène à `"all"`.
  ⚠️ Piège : les conteneurs masqués via l'attribut `hidden` qui ont un `display` explicite
  (`.filters`, `.ctrl-section`, `.ctrl-hint`) ont besoin d'une règle `[hidden]{display:none}`,
  sinon le `display` l'emporte et l'élément reste visible.
