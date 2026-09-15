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
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class TestGenererPdfDiff(unittest.TestCase):

    def test_aucune_difference_aucun_pdf(self):
        self.assertIsNone(ds.generer_pdf_diff([], None, None))


if __name__ == "__main__":
    unittest.main()
