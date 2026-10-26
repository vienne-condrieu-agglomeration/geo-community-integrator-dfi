# integrator-dfi

Intégrateur de données pour la plateforme GEO : prépare les données du module de filiation des parcelles. Il convertit
les fichiers [DFI de la DGFiP](https://www.data.gouv.fr/datasets/documents-de-filiation-informatises-dfi-des-parcelles)
(Licence Ouverte 2.0) en **un JSON par commune** que le module lira dans le navigateur, sans serveur ni base de données.

> Projet communautaire indépendant, **non affilié à Business Geografic**. GEO est un produit de Business Geografic.

Dépôts GitHub prévus (non créés) : `geo-community-integrator-dfi` (ce code) et `geo-community-data-dfi` (workflow GitHub
Actions et données publiées sur GitHub Pages). Convention de nommage des intégrateurs : voir `CLAUDE.md`.

Python 3, bibliothèque standard uniquement.

```bash
# Télécharger la dernière situation sur data.gouv et la convertir (départements 38 et 69)
python3 -I integrator_dfi.py download --departments 38 69 --output sortie/
python3 -I integrator_dfi.py download --departments all --output sortie/            # toute la France
python3 -I integrator_dfi.py download --departments 38 69 --insee 38544 38087 --output sortie/   # communes choisies

# Convertir des fichiers déjà extraits
python3 -I integrator_dfi.py convert dfiano-dep380-01072026.txt dfiano-dep690-01072026.txt --output sortie/

python3 -I -m unittest discover -s .                                    # tests
```

`--strict` fait échouer l'exécution s'il y a des avertissements. Toute ligne qui ne respecte pas le format arrête la
conversion avec le numéro de ligne.

## Téléchargement

`download` lit les métadonnées du jeu de données (API de data.gouv), retient les zip de la **situation la plus récente**
(« situation juillet 2026 » : trimestrielle, en deux zip d'environ 175 Mo), les télécharge par leur adresse stable
`/api/1/datasets/r/<id>`, puis extrait seulement les départements demandés. `--departments` accepte `38`, `2A`, `971`, ou `all` (toute la France : les fichiers sont extraits et convertis un par un, sans jamais
en garder plus d'un sur le disque).

- Les titres de data.gouv comportent des coquilles (`juillet 20266`) et leurs plages de départements ne sont pas fiables :
  seuls le mois et l'année sont lus ; le contenu est vérifié dans le zip. Un département absent des zip fait échouer l'exécution.
- Les zip sont gardés dans un cache (`--cache`, par défaut `$XDG_CACHE_HOME/integrator-dfi` ou `~/.cache/integrator-dfi`) et ne sont
  pas retéléchargés si leur taille est inchangée.
- Si l'index précédent indique déjà les mêmes ressources et le même périmètre, rien n'est régénéré (`--force` pour forcer)
  et le **code de sortie est 10** (0 = données générées, 1 = erreur). L'index précédent est `sortie/index.json`, ou celui
  donné par `--previous-index` (fichier ou adresse https).
- Seules les adresses `https` sont suivies. Les noms de fichiers extraits sont limités au motif `dfiano-depXXX-JJMMAAAA.txt`.
- **En CI (GitHub Actions)** : le runner repart de zéro à chaque exécution, donc le dossier de sortie est vide et le
  cache aussi. Passer l'index déjà publié (`--previous-index https://…/index.json`) et un cache temporaire
  (`--cache "$RUNNER_TEMP/dfi"`) ; le code 10 permet de sauter l'étape de déploiement. Le téléchargement (environ
  350 Mo) prend moins d'une minute, un `actions/cache` n'est pas utile.
- L'index porte le `millesime` (mois de la situation), les identifiants des ressources et le périmètre demandé.

## Format des fichiers DFI

Un lot d'analyse = deux lignes : type 1 (parcelles mères) puis type 2 (parcelles filles), séparateur `;`, fins de ligne `\r\n`.
Le fichier réel compte **10 champs avant les cellules de parcelles**, le descriptif PDF n'en décrit que 9 (colonne `XNUMX`
entre le nom du géomètre et le numéro de lot). Une section cadastrale d'une seule lettre est cadrée par une espace
(` C0637`) : le script la complète par `0` (`0C0637`), comme dans un IDU.

Les modifications issues des aménagements fonciers ruraux ne figurent pas dans les DFI.

## Format de sortie

`<insee>.json` :

```json
{"insee":"38544","lots":[["0000867","00001",1,"1988-11-16",[],["AO0357","AO0358"]], …]}
```

Un lot est `[identifiant du DFI, numéro de lot, nature, date, parcelles mères, parcelles filles]`.

- **Nature** : 1 document d'arpentage, 2 croquis de conservation, 4 remaniement, 5 document d'arpentage numérique,
  6 lotissement numérique, 7 lotissement, 8 rénovation.
- **Listes vides** : sans mère, la parcelle vient du domaine non cadastré ; sans fille, elle passe au domaine public ou disparaît.
- **Parcelle** : section (2) + numéro (4), par exemple `AH0280`. Si la section a un préfixe différent de `000` (commune
  fusionnée), il est placé devant : `014AH0280`. L'IDU complet est `INSEE` (5) + préfixe (3, `000` par défaut) + parcelle.
- Les lots sont triés par date, identifiant puis numéro : deux exécutions sur les mêmes données donnent les mêmes fichiers.

`index.json` : `format`, `integrateur` (version de l'intégrateur), `source`, `licence`, `situation` (date la plus récente lue dans les noms de
fichiers), nombre de lots par nature et par commune, **nom de la commune** (`nom`), nombre d'avertissements. Un avertissement signale une parcelle fille de plusieurs lots
d'une même commune (cas absent des départements 38 et 69 de juillet 2026). Avec `download`, l'index porte aussi
`millesime`, `ressources`, `departements` et `insee`.

**`format`** (entier, actuellement `1`) est la version du format de sortie : **le module le lit en premier** et refuse un
format qu'il ne connaît pas. Il est incrémenté pour tout changement incompatible (structure d'un lot, clés de l'index,
codage d'une parcelle) ; un ajout qui laisse fonctionner les lecteurs existants n'y touche pas. Un changement de `format`
force aussi la régénération de `download`, même si la situation de data.gouv n'a pas changé.

Un fichier n'est pas cumulatif d'une situation à l'autre (des lots peuvent disparaître) : régénérer toutes les communes à chaque fois.

## Licence

- **Code** : [GPL-3.0-or-later](LICENSE) — © 2026 Vienne Condrieu Agglomération.
- **Documentation** (ce README, `CHANGELOG.md`) : [CC-BY-4.0](LICENSE-DOCS).
- **Données produites** : issues du jeu de données de la DGFiP sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) ;
  la source est rappelée dans `index.json` (`source`, `licence`, `situation`) et doit être citée par les modules qui les affichent.
- **Marques** : « GEO » et « Business Geografic » sont des marques de leurs titulaires ; cet intégrateur est indépendant
  et n'est ni édité ni approuvé par Business Geografic.
- Aucune dépendance tierce : bibliothèque standard de Python uniquement.

Les contributions se font sous la même licence, avec signature DCO : voir [CONTRIBUTING.md](CONTRIBUTING.md).

## Noms des communes

Les fichiers de la DGFiP ne donnent que le code INSEE. À la génération, l'intégrateur interroge l'API Géo (`geo.api.gouv.fr`, un appel par
département, un second pour les arrondissements de Paris, Lyon et Marseille et les communes associées ou déléguées) et ajoute `nom` à chaque
commune de `index.json`. Le service est facultatif : s'il est indisponible, les noms de l'index précédent sont repris ; une commune sans nom
reste valide (les modules affichent alors son code). `--no-names` désactive cette étape (hors ligne). Le champ est additif : le format de
sortie reste le 1. Changer de version de l'intégrateur régénère les données même si la situation de data.gouv n'a pas changé.
