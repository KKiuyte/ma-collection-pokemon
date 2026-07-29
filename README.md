# Ma Collection Pokémon

Application web personnelle pour suivre ma collection de cartes Pokémon : séries,
versions (Normale, Reverse, Holo…), liste de souhaits, prix estimés et valeur totale.
En ligne : https://ma-collection-pokemon.web.app/

## C'est quoi, techniquement

Un **seul fichier HTML autonome** (`public/index.html`) — pas de framework, pas de build.
Hébergé sur Firebase Hosting, avec compte et synchronisation via Firebase, et données
des cartes issues de l'API TCGdex. C'est aussi une **PWA** (installable, fonctionne
hors-ligne).

> 🧠 Si tu utilises **Claude Code**, tout le contexte du projet (architecture, modèle de
> données, pièges à éviter, procédure de déploiement, état d'avancement) est dans
> **`CLAUDE.md`**, lu automatiquement. Commence par là.

## Démarrer avec Claude Code

```
# dans le dossier du projet
claude
```
Puis décris ce que tu veux faire, en français. Claude Code lit `CLAUDE.md` et connaît
le projet.

## Déployer

```
firebase deploy --only hosting
```
⚠️ Si `public/sw.js` ou l'appli a changé, **incrémenter `VERSION`** en haut de `sw.js`
avant de déployer (sinon l'ancienne version reste en cache).

## Organisation

- `public/` — le site déployé (`index.html` = l'application)
- `tools/build_hashes.py` — génère les empreintes visuelles pour la reconnaissance photo
- `roadmap.md` — feuille de route et notes
- `archive/` — anciens fichiers conservés volontairement (voir `CLAUDE.md`)
