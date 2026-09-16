#!/usr/bin/env python3
"""
Tests de la différence de stocks J-1 / J (diff_stocks.py).

Contrairement au contrôle de stocks, aucune vente ni stock théorique n'entre
dans le calcul : seules comptent la valeur de départ, la valeur d'arrivée et
leur écart, et le PDF ne doit contenir que les lignes qui diffèrent.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs
import diff_stocks as ds


class TestComparerStocks(unittest.TestCase):

    def test_seules_les_differences_sont_retenues(self):
        stock_j1 = {"1": 10.0, "2": 5.0, "3": 0.0}
        stock_j  = {"1": 10.0, "2": 3.0, "3": 4.0}
        diffs, orphelins, communs = ds.comparer_stocks(stock_j1, stock_j)
        self.assertEqual(communs, 3)
        self.assertEqual(orphelins, [])
        self.assertEqual([(r[0], r[1], r[4], r[5]) for r in diffs],
                         [("3", 0.0, 4.0, 4.0), ("2", 5.0, 3.0, -2.0)])

    def test_ventes_et_theorique_restent_nuls(self):
        diffs, _, _ = ds.comparer_stocks({"1": 8.0}, {"1": 6.0})
        gencod, s_j1, ventes, theo, s_j, ecart, statut, lib = diffs[0]
        self.assertEqual((ventes, theo), (0.0, 0.0))
        self.assertEqual((s_j1, s_j, ecart), (8.0, 6.0, -2.0))
        self.assertEqual(statut, "DIFF")

    def test_gencods_absents_dun_export_sont_orphelins(self):
        stock_j1 = {"1": 10.0, "2": 4.0}
        stock_j  = {"1": 12.0, "3": 7.0}
        diffs, orphelins, communs = ds.comparer_stocks(stock_j1, stock_j)
        self.assertEqual(communs, 1)
        self.assertEqual([r[0] for r in diffs], ["1"])
        self.assertEqual([(r[0], r[6]) for r in orphelins],
                         [("2", "ABSENT_J"), ("3", "ABSENT_J-1")])

    def test_perimetre_gencods_et_libelles(self):
        stock_j1 = {"1": 10.0, "2": 4.0}
        stock_j  = {"1": 12.0, "2": 9.0}
        diffs, _, communs = ds.comparer_stocks(stock_j1, stock_j, gencods={"1"},
                                               libelles={"1": "PRODUIT A"})
        self.assertEqual(communs, 1)
        self.assertEqual([(r[0], r[7]) for r in diffs], [("1", "PRODUIT A")])

    def test_stock_a_zero_des_deux_cotes_ignore(self):
        diffs, _, communs = ds.comparer_stocks({"1": 0.0}, {"1": 0.0})
        self.assertEqual((diffs, communs), ([], 1))


class TestChercherLocal(unittest.TestCase):
    """Les exports déposés dans le dépôt doivent être trouvés sans passer par
    Drive : c'est le mode d'emploi du workflow (on dépose j1.xlsx et j.xlsx
    dans le dépôt, on lance le workflow)."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _creer(self, chemin):
        os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
        open(chemin, "w").close()

    def test_racine_du_depot(self):
        self._creer("j.xlsx")
        self.assertEqual(ds.chercher_local("j.xlsx"), "j.xlsx")

    def test_sous_dossier_stocks(self):
        self._creer("stocks/j1.xlsx")
        self.assertEqual(ds.chercher_local("j1.xlsx"), os.path.join("stocks", "j1.xlsx"))

    def test_chemin_explicite_prioritaire(self):
        self._creer("j.xlsx")
        self._creer("autre/export.xlsx")
        self.assertEqual(ds.chercher_local("j.xlsx", "autre/export.xlsx"),
                         "autre/export.xlsx")

    def test_chemin_explicite_absent_retombe_sur_le_depot(self):
        self._creer("j.xlsx")
        self.assertEqual(ds.chercher_local("j.xlsx", "inexistant.xlsx"), "j.xlsx")

    def test_absent_partout(self):
        self.assertIsNone(ds.chercher_local("j.xlsx"))


class TestGenererPdfDiff(unittest.TestCase):

    def test_aucune_difference_aucun_pdf(self):
        self.assertIsNone(ds.generer_pdf_diff([], None, None))


if __name__ == "__main__":
    unittest.main()


class _FakeFiles:
    """Drive simulé : {folder_id: {nom: [(file_id, modifiedTime)]}}."""

    def __init__(self, arbo, dossiers, contenus):
        self.arbo, self.dossiers, self.contenus = arbo, dossiers, contenus
        self.requetes = []

    def list(self, q=None, fields=None, orderBy=None, pageSize=None):
        self.requetes.append(q)
        if "mimeType='application/vnd.google-apps.folder'" in q:
            nom = q.split("name='", 1)[1].split("'", 1)[0]
            ids = [i for i, n in self.dossiers.items() if n == nom]
            return _FakeExec({"files": [{"id": ids[0]}] if ids else []})
        nom = q.split("name='", 1)[1].split("'", 1)[0]
        parent = q.split("and '", 1)[1].split("' in parents", 1)[0] if "in parents" in q else None
        trouves = []
        for folder, fichiers in self.arbo.items():
            if parent and folder != parent:
                continue
            for fid, modifie in fichiers.get(nom, []):
                trouves.append({"id": fid, "parents": [folder], "modifiedTime": modifie})
        trouves.sort(key=lambda f: f["modifiedTime"], reverse=True)
        return _FakeExec({"files": trouves})

    def get(self, fileId=None, fields=None):
        return _FakeExec({"name": self.dossiers.get(fileId, "")})

    def get_media(self, fileId=None):
        return self.contenus.get(fileId, b"")


class _FakeExec:
    def __init__(self, valeur):
        self._valeur = valeur

    def execute(self):
        return self._valeur


class _FakeService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


class TestTelechargerDepuisDrive(unittest.TestCase):
    """Reproduit la situation réelle : les exports sont déposés dans le dossier
    Drive "GITHUB", alors que le dossier du contrôle de stocks ne contient que
    son propre j1.xlsx."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.dossiers = {"depot": "GITHUB", "controle": "Contrôle_Stocks",
                         "ailleurs": "Mon Drive"}
        self.arbo = {
            "depot":    {"j.xlsx": [("f_j_depot", "2026-09-15T20:07:00Z")],
                         "j1.xlsx": [("f_j1_depot", "2026-09-15T20:07:00Z")]},
            "controle": {"j1.xlsx": [("f_j1_controle", "2026-09-15T17:09:00Z")]},
            "ailleurs": {"j.xlsx": [("f_j_vieux", "2026-05-12T14:00:00Z")]},
        }
        self.contenus = {"f_j_depot": b"depot", "f_j1_depot": b"depot1",
                         "f_j1_controle": b"controle1", "f_j_vieux": b"vieux"}
        self.fake = _FakeFiles(self.arbo, self.dossiers, self.contenus)
        self._svc = cs._get_drive_service
        self._dl = sys.modules.get("googleapiclient.http")
        cs._get_drive_service = lambda: _FakeService(self.fake)
        cs.DRIVE_CONTROLE_FOLDER_ID = "controle"
        faux_module = types.ModuleType("googleapiclient.http")
        faux_module.MediaIoBaseDownload = _FakeDownload
        sys.modules["googleapiclient.http"] = faux_module
        sys.modules.setdefault("googleapiclient", types.ModuleType("googleapiclient"))

    def tearDown(self):
        cs._get_drive_service = self._svc
        if self._dl is None:
            sys.modules.pop("googleapiclient.http", None)
        else:
            sys.modules["googleapiclient.http"] = self._dl
        os.chdir(self._cwd)
        self._tmp.cleanup()

    @staticmethod
    def _lire(chemin):
        with open(chemin, "rb") as f:
            return f.read()

    def test_j_pris_dans_le_dossier_de_depot(self):
        self.assertEqual(ds.telecharger_depuis_drive("j.xlsx", "j.xlsx"), "j.xlsx")
        self.assertEqual(self._lire("j.xlsx"), b"depot")

    def test_j1_du_depot_prioritaire_sur_celui_du_controle(self):
        ds.telecharger_depuis_drive("j1.xlsx", "j1.xlsx")
        self.assertEqual(self._lire("j1.xlsx"), b"depot1")

    def test_repli_sur_le_controle_si_pas_de_dossier_de_depot(self):
        self.dossiers.pop("depot")
        self.arbo.pop("depot")
        ds.telecharger_depuis_drive("j1.xlsx", "j1.xlsx")
        self.assertEqual(self._lire("j1.xlsx"), b"controle1")

    def test_dernier_recours_ailleurs_sur_le_drive(self):
        self.dossiers.pop("depot")
        self.arbo.pop("depot")
        ds.telecharger_depuis_drive("j.xlsx", "j.xlsx")
        self.assertEqual(self._lire("j.xlsx"), b"vieux")

    def test_absent_partout(self):
        self.arbo.clear()
        self.assertIsNone(ds.telecharger_depuis_drive("j.xlsx", "j.xlsx"))


class _FakeDownload:
    def __init__(self, buf, contenu):
        self._buf, self._contenu = buf, contenu

    def next_chunk(self):
        self._buf.write(self._contenu)
        return None, True
