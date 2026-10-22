#!/usr/bin/env python3
"""
Tests de la lecture du fichier promo (PROMOS.xlsx) utilisé pour la commande
LGV du samedi : les produits en promo la semaine en cours ou la suivante sont
commandés à 3×VMS au lieu de 2×VMS.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs


def _ecrire_promos(chemin, lignes):
    """Écrit un PROMOS.xlsx au format du vrai fichier : colonnes nommées puis
    le thème "SXX ..." en colonne J sur la 1re ligne de chaque bloc."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "PROMOS"
    ws.append(['Gencod', 'Libellé étiquette', 'VMS', 'Thème promo', 'Qté vendues tt',
               'VMS ventes', 'Coeff', 'Prédiction ventes'])
    for gencod, theme in lignes:
        ws.append([gencod, 'LIBELLE', 1.0, '2EME -50%', 2, 1, 1, None, None, theme])
    wb.save(chemin)


class TestSemainesThemePromo(unittest.TestCase):
    def test_semaine_simple(self):
        self.assertEqual(cs._semaines_theme_promo("S43 TRAFIC HALLOWEEN"), {43})

    def test_bloc_sur_deux_semaines(self):
        self.assertEqual(cs._semaines_theme_promo("S12 TRAFIC S12/13"), {12, 13})
        self.assertEqual(cs._semaines_theme_promo("S33 TRAFIC S33/S34"), {33, 34})

    def test_pas_un_theme(self):
        self.assertEqual(cs._semaines_theme_promo(""), set())
        self.assertEqual(cs._semaines_theme_promo("R"), set())
        self.assertEqual(cs._semaines_theme_promo("2EME -50%"), set())


class TestNormaliserGencod(unittest.TestCase):
    def test_notation_scientifique(self):
        self.assertEqual(cs._normaliser_gencod("8.410076610737E12"), "8410076610737")

    def test_ean8_complete_comme_le_stock(self):
        self.assertEqual(cs._normaliser_gencod("80861263"), "0000080861263")

    def test_entete_ignoree(self):
        self.assertIsNone(cs._normaliser_gencod("Gencod"))


class TestLireGencodsPromo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chemin = os.path.join(self.tmp.name, "PROMOS.xlsx")
        _ecrire_promos(self.chemin, [
            ("3017620421006", "S42 TRAFIC MDD 2"),
            ("3057640257858", None),
            ("3265479568001", "S43 TRAFIC HALLOWEEN"),
            (3124480200433, None),             # gencod stocké en nombre
            ("3254381055501", "S44 GROS VOLUMES 2"),
            ("80861263", None),                # EAN-8
            ("3256220291897", "S45 TRAFIC"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_semaine_en_cours_et_suivante(self):
        self.assertEqual(cs.lire_gencods_promo(self.chemin, (43, 44)),
                         {"3265479568001", "3124480200433", "3254381055501", "0000080861263"})

    def test_semaines_hors_fenetre_exclues(self):
        promos = cs.lire_gencods_promo(self.chemin, (43, 44))
        self.assertNotIn("3017620421006", promos)   # S42 : passée
        self.assertNotIn("3256220291897", promos)   # S45 : trop loin

    def test_aucune_promo(self):
        self.assertEqual(cs.lire_gencods_promo(self.chemin, (50, 51)), set())


if __name__ == "__main__":
    unittest.main()
