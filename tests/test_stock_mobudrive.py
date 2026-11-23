#!/usr/bin/env python3
"""Tests du stock déposé pour l'app MobUDrive (stock_mobudrive.py).

Lancement : python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stock_mobudrive as sm


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

    def update(self, fileId, **_):
        self.maj.append(self.fichiers[fileId])
        return mock.Mock()


class TestStockMobUDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(sm.cs, "DRIVE_BONS_FOLDER_ID", "bons"),
                        mock.patch("googleapiclient.http.MediaFileUpload")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _publier(self, noms):
        drive = FauxDrive(noms)
        with mock.patch.object(sm.cs, "_get_drive_service", return_value=drive):
            self.assertTrue(sm.publier("j.xlsx"))
        return drive

    def test_cree_stock_xlsx(self):
        drive = self._publier(["bon_x.txt"])
        self.assertEqual((drive.crees, drive.maj), (["stock.xlsx"], []))

    def test_ecrase_stock_xlsx(self):
        drive = self._publier(["stock.xlsx", "bon_x.txt"])
        self.assertEqual((drive.crees, drive.maj), ([], ["stock.xlsx"]))

    def test_stock_soir(self):
        matin = os.path.join(self.tmp, "matin.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Gencod", "Libellé", "Stock UC", "Classeur"])
        ws.append(["3000000000001", "A", 10, "DRIVE X"])
        ws.append([3000000000002, "B", "5,5", "DRIVE X"])
        ws.append(["3000000000003", "C", 2, "DRIVE X"])
        wb.save(matin)
        sortie = sm.ecrire_stock_soir(matin, {"3000000000001": 4, "3000000000002": 1,
                                              "3000000000009": 3},
                                      os.path.join(self.tmp, "soir.xlsx"))
        stock, libelles, classeurs = sm.cs.lire_stock(sortie)
        self.assertEqual(stock, {"3000000000001": 6.0, "3000000000002": 4.5,
                                 "3000000000003": 2.0})
        self.assertEqual(libelles["3000000000002"], "B")


if __name__ == "__main__":
    unittest.main()
