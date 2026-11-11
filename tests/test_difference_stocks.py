#!/usr/bin/env python3
"""Tests de la différence de stocks matin → J1 (difference_stocks.py).

Lancement : python3 -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import difference_stocks as ds


class TestCalculerDifferences(unittest.TestCase):
    def test_seules_les_differences_r1_sont_retenues(self):
        matin = {"1": 10.0, "2": 5.0, "3": 0.0, "4": 7.0}
        j1 = {"1": 10.0, "2": 8.0, "4": 1.0, "5": 3.0}
        rows = ds.calculer_differences(matin, j1, {"1", "2", "3", "4", "6"}, {"2": "Lib 2"})
        self.assertEqual([(r[0], r[1], r[4], r[5]) for r in rows],
                         [("4", 7.0, 1.0, -6.0), ("2", 5.0, 8.0, 3.0)])
        self.assertEqual(rows[1][7], "Lib 2")

    def test_aucune_difference(self):
        self.assertEqual(ds.calculer_differences({"1": 2.0}, {"1": 2.0}, {"1"}, {}), [])


class TestJoursActifs(unittest.TestCase):
    def _lancer(self, date_txt):
        with mock.patch.object(sys, "argv", ["difference_stocks.py", "--date", date_txt]), \
             mock.patch.object(ds.cs, "_charger_config") as charger:
            ds.main()
        return charger.called

    def test_ignore_hors_mardi_mercredi(self):
        self.assertFalse(self._lancer("12/11/2026"))  # jeudi
        self.assertFalse(self._lancer("09/11/2026"))  # lundi

    def test_pas_de_mail_sans_difference(self):
        with mock.patch.object(sys, "argv", ["difference_stocks.py", "--date", "10/11/2026"]), \
             mock.patch.object(ds.cs, "_charger_config"), \
             mock.patch.object(ds.cs, "telecharger_fichier_archive", return_value="m.xlsx"), \
             mock.patch.object(ds.cs, "telecharger_fichier_controle", return_value="j1.xlsx"), \
             mock.patch.object(ds.cs, "lire_stock", return_value=({"1": 2.0}, {}, {})), \
             mock.patch.object(ds.cs, "charger_gencods_r1", return_value={"1"}), \
             mock.patch.object(ds.cs, "charger_libelles_dict", return_value={}), \
             mock.patch.object(ds, "envoyer_email") as envoi:
            ds.main()
        envoi.assert_not_called()


if __name__ == "__main__":
    unittest.main()
