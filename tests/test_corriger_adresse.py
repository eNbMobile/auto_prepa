#!/usr/bin/env python3
"""
Tests de la correction manuelle d'une adresse dans gencod_adresses.csv.

Le 25/10/2026, le gencod 3256220223157 était adressé R1-TG-2 (élément
oublié) : l'adresse ne correspondait à aucune clé du chemin de préparation.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corriger_adresse as ca


class TestCorriger(unittest.TestCase):
    def test_adresse_remplacee_fins_de_ligne_conservees(self):
        contenu = "5449000283900;R1-TG-5-1\r\n3256220223157;R1-TG-2\r\n3254381055501;R1-TG-2-1\r\n"
        nouveau, anciennes = ca.corriger(contenu, "3256220223157", "R1-TG-2-1")
        self.assertEqual(anciennes, ["R1-TG-2"])
        self.assertEqual(nouveau, contenu.replace("R1-TG-2\r\n", "R1-TG-2-1\r\n", 1))

    def test_gencod_avec_zeros_de_tete(self):
        contenu = "0003256220223157;R1-TG-2\n"
        nouveau, anciennes = ca.corriger(contenu, "3256220223157", "R1-TG-2-1")
        self.assertEqual(anciennes, ["R1-TG-2"])
        self.assertEqual(nouveau, "0003256220223157;R1-TG-2-1\n")

    def test_gencod_absent_ajoute(self):
        nouveau, anciennes = ca.corriger("1;M2-AA-1-1", "3256220223157", "R1-TG-2-1")
        self.assertEqual(anciennes, [])
        self.assertEqual(nouveau, "1;M2-AA-1-1\n3256220223157;R1-TG-2-1\n")

    def test_gencod_absent_ajoute_en_crlf(self):
        # 04/11/2026 : 2892064000007 ajouté en LF dans un fichier CRLF ;
        # prepa_drive_degrade aurait lu M2-JJ-17-1 au lieu de M2-JJ-17-11.
        contenu = "1;M2-AA-1-1\r\n"
        nouveau, _ = ca.corriger(contenu, "2892064000007", "M2-JJ-17-11")
        self.assertEqual(nouveau, "1;M2-AA-1-1\r\n2892064000007;M2-JJ-17-11\r\n")

    def test_ligne_lf_remise_en_crlf(self):
        contenu = "1;M2-AA-1-1\r\n2892064000007;M2-JJ-17-11\n"
        nouveau, anciennes = ca.corriger(contenu, "2892064000007", "M2-JJ-17-11")
        self.assertEqual(anciennes, ["M2-JJ-17-11"])
        self.assertEqual(nouveau, "1;M2-AA-1-1\r\n2892064000007;M2-JJ-17-11\r\n")

    def test_format_adresse(self):
        self.assertTrue(ca.RE_ADRESSE.match("R1-TG-2-1"))
        self.assertFalse(ca.RE_ADRESSE.match("R1-TG-2"))


if __name__ == "__main__":
    unittest.main()
