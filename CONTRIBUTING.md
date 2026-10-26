# Contribuer à integrator-dfi

Merci de votre intérêt. Les contributions (corrections, améliorations, documentation) sont les bienvenues.

## Licence des contributions

En contribuant, vous acceptez que votre contribution soit publiée sous les licences du projet :

- le **code** sous [GPL-3.0-or-later](LICENSE) ;
- la **documentation** sous [CC-BY-4.0](LICENSE-DOCS).

## Certificat d'origine (DCO)

Chaque commit doit porter une ligne `Signed-off-by`, qui atteste que vous avez le droit de proposer cette
contribution sous la licence du projet ([Developer Certificate of Origin 1.1](https://developercertificate.org/)).
Git l'ajoute avec l'option `-s` :

```bash
git commit -s -m "fix(integrator-dfi): décrire la correction"
```

La ligne obtenue est de la forme `Signed-off-by: Prénom Nom <adresse@exemple.fr>`. Si un commit a été oublié, la
signature peut s'ajouter après coup avec `git rebase --signoff <base>`, puis un push avec `--force-with-lease`
sur **votre** branche.

## Proposer un changement

1. Ouvrez une *issue* pour une nouveauté, ou directement une demande de fusion pour une correction simple.
2. Suivez les [Conventional Commits](https://www.conventionalcommits.org/fr/v1.0.0/), en français, à l'impératif,
   avec la portée `integrator-dfi`.
3. Lancez les tests : `python3 -I -m unittest discover -s .` (Python 3, bibliothèque standard uniquement : n'ajoutez pas
   de dépendance sans en discuter).
4. Mettez à jour le `CHANGELOG.md` (en français, pour les utilisateurs) et la version : `__version__` dans
   `integrator_dfi.py` doit être celle du premier `## [x.y.z]` du journal (un test le vérifie).
5. Un changement **incompatible** du format de sortie (structure d'un lot, clés de `index.json`, codage d'une parcelle)
   incrémente `FORMAT_VERSION` et se documente dans le README : les modules qui lisent les données en dépendent.
6. Les commentaires du code sont en français, le code en anglais.

## Données

Ne commitez aucun fichier de données (zip ou fichiers `dfiano-dep…txt` de la DGFiP) : ils sont volumineux et les tests
utilisent de petits jeux de lignes écrits dans le code. Pour signaler un fichier DFI que l'intégrateur refuse, joignez
le message d'erreur (numéro de ligne compris) et, si possible, une ou deux lignes concernées.
