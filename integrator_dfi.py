#!/usr/bin/env python3
"""Convertit les fichiers DFI de la DGFiP en un JSON par commune.

Source : https://www.data.gouv.fr/datasets/documents-de-filiation-informatises-dfi-des-parcelles
Format de sortie : voir README.md.

Usage :
    python3 -I integrator_dfi.py convert FICHIER... --output DOSSIER [--insee CODE...]
    python3 -I integrator_dfi.py download --departments 38 69 --output DOSSIER [--cache DOSSIER]
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

# Version de l'intégrateur (la même que la première entrée numérotée de CHANGELOG.md ; vérifié par les tests et par
# scripts/publish-module.sh). Distincte de FORMAT_VERSION, qui est celle du format de sortie.
__version__ = "0.1.0"

SOURCE = "DGFiP, Documents de filiation informatisés (DFI) des parcelles"
LICENSE = "Licence Ouverte 2.0"
# Version du format de sortie (index.json et JSON des communes), lue par le module. À incrémenter pour tout changement
# incompatible (structure d'un lot, clés de l'index) ; un ajout qui laisse les lecteurs existants fonctionner n'y touche pas.
FORMAT_VERSION = 1
API_URL = "https://www.data.gouv.fr/api/1/datasets/documents-de-filiation-informatises-dfi-des-parcelles/"
USER_AGENT = "integrator-dfi (geo-api-v2)"
MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
          "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
# Titre d'une ressource : « … (situation juillet 2026)- dept2A0 à dept49.zip » (coquilles fréquentes : « 20266 »)
SITUATION_RE = re.compile(r"situation\s+([a-z]+)\s+(20\d\d)")
# Fichier départemental dans un zip : dfiano-dep380-01072026.txt
MEMBER_RE = re.compile(r"^dfiano-dep([0-9A-Z]{3})-\d{8}\.txt$")

# Nom d'un fichier départemental : dfiano-dep380-01072026.txt (date au format JJMMAAAA)
FILENAME_RE = re.compile(r"-(\d{2})(\d{2})(\d{4})\.txt$")
PARCEL_RE = re.compile(r"^[0-9A-Z]{2}[0-9]{4}$")

# Champs avant les cellules de parcelles. Le descriptif PDF en décrit 9 ; le fichier réel en
# compte 10 (colonne supplémentaire « XNUMX » entre le géomètre et le numéro de lot).
FIELDS_BEFORE_CELLS = 10


class FormatError(Exception):
    """Fichier DFI qui ne respecte pas le format attendu."""


class DownloadError(Exception):
    """Ressource introuvable ou téléchargement incomplet."""


def parse_line(line, where):
    """Découpe une ligne et valide ses champs. Retourne un dictionnaire."""
    fields = line.split(";")
    if len(fields) < FIELDS_BEFORE_CELLS:
        raise FormatError(f"{where} : {len(fields)} champs, {FIELDS_BEFORE_CELLS} attendus au moins")
    department, commune, prefix, dfi, nature, date, _surveyor, _xnum, lot, kind = fields[:10]
    if not (len(department) == 3 and len(commune) == 3 and len(prefix) == 3 and prefix.isdigit()):
        raise FormatError(f"{where} : département, commune ou préfixe de section invalide")
    if not (len(dfi) == 7 and dfi.isdigit()):
        raise FormatError(f"{where} : identifiant de DFI invalide ({dfi!r})")
    if not (len(nature) == 1 and nature.isdigit()):
        raise FormatError(f"{where} : nature invalide ({nature!r})")
    if not (len(lot) == 5 and lot.isdigit()):
        raise FormatError(f"{where} : numéro de lot invalide ({lot!r})")
    if kind not in ("1", "2"):
        raise FormatError(f"{where} : type de ligne invalide ({kind!r})")
    try:
        iso_date = datetime.datetime.strptime(date, "%Y%m%d").date().isoformat()
    except ValueError:
        raise FormatError(f"{where} : date invalide ({date!r})") from None
    # Une section d'une seule lettre est cadrée avec une espace (« C0637 ») ; l'IDU la complète par « 0 »
    cells = ["0" + cell[1:] if cell.startswith(" ") else cell for cell in fields[10:] if cell]
    for cell in cells:
        if not PARCEL_RE.match(cell):
            raise FormatError(f"{where} : parcelle invalide ({cell!r})")
    # Le préfixe de section n'est conservé que lorsqu'il n'est pas « 000 »
    parcels = [cell if prefix == "000" else prefix + cell for cell in cells]
    return {
        "insee": department[:2] + commune,
        "dfi": dfi,
        "lot": lot,
        "nature": int(nature),
        "date": iso_date,
        "kind": kind,
        "parcels": parcels,
        "prefix": prefix,
    }


def read_lots(lines, name="fichier"):
    """Regroupe les lignes par paires (type 1 = mères, type 2 = filles) et produit un lot par paire.

    Un lot est [dfi, lot, nature, date, mères, filles]. Les listes peuvent être vides : une parcelle
    issue du domaine non cadastré n'a pas de mère, un passage au domaine public n'a pas de fille.
    """
    pending = None
    for number, raw in enumerate(lines, 1):
        line = raw.rstrip("\r\n")
        if not line:
            continue
        where = f"{name}, ligne {number}"
        record = parse_line(line, where)
        key = (record["insee"], record["prefix"], record["dfi"], record["lot"])
        if record["kind"] == "1":
            if pending is not None:
                raise FormatError(f"{where} : ligne de type 1 sans ligne de type 2 avant elle")
            pending = (key, record)
            continue
        if pending is None or pending[0] != key:
            raise FormatError(f"{where} : ligne de type 2 sans ligne de type 1 correspondante")
        mother = pending[1]
        pending = None
        if (mother["nature"], mother["date"]) != (record["nature"], record["date"]):
            raise FormatError(f"{where} : nature ou date différente entre les deux lignes du lot")
        yield record["insee"], [
            record["dfi"], record["lot"], record["nature"], record["date"],
            mother["parcels"], record["parcels"],
        ]
    if pending is not None:
        raise FormatError(f"{name} : le fichier se termine sur une ligne de type 1")


def file_date(path):
    """Date de situation inscrite dans le nom du fichier, ou None."""
    match = FILENAME_RE.search(Path(path).name)
    if not match:
        return None
    day, month, year = match.groups()
    return datetime.date(int(year), int(month), int(day))


def duplicate_daughters(lots):
    """Parcelles qui apparaissent comme fille dans plus d'un lot d'une même commune."""
    seen = Counter()
    for lot in lots:
        for parcel in set(lot[5]):
            seen[parcel] += 1
    return sorted(parcel for parcel, count in seen.items() if count > 1)


def convert(inputs, output, wanted=None, extra=None):
    """Convertit des fichiers départementaux et écrit un JSON par commune plus index.json.

    `extra` : informations ajoutées à l'index (origine des fichiers, périmètre demandé).
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    communes = {}
    natures = Counter()
    warnings = []
    dates = []
    for path in inputs:
        path = Path(path)
        by_commune = defaultdict(list)
        with open(path, encoding="latin-1", newline=None) as handle:
            for insee, lot in read_lots(handle, path.name):
                if wanted and insee not in wanted:
                    continue
                by_commune[insee].append(lot)
        for insee, lots in by_commune.items():
            if insee in communes:
                raise FormatError(f"{path.name} : la commune {insee} figure dans plusieurs fichiers")
            # Tri déterministe : deux exécutions sur les mêmes données donnent les mêmes fichiers
            lots.sort(key=lambda lot: (lot[3], lot[0], lot[1]))
            for parcel in duplicate_daughters(lots):
                warnings.append(f"{insee} : la parcelle {parcel} est fille de plusieurs lots")
            natures.update(lot[2] for lot in lots)
            payload = {"insee": insee, "lots": lots}
            (output / f"{insee}.json").write_text(
                json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            communes[insee] = {"lots": len(lots)}
        date = file_date(path)
        if date:
            dates.append(date)
    if wanted:
        missing = sorted(wanted - set(communes))
        if missing:
            warnings.append("communes demandées absentes des fichiers : " + ", ".join(missing))
    index = {
        "format": FORMAT_VERSION,
        "source": SOURCE,
        "licence": LICENSE,
        "situation": max(dates).isoformat() if dates else None,
        "natures": {str(nature): count for nature, count in sorted(natures.items())},
        "avertissements": len(warnings),
        "communes": dict(sorted(communes.items())),
    }
    index.update(extra or {})
    (output / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return index, warnings


ALLOWED_SCHEMES = ("https",)
EXIT_UP_TO_DATE = 10


def normalize(text):
    """Minuscules sans accents."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def discover(dataset):
    """Retient les zip de la situation la plus récente du jeu de données.

    Retourne ((année, mois), ressources, titres ignorés). Les titres de data.gouv comportent des coquilles
    et ne décrivent pas toujours le contenu : seule la situation (mois et année) en est tirée.
    """
    found = {}
    ignored = []
    for resource in dataset.get("resources", []):
        title = resource.get("title", "")
        if resource.get("format") != "zip" and not title.lower().endswith(".zip"):
            continue
        match = SITUATION_RE.search(normalize(title))
        if not match or match.group(1) not in MONTHS:
            ignored.append(title)
            continue
        found.setdefault((int(match.group(2)), MONTHS[match.group(1)]), []).append(resource)
    if not found:
        raise DownloadError("aucune ressource zip « situation <mois> <année> » dans le jeu de données")
    latest = max(found)
    return latest, sorted(found[latest], key=lambda resource: resource["title"]), ignored


def department_file_code(code):
    """Code départemental des fichiers DFI (3 caractères) : 38 -> 380, 2A -> 2A0, 971 -> 971."""
    code = code.upper()
    if len(code) == 2:
        return code + "0"
    if len(code) == 3:
        return code
    raise DownloadError(f"code de département invalide : {code!r}")


def download_file(url, destination):
    """Télécharge `url` vers `destination` (en flux). Ne retélécharge pas un fichier de même taille."""
    if urllib.parse.urlparse(url).scheme not in ALLOWED_SCHEMES:
        raise DownloadError(f"adresse non autorisée : {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    destination = Path(destination)
    with urllib.request.urlopen(request, timeout=60) as response:
        size = int(response.headers.get("Content-Length", -1))
        if size >= 0 and destination.exists() and destination.stat().st_size == size:
            return False
        partial = destination.with_suffix(".part")
        with open(partial, "wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
        if size >= 0 and partial.stat().st_size != size:
            partial.unlink()
            raise DownloadError(f"téléchargement incomplet : {url}")
        partial.replace(destination)
    return True


def extract_departments(zip_path, codes, workdir):
    """Extrait du zip les fichiers des départements demandés. Retourne {code: chemin}."""
    extracted = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            match = MEMBER_RE.match(name)  # le motif exclut tout séparateur de chemin
            if match and match.group(1) in codes:
                target = Path(workdir) / name
                with archive.open(name) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out, 1 << 20)
                extracted[match.group(1)] = target
    return extracted


def default_cache():
    """Cache des zip : $XDG_CACHE_HOME/integrator-dfi, sinon ~/.cache/integrator-dfi."""
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "integrator-dfi"


def load_previous_index(source, log):
    """Lit l'index d'une exécution précédente (fichier ou adresse https). Retourne None s'il est absent ou illisible.

    Sur un runner GitHub Actions le dossier de sortie est vide : l'index déjà publié se lit à son adresse.
    """
    source = str(source)
    try:
        if urllib.parse.urlparse(source).scheme in ALLOWED_SCHEMES:
            request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        return json.loads(Path(source).read_text(encoding="utf-8")) if Path(source).exists() else None
    except (OSError, ValueError) as error:  # pas encore publié, ou indisponible : on régénère
        log(f"Index précédent inutilisable ({error}), régénération")
        return None


def download(departments, output, cache, wanted=None, force=False, api_url=API_URL, log=print, previous_index=None):
    """Télécharge la dernière situation des DFI et la convertit. Retourne (index, avertissements) ou None.

    None signifie « déjà à jour » : l'index précédent (`previous_index`, par défaut `output/index.json`)
    porte les mêmes ressources et le même périmètre.
    """
    codes = {department_file_code(department) for department in departments}
    request = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        dataset = json.load(response)
    (year, month), resources, ignored = discover(dataset)
    for title in ignored:
        log(f"Avertissement : ressource ignorée (situation illisible) : {title}")
    log(f"Situation retenue : {month:02d}/{year}, {len(resources)} zip")
    ids = sorted(resource["id"] for resource in resources)
    scope = {"departements": sorted(departments), "insee": sorted(wanted) if wanted else None}
    if not force:
        previous = load_previous_index(previous_index or Path(output) / "index.json", log)
        # Un autre format de sortie impose de régénérer, même si la situation de data.gouv n'a pas changé
        if previous and previous.get("format") == FORMAT_VERSION and previous.get("ressources") == ids \
                and all(previous.get(key) == value for key, value in scope.items()):
            log("Données déjà à jour (utiliser --force pour régénérer)")
            return None
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    files = {}
    with tempfile.TemporaryDirectory(dir=cache) as work:
        for resource in resources:
            zip_path = cache / f"{resource['id']}.zip"
            fresh = download_file(resource["latest"], zip_path)
            log(f"{'Téléchargé' if fresh else 'Déjà en cache'} : {resource['title']}")
            for code, path in extract_departments(zip_path, codes, work).items():
                if code in files:
                    raise DownloadError(f"le département {code} figure dans plusieurs zip")
                files[code] = path
        missing = sorted(codes - set(files))
        if missing:
            raise DownloadError("départements absents des zip : " + ", ".join(missing))
        extra = {"millesime": f"{year}-{month:02d}", "ressources": ids, **scope}
        return convert([files[code] for code in sorted(files)], output, wanted, extra)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("convert", help="convertit des fichiers DFI départementaux")
    conv.add_argument("inputs", nargs="+", help="fichiers dfiano-depXXX-JJMMAAAA.txt")
    conv.add_argument("--output", required=True, help="dossier de sortie")
    conv.add_argument("--insee", nargs="+", default=None, help="ne garder que ces communes (codes INSEE)")
    conv.add_argument("--strict", action="store_true", help="échouer s'il y a des avertissements")
    down = sub.add_parser("download", help="télécharge la dernière situation sur data.gouv et la convertit")
    down.add_argument("--departments", nargs="+", required=True, help="départements voulus (38 69 2A 971…)")
    down.add_argument("--output", required=True, help="dossier de sortie")
    down.add_argument("--cache", default=str(default_cache()),
                      help="dossier des zip téléchargés (défaut : $XDG_CACHE_HOME/integrator-dfi ou ~/.cache/integrator-dfi)")
    down.add_argument("--previous-index", default=None,
                      help="index.json d'une exécution précédente (fichier ou adresse https), "
                           "à la place de SORTIE/index.json : utile quand le dossier de sortie est vide (CI)")
    down.add_argument("--api-url", default=API_URL, help=argparse.SUPPRESS)
    down.add_argument("--insee", nargs="+", default=None, help="ne garder que ces communes (codes INSEE)")
    down.add_argument("--force", action="store_true", help="régénérer même si la situation n'a pas changé")
    down.add_argument("--strict", action="store_true", help="échouer s'il y a des avertissements")
    args = parser.parse_args(argv)
    wanted = set(args.insee) if args.insee else None
    try:
        if args.command == "convert":
            result = convert(args.inputs, args.output, wanted)
        else:
            result = download(args.departments, args.output, args.cache, wanted, args.force,
                              api_url=args.api_url, previous_index=args.previous_index)
    except (FormatError, DownloadError, OSError, zipfile.BadZipFile, ValueError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    if result is None:  # situation déjà à jour : code distinct pour que la CI saute le déploiement
        return EXIT_UP_TO_DATE
    index, warnings = result
    lots = sum(commune["lots"] for commune in index["communes"].values())
    print(f"{len(index['communes'])} communes, {lots} lots, situation {index['situation']}")
    for warning in warnings:
        print(f"Avertissement : {warning}", file=sys.stderr)
    return 1 if (warnings and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
