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
  scan.html             ← PAGE PUBLIQUE de scan (2026-08-06), accessible via le bouton caméra
                           de l'en-tête d'index.html ; identifie une carte puis l'ajoute
                           directement à la collection (Firebase inclus, cf. section dédiée)
  test-scan.html        ← banc d'essai de la reconnaissance par photo (autonome, gardé pour
                           les campagnes de test — pas de lien depuis l'appli)
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
- **Partage — étapes 1a, 1b-1, 1b-2, 2 et 3 faites** :
  - **Pseudo (1a)** : `users/{uid}` (`{pseudo, pseudoLower, email}`, profil public lisible par
    tout membre connecté) + registre `pseudos/{minuscule} = {uid}` (unicité insensible à la casse
    + recherche pseudo→compte). Réservation atomique par `runTransaction`. Reste géré dans
    « Mon compte » : affiché en lecture seule une fois défini, bouton **Modifier** → confirmation
    (`confirm()`) avant d'écraser un pseudo existant (`pseudoEditing`) — le tout premier réglage
    reste direct. `loadUserProfile()` retente une fois en cas d'échec réseau et distingue
    « profil pas encore vérifié » (`profileLoadFailed`) de « pas de pseudo », pour ne jamais
    proposer d'en recréer un par erreur sur un appareil neuf.
  - **Toute la gestion des accès (octroi, comptes autorisés, demandes) vit dans l'onglet
    « Partagé », pas dans « Mon compte »** — seul le pseudo reste dans « Mon compte ». L'onglet
    « Partagé » a 3 sous-onglets (`sharedSubTab`, variable locale à la vue, non persistée) :
    **Partages** (`renderSharedFeedPanel`, ex-contenu unique de `renderShared`), **Comptes
    partagés** (`renderShareGrantsPanel`, ex-octroi) et **Demandes d'accès**
    (`renderShareRequestsPanel`, reçues + envoyer une nouvelle demande). `renderShared()` est la
    coquille commune : sous-onglets + `#shareStatus` (retour des actions, équivalent de
    `#authStatus` mais pour cette vue) + délégation au panneau actif.
  - **Octroi côté propriétaire (1b-1)** : copies publiées par périmètre `shared_wishlist/{uid}` et
    `shared_trades/{uid}` = `{ owner, ownerPseudo, viewers:[uid…], data, updatedAt }`. Lisibles par
    le propriétaire ou une personne dans `viewers`. `SHARE_SCOPES` liste les périmètres (extensible
    à la collection complète). Autoriser/révoquer par pseudo dans l'onglet Partagé → Comptes
    partagés ; `saveCloud()` republie les copies (`refreshPublishedShares`) pour les garder à jour.
  - **Lecture seule côté destinataire (1b-2)** : sous-onglet Partages, requête
    `query(collection(db, s.col), where("viewers","array-contains", uid))` sur chaque périmètre de
    `SHARE_SCOPES` (`loadShared()`). Groupé par pseudo du propriétaire ; réutilise `cardButton`
    (souhaits, en grille) et le style `trade-row` (échanges, via le helper `tradeRow()`). Cliquer
    sur une carte ouvre la fiche habituelle — elle modifie TA collection à toi, jamais celle du
    propriétaire. Chargé une seule fois par connexion (`sharedLoaded`), bouton « Actualiser ».
  - **Demandes d'accès (2)** : collection `share_requests/{proprio}_{demandeur}_{périmètre}`
    (id déterministe — redemander après refus republie le même document). Le demandeur crée sa
    demande (`sendAccessRequest`) depuis le sous-onglet Demandes d'accès ; le propriétaire y voit
    ses demandes reçues (`loadShareRequests`) avec Accepter (réutilise `grantAccess`, puis supprime
    la demande) ou Refuser (supprime). Le demandeur voit ses demandes en attente (chips annulables).
  - **Suggestions d'échange automatiques (3)** : dans le sous-onglet Partages, `tradeSuggestions()`
    croise `sharedList` (déjà chargé) avec ta wishlist locale et `tradeEntries()` — aucune donnée
    supplémentaire stockée. Par personne : ses échanges partagés présents dans ta wishlist
    (« tu pourrais demander ») et tes doubles présents dans sa wishlist partagée (« tu pourrais
    proposer »).
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
  - **`variants_detailed` exploité (2026-08-05)** — `detailedCardmarketPrice()`, essayé en
    priorité avant le repli ci-dessous. Vérifié sur plusieurs cartes réelles de l'API (pas
    seulement lu dans la doc) : le tableau `{type, size, variantId, pricing}` de `/cards/{id}`
    donne un prix Cardmarket **propre à chaque produit distinct** — utile quand une carte a
    une version Holo vendue comme un produit à part (idProduct différent de Normale/Reverse).
    Piège découvert en creusant : le `type` d'une entrée ne dit pas quel champ lire à
    l'intérieur — une entrée `"reverse"` reste **toujours** le parallèle brillant du produit
    auquel elle appartient (ce produit peut être celui de Normale OU celui de Holo selon la
    carte), donc ses propres champs `avg`/`trend` décrivent l'AUTRE version de ce même
    produit, jamais Reverse Holo elle-même — d'où l'usage systématique du suffixe `-holo`
    pour elle, alors que `normal` et `holo` sont chacun la version de base de leur produit
    (partagé ou dédié) et utilisent directement leurs propres champs. Confirmé par comparaison
    directe : sur `swsh4-25`, Holo a son propre `idProduct` (avg 8.61 €) alors que Normale et
    Reverse partagent le même produit (avg 2.49 € / avg-holo 3.53 €) ; sur `swsh3-25`
    (Heatran, sans version Normale), Holo et Reverse partagent un seul produit où c'est cette
    fois `avg` qui vaut pour Holo (0.31 €) et `avg-holo` pour Reverse (0.77 €) — la règle
    « `reverse` = toujours `-holo` » tient dans les deux cas, contrairement à une règle qui
    se serait basée sur la présence d'une version Normale.
  - Cache : `variantsDetailedByCard[cardId]`, persisté dans `collection_pokemon_meta` (clé
    courte `d`), même cycle de vie que `variantCache`/`pricingByCard` (TTL 24 h).
  - Si l'entrée correspondante est absente ou sans prix (ex. `variantId:"generated"` sans
    `pricing` du tout, observé sur certaines cartes), repli intact sur l'ancienne logique
    (`-holo` du prix de base, ou TCGplayer) — donc pour une carte avec Holo distincte, le
    cas Reverse Holo qui retombait avant sur TCGplayer $ (« Cardmarket ne distingue pas les
    deux ») ne devrait plus quasiment jamais s'y retrouver, mais le repli reste utile en
    sécurité pour les entrées incomplètes.
  - **Bug corrigé au passage** (indépendant de `variants_detailed`) : les clés TCGplayer
    utilisées pour Holo/Reverse Holo étaient `"holo"`/`"reverse"`, alors que l'API renvoie
    en réalité `"holofoil"`/`"reverse-holofoil"` — ces deux variantes retombaient donc
    silencieusement sur le prix TCGplayer de la version **Normale** au lieu du bon
    sous-objet, depuis l'écriture initiale de `priceForVariant()`. Corrigé.
  - ⚠️ **Décalage observé entre le dépôt source et l'API publique** : pour une carte toute
    récente (`me04-007`, série sortie 22/05/2026), le dépôt GitHub public
    (`tcgdex/cards-database`, `data/{Série}/{Set}/{numéro}.ts`) listait déjà la version
    Reverse Holo, mais `/cards/{id}` (et `variants_detailed`) ne la renvoyait pas encore —
    `variants.reverse` restait à `false` pour toute la série (`cardCount.reverse: 0`).
    Décidé de ne rien coder côté appli (2026-08-03) : c'est un délai de publication TCGdex,
    pas un manque permanent ni un bug d'ici — se corrige tout seul quand ils republient
    l'API. Se reproduira probablement à chaque sortie de série récente ; si ça devient
    gênant, l'idée mise de côté était un bouton « ajouter quand même une autre version »
    sur la fiche carte (contournerait `variantCache` pour n'importe quelle version).
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
4. **Cache navigateur tenace (corrigé)** : le service worker mettait bien à jour son
   `VERSION`, mais son étape d'installation utilisait `caches.addAll()` — un simple `fetch()`
   qui pouvait renvoyer la page déjà présente dans le **cache HTTP du navigateur**, recachant
   ainsi l'ANCIENNE page sous le nouveau numéro de version. D'où le besoin de tester en
   navigation privée (aucun cache HTTP à contourner). Corrigé par deux changements : (1)
   `sw.js` fetch chaque fichier avec `{ cache: "reload" }` pour forcer le réseau ; (2)
   `firebase.json` envoie `Cache-Control: no-cache` sur les `*.html` et `sw.js` (le navigateur
   revalide toujours avant d'utiliser une copie en cache). La navigation privée ne devrait
   plus être nécessaire pour voir une mise à jour — si le problème revient, vérifier que ces
   deux points n'ont pas été défaits.
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

**Scan de carte par photo — intégré dans l'appli mais pas encore testé en conditions réelles**
(voir tout en bas de cette section pour l'état actuel : `public/scan.html`) :
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
- **Campagne de test réelle (2026-08-05, 25 cartes, sur téléphone)** :
  - 1re position : 18/25 (72 %) — top 3 : 22/25 (88 %)
  - Marge moyenne quand c'est juste : 0.0078 — quand c'est faux : 0.0013 (bonne séparation,
    confirme le seuil ~0.005 envisagé)
  - Numéro lu et exploité (lecture complète ou partielle) : 19/25 (76 %)
  - Par type : communes/peu communes 8/11 (73 %), holos/reverse 6/6 (100 %,
    net progrès vs 67 % du 1er test — probablement grâce à la lecture partielle par confiance),
    full art/SIR 4/8 (50 %, toujours le point faible malgré un léger mieux vs 43 %)
  - Le top 3 (88 %) est nettement plus fiable que le 1er choix seul (72 %) → piste à retenir
    si on intègre un jour : proposer 3 candidates à confirmer plutôt qu'une seule réponse.
  - **Décision d'intégration pas encore prise** — résultats notés, à rediscuter plus tard.
- **Troisième couche ajoutée (2026-08-05, non testée en conditions réelles) — OCR du nom** :
  en plus du numéro (bas de carte) et de l'empreinte visuelle, `test-scan.html` lit maintenant
  aussi le **nom en haut de la carte** (`readName()`/`extractName()`), pensé pour combler le
  point faible des full art (empreinte peu fiable sur fond très chargé, mais le nom reste
  lisible). Bande de crop `cropRectName()` : haut de carte, largeur limitée à 68 % pour éviter
  le bloc PV/type à droite ; mots à une lettre et « PV »/« HP » filtrés (`NAME_NOISE`) car ils
  débordent parfois sur la bande. Comparaison floue par distance d'édition normalisée
  (`nameSimilarity()`, accents/casse ignorés) contre `c.t` du catalogue (déjà présent, aucune
  régénération du catalogue nécessaire). Toggle Lire/Ne pas lire dans l'UI de test
  (`nameZoneOn`, on par défaut).
  - **Algorithme en cascade** (numéro → nom → image), chaque étage **réduisant** l'ensemble de
    candidats plutôt que de trancher seul, pour qu'une erreur d'un seul OCR n'élimine pas la
    bonne carte : `narrowByName(pool, nameGuess)` ne garde que les candidats à ≤ 0.15 du
    meilleur score de similarité (`NAME_SIM_THRESHOLD = 0.45` sous lequel on ne fait pas
    confiance au nom lu). Appliqué (a) pour départager quand le numéro (lecture complète ou
    motif partiel) laisse plusieurs candidats, et (b) en repli seul quand aucun numéro n'est
    exploitable — nouveau mode « nom » symétrique du mode « motif partiel ».
  - Journal de test étendu : `byName` suit si le nom a effectivement été exploité, comme
    `byNum` pour le numéro ; récapitulatif affiche désormais « Nom lu et exploité : X/Y ».
    Badge visuel bleu (`.badge.nam`) distinct du badge vert du numéro.
  - ⚠️ **Non testé avec de vraies photos** (pas d'appareil photo depuis cet environnement) —
    seulement vérifié par relecture + `node --check` sur le script extrait, et par un test
    unitaire de `nameSimilarity()`/`narrowByName()` avec des chaînes fabriquées (confirmé :
    une lecture bruitée « oracaufeu ex » distingue toujours correctement « Dracaufeu ex » de
    « Dracaufeu » et « Dracaufeu V » dans un mini-catalogue). La bande de crop (haut de carte,
    marge droite pour éviter les PV) est une **première estimation géométrique**, pas calibrée
    sur de vraies cartes — à ajuster selon les résultats du prochain test réel.
  - Double le nombre d'appels OCR par scan (numéro + nom) : la reconnaissance sera plus lente.
    Pas un problème pour la page de test, à surveiller si intégré dans l'appli.
- **Intégré dans l'appli (2026-08-06) — `public/scan.html`, page publique** : bouton caméra
  dans l'en-tête d'`index.html` (`#scanBtn`, à côté du thème/compte) → `scan.html`. Reprend le
  pipeline validé ci-dessus (empreinte + numéro + nom, cascade numéro→nom→image) mais réécrit
  pour un usage réel, pas un banc d'essai :
  - **Plus de choix manuel lire/pas lire** : le numéro est tenté bas-gauche puis bas-droite
    automatiquement (`readNumberBothZones()`, ne tente la 2e bande que si la 1re n'a rien donné
    — évite de systématiquement doubler le temps de lecture), le nom est toujours lu.
  - **Résultat affiché** : 1 seule carte en grand si le numéro/nom-narrowed et l'image seule
    tombent sur la même carte (`agree`, avec un lien « pas la bonne carte » qui révèle 2
    autres possibilités) ; jusqu'à 3 cartes à choisir sinon. Aucun signal exploitable → 3
    candidates par l'image seule (jamais de résultat unique sur l'image seule : on demande
    toujours confirmation dans ce cas, contrairement à `test-scan.html` qui l'affichait via un
    seuil de marge).
  - **Ajout direct à la collection** : sélectionner une carte ouvre un petit formulaire
    version/état/langue (identique à celui de la fiche carte dans `index.html`, versions
    récupérées via `/cards/{id}`), puis écrit dans les **mêmes données** que l'appli
    (`localStorage` clés `collection_pokemon_v1`/`collection_pokemon_wishlist` + Firestore
    `collections/{uid}` si connecté). Bouton « Scanner une autre carte » pour enchaîner.
  - ⚠️ **Piège de cohérence identifié et traité** : `onLogin()` dans `index.html` ne redemande
    confirmation avant de remplacer la collection locale par celle du cloud que sur une
    connexion *interactive* — une session déjà ouverte (cas courant) remplace **sans prévenir**
    dès que les deux diffèrent. Une page de scan qui écrirait juste dans `localStorage` sans
    toucher Firestore risquerait donc de voir la carte fraîchement ajoutée silencieusement
    écrasée à la prochaine ouverture de l'appli. `scan.html` importe donc son propre Firebase
    (même config, non secrète), récupère la version cloud la plus fraîche **avant** d'ajouter
    quoi que ce soit (`onAuthStateChanged` → `getDoc` → fusion), et le bouton « Ajouter » reste
    désactivé (`cloudReady`) tant que cette fusion n'est pas terminée — pour ne jamais pousser
    un `owned` obsolète par-dessus un changement fait depuis un autre appareil.
  - `test-scan.html` **conservé tel quel**, pas de lien depuis l'appli : reste le banc d'essai
    pour continuer à mesurer la précision (dernier chiffre connu : 72 % en 1er / 88 % en top 3,
    campagne du 2026-08-05, avant l'ajout de la couche nom ci-dessus). Les deux fichiers
    dupliquent le même cœur de reconnaissance (empreinte/OCR) — **toute correction ou réglage
    faite dans l'un doit être répercutée dans l'autre**, même piège que `build_hashes.py`.
  - `scan.html` ajouté au précache du service worker (`APP_FILES` dans `sw.js`) pour ouvrir
    instantanément même en connexion faible ; `catalogue-fr.json` reste chargé à la demande
    (13 Mo, jamais précaché).
  - ⚠️ **Rien de tout ça n'a été testé dans un vrai navigateur** (pas d'appareil photo ni
    d'outil Chrome connecté depuis cet environnement) — vérifié uniquement par relecture et
    `node --check` sur les scripts extraits. Premier vrai test à faire par Ariel sur son
    téléphone : cadrage de la photo, temps de reconnaissance réel (jusqu'à ~11 appels Tesseract
    dans le pire cas — numéro illisible des deux côtés + nom), et surtout que l'ajout à la
    collection se reflète bien dans l'appli principale après un scan.

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
