#!/usr/bin/env python3
"""Tests du dépôt vms.xlsx pour l'app MobUDrive (controle_stocks.publier_vms_mobudrive).

Lancement : python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs


class FauxDrive:
    def __init__(self, noms):
        self.fichiers = {f"id{i}": n for i, n in enumerate(noms)}
        self.crees, self.maj = [], []

    def files(self):
        return self

    def list(self, q, **_):
        r = mock.Mock()
        r.execute.return_value = {"files": [{"id": i} for i, n in self.fichiers.items()
                                            if f"name='{n}'" in q]}
        return r

    def create(self, body, **_):
        self.crees.append(body["name"])
        return mock.Mock()

    def update(self, fileId, body=None, **kw):
        self.maj.append((self.fichiers[fileId], body, "media_body" in kw))
        return mock.Mock()


class TestVmsMobUDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(cs, "DRIVE_BONS_FOLDER_ID", "bons"),
                        mock.patch.object(cs, "WORK_DIR", self.tmp),
                        mock.patch("googleapiclient.http.MediaFileUpload")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _publier(self, noms, gencods, vms_map):
        drive = FauxDrive(noms)
        with mock.patch.object(cs, "_get_drive_service", return_value=drive):
            self.assertTrue(cs.publier_vms_mobudrive(gencods, vms_map))
        return drive

    def test_cree_vms_xlsx(self):
        drive = self._publier(["bon_x.txt"], ["3000000000001"], {"3000000000001": 2.5})
        self.assertEqual((drive.crees, drive.maj), (["vms.xlsx"], []))

    def test_ancien_vms_xlsx_a_la_corbeille(self):
        drive = self._publier(["vms.xlsx", "bon_x.txt"], ["3000000000001"], {"3000000000001": 2.5})
        self.assertEqual(drive.maj, [("vms.xlsx", {"trashed": True}, False)])
        self.assertEqual(drive.crees, ["vms.xlsx"])

    def test_contenu_gencod_point_virgule_vms(self):
        self._publier(["bon_x.txt"],
                      ["3000000000002", "3000000000001"],
                      {"3000000000001": 2.5, "3000000000002": 0.0})
        wb = openpyxl.load_workbook(os.path.join(self.tmp, "vms.xlsx"))
        lignes = [row[0].value for row in wb.active.iter_rows()]
        self.assertEqual(lignes, ["3000000000001;2.5", "3000000000002;0.0"])

    def test_gencod_absent_du_vms_map_a_zero(self):
        self._publier(["bon_x.txt"], ["3000000000009"], {})
        wb = openpyxl.load_workbook(os.path.join(self.tmp, "vms.xlsx"))
        lignes = [row[0].value for row in wb.active.iter_rows()]
        self.assertEqual(lignes, ["3000000000009;0.0"])


if __name__ == "__main__":
    unittest.main()
