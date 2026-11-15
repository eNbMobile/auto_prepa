#!/usr/bin/env python3
"""Tests des stocks insuffisants prévisionnels (calculer_stocks_insuffisants.py).

Lancement : python3 -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calculer_stocks_insuffisants as csi


class TestParserDates(unittest.TestCase):
    def test_plusieurs_dates_triees_sans_doublon(self):
        self.assertEqual(csi.parser_dates("17/11/2026, 16/11/2026;17/11/2026"),
                         [date(2026, 11, 16), date(2026, 11, 17)])

    def test_date_invalide_ou_vide(self):
        with self.assertRaises(ValueError):
            csi.parser_dates("16/11")
        with self.assertRaises(ValueError):
            csi.parser_dates("  ")


class TestCalcul(unittest.TestCase):
    def test_restant_apres_ventes_cumulees(self):
        stock = {"1": 4.0, "2": 5.0, "3": 0.0, "4": 1.0, "5": 1.0, "6": 0.0}
        classeurs = {"4": "** DRIVE PRODUIT A ENLEVER **", "5": "**DRIVE DÉLOTAGE**"}
        ventes = [{"1": 2, "2": 1}, {"1": 1, "7": 3}]
        rows = csi.calculer_stock_insuffisant(stock, classeurs, ventes,
                                              {"1", "2", "3", "4", "5", "7"}, {"1": "Lib 1"})
        self.assertEqual([(r[0], r[1], r[2], r[4]) for r in rows],
                         [("1", 4.0, 3, 1.0), ("3", 0.0, 0, 0.0)])
        self.assertEqual(rows[0][7], "Lib 1")

    def test_rupture_negative_conservee(self):
        rows = csi.calculer_stock_insuffisant({"1": 0.0}, {}, [{"1": 2}], None, {})
        self.assertEqual(rows[0][4], -2.0)


if __name__ == "__main__":
    unittest.main()
