"""Tests de integrator_dfi.py : python3 -I -m unittest discover -s src/integrators/dfi"""
import json
import re
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

import integrator_dfi as dfi_data

SURVEYOR = "XXXXXREDACTEURDUDOCUMENTXXXXXX"


def line(commune, dfi, nature, date, lot, kind, *cells, prefix="000", department="380"):
    """Construit une ligne au format réel (colonne XNUMX, point-virgule final)."""
    head = [department, commune, prefix, dfi, nature, date, SURVEYOR, "XNUMX", lot, kind]
    return ";".join(head + list(cells)) + ";"


SAMPLE = "\r\n".join([
    # division AC26 -> AC214, AC215
    line("001", "0000450", "1", "19900813", "00001", "1", "AC0026"),
    line("001", "0000450", "1", "19900813", "00001", "2", "AC0214", "AC0215"),
    # parcelle issue du domaine non cadastré (aucune mère)
    line("001", "0000451", "2", "19910101", "00001", "1"),
    line("001", "0000451", "2", "19910101", "00001", "2", "AC0300"),
    # passage au domaine public (aucune fille)
    line("002", "0000452", "2", "20100105", "00001", "1", "AW0484"),
    line("002", "0000452", "2", "20100105", "00001", "2"),
    # section d'une seule lettre : cellule cadrée avec une espace
    line("003", "0000454", "1", "19990101", "00001", "1", " C0637"),
    line("003", "0000454", "1", "19990101", "00001", "2", " C0774", " C0775"),
    # commune fusionnée : préfixe de section 014
    line("002", "0000453", "1", "20000101", "00001", "1", "AB0001", prefix="014"),
    line("002", "0000453", "1", "20000101", "00001", "2", "AB0002", "AB0003", prefix="014"),
]) + "\r\n"


class ParseTest(unittest.TestCase):
    def read(self, text):
        return list(dfi_data.read_lots(text.splitlines(keepends=True)))

    def test_cases(self):
        lots = dict((lot[0], (insee, lot)) for insee, lot in self.read(SAMPLE))
        self.assertEqual(lots["0000450"], ("38001", ["0000450", "00001", 1, "1990-08-13", ["AC0026"], ["AC0214", "AC0215"]]))
        self.assertEqual(lots["0000451"][1][4], [])          # aucune mère
        self.assertEqual(lots["0000452"][1][5], [])          # aucune fille
        self.assertEqual(lots["0000454"][1][4:], [["0C0637"], ["0C0774", "0C0775"]])  # espace -> 0
        self.assertEqual(lots["0000453"][1][4:], [["014AB0001"], ["014AB0002", "014AB0003"]])

    def test_rejects_missing_column(self):
        # Descriptif PDF : 9 champs avant les cellules, il manque la colonne XNUMX
        bad = "380;001;000;0000450;1;19900813;" + SURVEYOR + ";00001;1;AC0026;\r\n"
        with self.assertRaises(dfi_data.FormatError):
            self.read(bad)

    def test_rejects_unpaired_lines(self):
        first = line("001", "0000450", "1", "19900813", "00001", "1", "AC0026")
        with self.assertRaises(dfi_data.FormatError):
            self.read(first + "\r\n")                        # type 1 sans type 2
        second = line("001", "0000450", "1", "19900813", "00001", "2", "AC0214")
        with self.assertRaises(dfi_data.FormatError):
            self.read(second + "\r\n")                       # type 2 sans type 1

    def test_rejects_bad_date_and_parcel(self):
        with self.assertRaises(dfi_data.FormatError):
            self.read(line("001", "0000450", "1", "19901345", "00001", "1") + "\r\n")
        with self.assertRaises(dfi_data.FormatError):
            self.read(line("001", "0000450", "1", "19900813", "00001", "1", "AC26") + "\r\n")

    def test_file_date(self):
        self.assertEqual(str(dfi_data.file_date("dfiano-dep380-01072026.txt")), "2026-07-01")
        self.assertIsNone(dfi_data.file_date("autre.txt"))


class ConvertTest(unittest.TestCase):
    def convert(self, text, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = Path(tmp.name) / "dfiano-dep380-01072026.txt"
        source.write_bytes(text.encode("latin-1"))
        out = Path(tmp.name) / "out"
        index, warnings = dfi_data.convert([source], out, **kwargs)
        return out, index, warnings

    def test_one_file_per_commune_and_index(self):
        out, index, warnings = self.convert(SAMPLE)
        self.assertEqual(sorted(index["communes"]), ["38001", "38002", "38003"])
        self.assertEqual(index["situation"], "2026-07-01")
        self.assertEqual(index["format"], 1)  # le module refuse un format qu'il ne connaît pas
        self.assertEqual(json.loads((out / "index.json").read_text())["format"], dfi_data.FORMAT_VERSION)
        self.assertEqual(warnings, [])
        data = json.loads((out / "38001.json").read_text())
        self.assertEqual(data["insee"], "38001")
        self.assertEqual([lot[0] for lot in data["lots"]], ["0000450", "0000451"])  # tri par date

    def test_names_and_integrator_version_in_index(self):
        out, index, _ = self.convert(SAMPLE, names_provider=lambda insees: {"38001": "Abc", "38002": "Déf", "99999": "Hors"})
        self.assertEqual(index["communes"]["38001"], {"lots": 2, "nom": "Abc"})
        self.assertEqual(index["communes"]["38003"], {"lots": 1}, "commune sans nom : pas de champ nom")
        self.assertNotIn("99999", index["communes"])
        self.assertEqual(index["integrateur"], dfi_data.__version__)
        self.assertEqual(index["format"], 1, "champ additif : le format de sortie ne change pas")
        self.assertEqual(json.loads((out / "index.json").read_text())["communes"]["38002"]["nom"], "Déf")

    def test_filter_and_missing_commune(self):
        out, index, warnings = self.convert(SAMPLE, wanted={"38001", "38999"})
        self.assertEqual(sorted(index["communes"]), ["38001"])
        self.assertFalse((out / "38002.json").exists())
        self.assertTrue(any("38999" in warning for warning in warnings))

    def test_duplicate_daughter_warning(self):
        text = SAMPLE + "\r\n".join([
            line("001", "0000460", "1", "19950101", "00001", "1", "AC0214"),
            line("001", "0000460", "1", "19950101", "00001", "2", "AC0215"),
        ]) + "\r\n"
        _, _, warnings = self.convert(text)
        self.assertEqual(len(warnings), 1)
        self.assertIn("AC0215", warnings[0])


def resource(rid, title, url="https://example.invalid/x", fmt="zip"):
    return {"id": rid, "title": title, "format": fmt, "latest": url}


class VersionTest(unittest.TestCase):
    def test_version_matches_changelog(self):
        """La version du script est celle de la première entrée numérotée du journal (publish-module.sh le vérifie aussi)."""
        changelog = (Path(__file__).with_name("CHANGELOG.md")).read_text(encoding="utf-8")
        match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(dfi_data.__version__, match.group(1))


class NamesTest(unittest.TestCase):
    """Noms des communes : API Géo simulée."""

    def fake(self, data, calls=None):
        def fetch(url):
            if calls is not None:
                calls.append(url)
            for key, value in data.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return value
            return []
        return fetch

    def test_department_of(self):
        self.assertEqual([dfi_data.department_of(c) for c in ("38544", "2A004", "2B033", "97101", "97611", "75101", "01001")],
                         ["38", "2A", "2B", "971", "976", "75", "01"])

    def test_names_by_department_and_second_call_for_other_types(self):
        calls = []
        data = {"codeDepartement=69&fields=nom,code&type=": [{"code": "69381", "nom": "Lyon 1er Arrondissement"}],
                "codeDepartement=69&fields=nom,code": [{"code": "69007", "nom": "Ampuis"}, {"code": "69999", "nom": "Hors périmètre"}],
                "codeDepartement=38": [{"code": "38544", "nom": "Vienne"}]}
        logs = []
        names = dfi_data.fetch_commune_names(["38544", "69007", "69381", "69888"], fetch=self.fake(data, calls), log=logs.append)
        self.assertEqual(names, {"38544": "Vienne", "69007": "Ampuis", "69381": "Lyon 1er Arrondissement"})
        self.assertEqual(len(calls), 3, "38 : 1 appel (tout résolu) ; 69 : 2 appels (communes actuelles, puis les autres types)")
        self.assertTrue(any("type=arrondissement-municipal,commune-associee,commune-deleguee" in c for c in calls))
        self.assertTrue(any("3 sur 4" in line and "1 sans nom" in line for line in logs), logs)

    def test_failure_reuses_previous_names_and_never_raises(self):
        previous = {"communes": {"38544": {"lots": 1, "nom": "Vienne"}, "38001": {"lots": 1}}}
        logs = []
        names = dfi_data.fetch_commune_names(["38544", "38001"], previous, self.fake({"codeDepartement=38": dfi_data.DownloadError("hors ligne")}), logs.append)
        self.assertEqual(names, {"38544": "Vienne"})
        self.assertTrue(any("indisponibles" in line for line in logs))
        self.assertTrue(any("dont 1 repris de l'index précédent" in line for line in logs))

    def test_partial_failure_keeps_other_departments(self):
        data = {"codeDepartement=38": dfi_data.DownloadError("x"), "codeDepartement=69": [{"code": "69007", "nom": "Ampuis"}]}
        names = dfi_data.fetch_commune_names(["38544", "69007"], fetch=self.fake(data), log=lambda m: None)
        self.assertEqual(names, {"69007": "Ampuis"})

    def test_get_json_rejects_insecure_scheme(self):
        with self.assertRaises(dfi_data.DownloadError):
            dfi_data.get_json("http://exemple.invalid/x")


class DiscoverTest(unittest.TestCase):
    def test_latest_situation_tolerates_typos(self):
        dataset = {"resources": [
            resource("a", "Documents de filiation informatisés (situation avril 2026).zip"),
            resource("b", "Documents de filiation informatisés (situation juillet 2026)- dept2A0 à dept49.zip"),
            resource("c", "Documents de filiation informatisés (situation juillet 20266)- dept 50 à dept 976.zip"),
            resource("d", "Documents de filiations informatisés (situation Octobre 2025) - dept 560 à dept 976.zip"),
            resource("e", "descriptif du fichier", fmt="pdf"),
            resource("f", "Archive sans situation lisible.zip"),
        ]}
        (year, month), resources, ignored = dfi_data.discover(dataset)
        self.assertEqual((year, month), (2026, 7))
        self.assertEqual(sorted(r["id"] for r in resources), ["b", "c"])
        self.assertEqual(ignored, ["Archive sans situation lisible.zip"])

    def test_no_situation(self):
        with self.assertRaises(dfi_data.DownloadError):
            dfi_data.discover({"resources": [resource("e", "descriptif", fmt="pdf")]})

    def test_department_file_code(self):
        self.assertEqual([dfi_data.department_file_code(c) for c in ("38", "2a", "971")], ["380", "2A0", "971"])
        with self.assertRaises(dfi_data.DownloadError):
            dfi_data.department_file_code("3")


class DownloadTest(unittest.TestCase):
    """Téléchargement simulé : les adresses https sont remplacées par des fichiers locaux (file://)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        for patcher in (unittest.mock.patch.object(dfi_data, "ALLOWED_SCHEMES", ("https", "file")),
                        # aucun appel réseau pour les noms de communes (les tests de noms fournissent leur propre service)
                        unittest.mock.patch.object(dfi_data, "get_json", lambda url, attempts=3: [])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_zip(self, name, members):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, text in members.items():
                archive.writestr(member, text.encode("latin-1"))
        return path

    def make_api(self, resources):
        path = self.tmp / "api.json"
        path.write_text(json.dumps({"resources": resources}))
        return path.as_uri()

    def test_download_and_convert(self):
        zip38 = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE,
                                         "dfiano-dep010-01072026.txt": "ligne invalide non lue\r\n"})
        zip69 = self.make_zip("b.zip", {"dfiano-dep690-01072026.txt": SAMPLE.replace("380;", "690;")})
        api = self.make_api([
            resource("id38", "DFI (situation juillet 2026)- dept2A0 à dept49.zip", zip38.as_uri()),
            resource("id69", "DFI (situation juillet 20266)- dept 50 à dept 976.zip", zip69.as_uri()),
            resource("old", "DFI (situation avril 2026).zip", "file:///inexistant"),
        ])
        logs = []
        out, cache = self.tmp / "out", self.tmp / "cache"
        index, warnings = dfi_data.download(["38", "69"], out, cache, api_url=api, log=logs.append)
        self.assertEqual(index["millesime"], "2026-07")
        self.assertEqual(index["ressources"], ["id38", "id69"])
        self.assertIn("38001", index["communes"])
        self.assertIn("69001", index["communes"])
        self.assertTrue((out / "69001.json").exists())
        self.assertEqual(sorted(p.name for p in cache.iterdir()), ["id38.zip", "id69.zip"])  # extraction nettoyée
        # Deuxième exécution : situation inchangée, rien à faire
        self.assertIsNone(dfi_data.download(["38", "69"], out, cache, api_url=api, log=logs.append))
        self.assertIn("Données déjà à jour (utiliser --force pour régénérer)", logs)
        # Un périmètre différent relance la conversion, sans retélécharger
        again = dfi_data.download(["38"], out, cache, api_url=api, log=logs.append)
        self.assertEqual(again[0]["departements"], ["38"])
        self.assertIn("Déjà en cache : DFI (situation juillet 2026)- dept2A0 à dept49.zip", logs)

    def test_missing_department(self):
        zip38 = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE})
        api = self.make_api([resource("id38", "DFI (situation juillet 2026).zip", zip38.as_uri())])
        with self.assertRaises(dfi_data.DownloadError):
            dfi_data.download(["38", "69"], self.tmp / "out", self.tmp / "cache", api_url=api, log=lambda m: None)

    def test_rejects_unsafe_scheme_and_truncated_download(self):
        with unittest.mock.patch.object(dfi_data, "ALLOWED_SCHEMES", ("https",)):
            with self.assertRaises(dfi_data.DownloadError):
                dfi_data.download_file((self.tmp / "x").as_uri(), self.tmp / "y.zip")
        source = self.tmp / "source.bin"
        source.write_bytes(b"0123456789")
        destination = self.tmp / "copy.bin"
        self.assertTrue(dfi_data.download_file(source.as_uri(), destination))
        self.assertFalse(dfi_data.download_file(source.as_uri(), destination))  # même taille : ignoré

    def test_previous_index_for_empty_output_folder(self):
        """Sur un runner, le dossier de sortie est vide : l'index publié sert à décider."""
        zip38 = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE})
        api = self.make_api([resource("id38", "DFI (situation juillet 2026).zip", zip38.as_uri())])
        first, cache = self.tmp / "first", self.tmp / "cache"
        dfi_data.download(["38"], first, cache, api_url=api, log=lambda m: None)
        published = first / "index.json"
        fresh = self.tmp / "fresh"  # dossier vide, comme sur un runner
        quiet = dict(api_url=api, log=lambda m: None)
        # par fichier, par adresse, puis avec un périmètre différent ou --force : régénération
        self.assertIsNone(dfi_data.download(["38"], fresh, cache, previous_index=published, **quiet))
        self.assertIsNone(dfi_data.download(["38"], fresh, cache, previous_index=published.as_uri(), **quiet))
        self.assertIsNotNone(dfi_data.download(["38"], fresh, cache, wanted={"38001"},
                                               previous_index=published, **quiet))
        self.assertIsNotNone(dfi_data.download(["38"], fresh, cache, force=True, previous_index=published, **quiet))
        # index précédent d'un autre format (ou sans format) : régénération, même situation de data.gouv
        old = json.loads(published.read_text())
        for value in (0, None):
            if value is None:
                del old["format"]
            else:
                old["format"] = value
            stale = self.tmp / "stale.json"
            stale.write_text(json.dumps(old))
            self.assertIsNotNone(dfi_data.download(["38"], fresh, cache, previous_index=stale, **quiet))
        # index précédent absent ou illisible : régénération, sans erreur
        logs = []
        missing = (self.tmp / "absent" / "index.json").as_uri()
        self.assertIsNotNone(dfi_data.download(["38"], fresh, cache, previous_index=missing,
                                               api_url=api, log=logs.append))
        self.assertTrue(any("Index précédent inutilisable" in message for message in logs))

    def test_download_with_names_and_integrator_version_regeneration(self):
        zip38 = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE})
        api = self.make_api([resource("id38", "DFI (situation juillet 2026).zip", zip38.as_uri())])
        out, cache = self.tmp / "out", self.tmp / "cache"
        fetcher = lambda url: [{"code": "38001", "nom": "Abc"}] if "codeDepartement=38" in url else []
        index, _ = dfi_data.download(["38"], out, cache, api_url=api, log=lambda m: None, names_fetcher=fetcher)
        self.assertEqual(index["communes"]["38001"]["nom"], "Abc"); self.assertNotIn("nom", index["communes"]["38002"])
        self.assertEqual(index["integrateur"], dfi_data.__version__)
        quiet = dict(api_url=api, log=lambda m: None, names_fetcher=fetcher)
        self.assertIsNone(dfi_data.download(["38"], out, cache, **quiet), "même situation, même version : rien à faire")
        # un index publié par une version plus ancienne de l'intégrateur (sans noms) est régénéré
        old = json.loads((out / "index.json").read_text()); old["integrateur"] = "0.1.0"
        (out / "index.json").write_text(json.dumps(old))
        again = dfi_data.download(["38"], out, cache, **quiet)
        self.assertIsNotNone(again); self.assertEqual(again[0]["integrateur"], dfi_data.__version__)
        # service des noms indisponible : on garde les noms de l'index précédent
        def down(url): raise dfi_data.DownloadError("hors ligne")
        kept, _ = dfi_data.download(["38"], out, cache, force=True, api_url=api, log=lambda m: None, names_fetcher=down)
        self.assertEqual(kept["communes"]["38001"]["nom"], "Abc")
        # --no-names : aucune requête
        calls = []
        dfi_data.download(["38"], out, cache, force=True, api_url=api, log=lambda m: None, fetch_names=False, names_fetcher=lambda u: calls.append(u) or [])
        self.assertEqual(calls, [])

    def test_all_departments_converted_one_file_at_a_time(self):
        other = SAMPLE.replace("380;", "690;")
        zip_a = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE, "dfiano-dep2A0-02072026.txt": SAMPLE.replace("380;", "2A0;")})
        zip_b = self.make_zip("b.zip", {"dfiano-dep690-01072026.txt": other, "dfiano-dep976-01072026.txt": SAMPLE.replace("380;", "976;001;")[:0] + SAMPLE.replace("380;001;", "976;001;").replace("380;002;", "976;002;").replace("380;003;", "976;003;")})
        api = self.make_api([resource("a", "DFI (situation juillet 2026) - A.zip", zip_a.as_uri()), resource("b", "DFI (situation juillet 2026) - B.zip", zip_b.as_uri())])
        out, cache = self.tmp / "out", self.tmp / "cache"
        index, _ = dfi_data.download(["all"], out, cache, api_url=api, log=lambda m: None)
        self.assertEqual(index["departements"], ["all"])
        self.assertTrue({"38001", "69001", "2A001", "97001"} <= set(index["communes"]), sorted(index["communes"]))
        self.assertIsNone(dfi_data.download(["all"], out, cache, api_url=api, log=lambda m: None))
        # un périmètre explicite est un autre périmètre
        self.assertIsNotNone(dfi_data.download(["38"], out, cache, api_url=api, log=lambda m: None))

    def test_iter_extracted_deletes_each_file_after_use(self):
        zip_a = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE, "dfiano-dep690-01072026.txt": SAMPLE, "dossier/x.txt": "ignoré"})
        members = dfi_data.list_members([zip_a], None)
        self.assertEqual(sorted(members), ["380", "690"], "le motif exclut les chemins et les autres fichiers")
        work = self.tmp / "work"; work.mkdir()
        seen = []
        for path in dfi_data.iter_extracted(members, work):
            seen.append(path.name); self.assertTrue(path.exists()); self.assertEqual(len(list(work.iterdir())), 1, "un seul fichier à la fois")
        self.assertEqual(seen, ["dfiano-dep380-01072026.txt", "dfiano-dep690-01072026.txt"]); self.assertEqual(list(work.iterdir()), [])
        with self.assertRaises(dfi_data.DownloadError):
            dfi_data.list_members([zip_a, self.make_zip("b.zip", {"dfiano-dep380-02072026.txt": SAMPLE})], None)
        self.assertEqual(sorted(dfi_data.list_members([zip_a], {"690"})), ["690"])

    def test_exit_code_when_up_to_date(self):
        zip38 = self.make_zip("a.zip", {"dfiano-dep380-01072026.txt": SAMPLE})
        api = self.make_api([resource("id38", "DFI (situation juillet 2026).zip", zip38.as_uri())])
        out, cache = self.tmp / "out", self.tmp / "cache"
        args = ["download", "--departments", "38", "--output", str(out), "--cache", str(cache), "--api-url", api]
        with unittest.mock.patch("sys.stdout"):
            self.assertEqual(dfi_data.main(args), 0)
            self.assertEqual(dfi_data.main(args), dfi_data.EXIT_UP_TO_DATE)
            self.assertEqual(dfi_data.main(args + ["--force"]), 0)

    def test_default_cache_follows_xdg(self):
        with unittest.mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "/xdg"}):
            self.assertEqual(dfi_data.default_cache(), Path("/xdg/integrator-dfi"))
        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(dfi_data.default_cache(), Path.home() / ".cache" / "integrator-dfi")


if __name__ == "__main__":
    unittest.main()
