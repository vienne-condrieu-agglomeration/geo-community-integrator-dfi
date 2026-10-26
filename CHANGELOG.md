# Journal des nouveautés

Toutes les évolutions notables de l'intégrateur DFI. Le format suit
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le versionnement
[SemVer](https://semver.org/lang/fr/).

Ce fichier s'écrit pour les **utilisateurs** de l'intégrateur, en français. La version numérotée la plus récente
doit être celle de `__version__` dans `integrator_dfi.py` (les tests le vérifient). La version du **format de
sortie** (`format` dans `index.json`) est distincte : elle est notée ici quand elle change.

## [Non publié]

## [0.1.0] — 2026-10-26

### Ajouté

- Commande `download` : télécharge la situation la plus récente des DFI sur data.gouv, extrait les départements
  demandés et les convertit. Les zip sont gardés dans un cache ; rien n'est régénéré si la situation, le périmètre
  et le format n'ont pas changé (code de sortie 10). `--previous-index` permet de lire l'index déjà publié quand
  le dossier de sortie est vide, par exemple sur un runner GitHub Actions
- Commande `convert` : convertit des fichiers départementaux déjà extraits
- Un fichier JSON par commune (lots de filiation : DFI, nature, date, parcelles mères et filles) et un
  `index.json` avec la version du format de sortie (`format` : 1), la situation et le détail par commune
- Contrôle strict du format des fichiers de la DGFiP, avec le numéro de ligne en cas d'écart
- Licences : code sous GPL-3.0-or-later, documentation sous CC-BY-4.0 (comme les modules GEO de la communauté)
- Guide de contribution (`CONTRIBUTING.md`) avec signature DCO, comme les modules
