#!/usr/bin/env python3
"""
Tests de la création du classeur CA DRIVE de l'année suivante : calendrier
(fériés, semaines ISO, mois des semaines) et formules SOMME d'ÉVOLUTION.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import creer_ca_drive_annee as cc


class TestCalendrier(unittest.TestCase):
    def test_feries_2027(self):
        f = cc.jours_feries(2027)
        self.assertIn(date(2027, 3, 29), f)   # lundi de Pâques
        self.assertIn(date(2027, 5, 6), f)    # Ascension
        self.assertIn(date(2027, 5, 17), f)   # lundi de Pentecôte

    def test_paques(self):
        self.assertEqual(cc._paques(2026), date(2026, 4, 5))
        self.assertEqual(cc._paques(2027), date(2027, 3, 28))

    def test_drive_ouvert_le_8_mai(self):
        self.assertFalse(cc.drive_ferme(date(2027, 5, 8)))
        self.assertTrue(cc.drive_ferme(date(2027, 5, 1)))

    def test_magasin_ouvert_ascension(self):
        self.assertFalse(cc.magasin_ferme(date(2027, 5, 6)))
        self.assertTrue(cc.magasin_ferme(date(2027, 3, 29)))

    def test_semaines_iso(self):
        self.assertEqual(cc.nb_semaines_iso(2026), 53)
        self.assertEqual(cc.nb_semaines_iso(2027), 52)

    def test_mois_semaine_jeudi(self):
        # S 13 2027 : 29 mars → 4 avril, jeudi 1er avril.
        self.assertEqual(cc.mois_semaine(2027, 13), 4)
        self.assertEqual(cc.mois_semaine(2027, 52), 12)


class TestSommeJours(unittest.TestCase):
    def test_semaines_completes_regroupees(self):
        cellules = [("RÉALISATION", r, c) for r in (7, 8, 9, 10) for c in "BCDEFG"]
        self.assertEqual(cc.somme_jours(cellules), "=SUM('RÉALISATION'!B7:G10)")

    def test_debut_et_fin_de_mois(self):
        cellules = ([("RÉALISATION", 11, c) for c in "DEFG"]
                    + [("RÉALISATION", r, c) for r in (12, 13) for c in "BCDEFG"]
                    + [("RÉALISATION", 14, "B")])
        self.assertEqual(
            cc.somme_jours(cellules),
            "=SUM('RÉALISATION'!D11:G11,'RÉALISATION'!B12:G13,'RÉALISATION'!B14)")

    def test_deux_onglets(self):
        cellules = [("RÉALISATION N-1", 55, "G"), ("RÉALISATION", 3, "B")]
        self.assertEqual(cc.somme_jours(cellules),
                         "=SUM('RÉALISATION N-1'!G55,'RÉALISATION'!B3)")


if __name__ == "__main__":
    unittest.main()
