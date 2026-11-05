"""Zonage immédiat (R/S) des fruits/légumes nouveaux pendant le run
d'auto_prepa : copie locale de gencod_nomenclatures.csv seulement."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arbitrage_fruits_legumes as afl
import auto_prepa as ap

CHEMIN = ("M2-KK-9-1;FRUITS;R\r\n023034000000000000;FRUITS;R\r\n"
          "023035000000000000;LEGUMES;S\r\n")
INFOS = "MARDI 13/10/2026 - 10h30-11h00,56209742,Retrait,Paiement en ligne,M. X Y,Pas de sacs"


def ligne(gencod, libelle, adresse, nom):
    return (f"{gencod};{libelle};2.50;0.00;1;OUI;0;0;N;{INFOS};"
            f"{adresse};{nom};12;00/00/0000\n")


class TestZonesImmediates(unittest.TestCase):
    def test_fruit_legume_doute_et_connu(self):
        produits = [
            ("3700389403054", "Noix de coco - La pièce, COTE D'IVOIRE", ""),
            ("3236021191152", "Oignon jaune, filet 5kg, FRANCE", ""),
            ("3256220929707", "U BIO Brocolis bio U 540g", ""),        # pays absent
            ("3590920984438", "Pomme Gala - Barquette 6 fruits, FRANCE", ""),  # connue
        ]
        zones = afl.zones_immediates(produits, {"3590920984438"}, CHEMIN)
        self.assertEqual(zones, [
            ("3700389403054", "Noix de coco - La pièce, COTE D'IVOIRE", "023034000000000000"),
            ("3236021191152", "Oignon jaune, filet 5kg, FRANCE", "023035000000000000"),
        ])


class TestZonerBonLocal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ancien = ap.WORK_DIR
        ap.WORK_DIR = self.dir
        ap._NOMENCLATURES_LOCALES = None
        with open(os.path.join(self.dir, "chemin_prepa_ramasse.csv"), "w", newline="") as f:
            f.write(CHEMIN)
        self.nomencl = os.path.join(self.dir, "gencod_nomenclatures.csv")
        with open(self.nomencl, "wb") as f:
            f.write(b"3590920984438;023034000000000000\r\n")
        self.bon = os.path.join(self.dir, "bon_prepa.txt")
        with open(self.bon, "w", encoding="utf-8") as f:
            f.write("M,1,4,6,0,54.20,10h05\n")
            f.write(ligne("3700389403054", "Noix de coco - La pièce, COTE D'IVOIRE",
                          "M1-ZZ-0-0", "ADRESSE INCONNUE;W"))
            f.write(ligne("3590920984438", "Pomme Gala - Barquette 6 fruits, FRANCE",
                          "M1-ZZ-0-0", "ADRESSE INCONNUE;W"))
            f.write(ligne("3168930001911", "BUGLES CACAHUETE 85G",
                          "M1-ZZ-0-0", "ADRESSE INCONNUE;W"))

    def tearDown(self):
        ap.WORK_DIR = self.ancien
        ap._NOMENCLATURES_LOCALES = None

    def test_ajout_local_en_crlf_une_seule_fois(self):
        zones = ap._zoner_fruits_legumes(self.bon)
        self.assertEqual([g for g, _, _ in zones], ["3700389403054"])
        self.assertEqual(ap._zoner_fruits_legumes(self.bon), [])  # déjà ajouté
        with open(self.nomencl, "rb") as f:
            self.assertEqual(f.read(), b"3590920984438;023034000000000000\r\n"
                                       b"3700389403054;023034000000000000\r\n")

    def test_aucun_fruit_legume_rien_ne_change(self):
        with open(self.bon, "w", encoding="utf-8") as f:
            f.write("M,1,4,6,0,54.20,10h05\n")
            f.write(ligne("3168930001911", "BUGLES CACAHUETE 85G",
                          "M1-ZZ-0-0", "ADRESSE INCONNUE;W"))
        self.assertEqual(ap._zoner_fruits_legumes(self.bon), [])
        self.assertIsNone(ap._NOMENCLATURES_LOCALES)  # CSV non lu

    def test_erreur_ne_leve_pas(self):
        os.remove(self.nomencl)
        self.assertEqual(ap._zoner_fruits_legumes(self.bon), [])


if __name__ == "__main__":
    unittest.main()
