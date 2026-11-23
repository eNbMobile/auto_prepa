#!/usr/bin/env python3
"""Tests du stock déposé pour l'app MobUDrive (stock_mobudrive.py).

Lancement : python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stock_mobudrive as sm


class FauxDrive:
    def __init__(self, noms):
        self.fichiers = {f"id{i}": n for i, n in enumerate(noms)}
        self.crees, self.maj, self.supprimes = [], [], []

    def files(self):
        return self

    def list(self, **_):
        r = mock.Mock()
        r.execute.return_value = {"files": [{"id": i, "name": n} for i, n in self.fichiers.items()]}
        return r

    def create(self, body, **_):
        self.crees.append(body["name"])
        return mock.Mock()

    def update(self, fileId, **_):
        self.maj.append(self.fichiers[fileId])
        return mock.Mock()

    def delete(self, fileId):
        self.supprimes.append(self.fichiers[fileId])
        return mock.Mock()


class TestStockMobUDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(sm.cs, "WORK_DIR", self.tmp),
                        mock.patch.object(sm.cs, "DRIVE_BONS_FOLDER_ID", "bons"),
                        mock.patch("googleapiclient.http.MediaFileUpload")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _publier(self, noms, jour, moment):
        drive = FauxDrive(noms)
        with mock.patch.object(sm.cs, "_get_drive_service", return_value=drive):
            ok = sm.publier({"3000000000001": 4.0}, {"3000000000001": "Lib"}, jour, moment)
        return ok, drive

    def test_stock_soir(self):
        self.assertEqual(sm.stock_soir({"1": 10.0, "2": 3.0}, {"1": 4, "9": 2}),
                         {"1": 6.0, "2": 3.0})

    def test_csv(self):
        chemin = sm.ecrire_csv({"2": 1.5, "1": 3.0}, {"1": "A"}, os.path.join(self.tmp, "s.csv"))
        with open(chemin, "rb") as f:
            self.assertEqual(f.read(), "gencod;stock;libelle\n1;3;A\n2;1.5;\n".encode())

    def test_matin_remplace_soir_veille(self):
        ok, drive = self._publier(["stock_22_11_2026_soir.csv", "bon_x.txt"], date(2026, 11, 23), "matin")
        self.assertTrue(ok)
        self.assertEqual(drive.crees, ["stock_23_11_2026_matin.csv"])
        self.assertEqual(drive.supprimes, ["stock_22_11_2026_soir.csv"])

    def test_soir_remplace_matin_du_jour(self):
        ok, drive = self._publier(["stock_23_11_2026_matin.csv"], date(2026, 11, 23), "soir")
        self.assertTrue(ok)
        self.assertEqual(drive.supprimes, ["stock_23_11_2026_matin.csv"])

    def test_meme_fichier_mis_a_jour(self):
        ok, drive = self._publier(["stock_23_11_2026_matin.csv"], date(2026, 11, 23), "matin")
        self.assertEqual((drive.maj, drive.crees, drive.supprimes),
                         (["stock_23_11_2026_matin.csv"], [], []))

    def test_plus_recent_conserve(self):
        ok, drive = self._publier(["stock_24_11_2026_matin.csv"], date(2026, 11, 23), "soir")
        self.assertFalse(ok)
        self.assertEqual((drive.crees, drive.supprimes), ([], []))


if __name__ == "__main__":
    unittest.main()
