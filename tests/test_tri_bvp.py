#!/usr/bin/env python3
"""
Tests du tri de la page BVP (lettre C) par categorie : Boulangerie, puis
Viennoiserie, puis Patisserie (cf. _categorie_bvp dans anticipation_commandes.py).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anticipation_commandes as ac

BOULANGERIE, VIENNOISERIE, PATISSERIE, AUTRE = 0, 1, 2, 3


class TestCategorieBvp(unittest.TestCase):
    def test_nomenclature_020518_seule_est_boulangerie(self):
        nomenclatures = {"0000000000001": "020518000000000000"}
        self.assertEqual(
            ac._categorie_bvp("Produit sans mot cle", "0000000000001", nomenclatures),
            BOULANGERIE)

    def test_mot_pain_est_boulangerie(self):
        self.assertEqual(ac._categorie_bvp("Pain blanc moulé, 1 pièce, 400g", "1", {}),
                          BOULANGERIE)

    def test_mot_baguette_est_boulangerie(self):
        self.assertEqual(ac._categorie_bvp("Baguette au froment, 1 pièce, 250g", "1", {}),
                          BOULANGERIE)

    def test_mot_dejeunette_est_boulangerie(self):
        self.assertEqual(ac._categorie_bvp("Déjeunette, 4 pièces, 500g", "1", {}),
                          BOULANGERIE)

    def test_pain_au_chocolat_exclu_meme_avec_nomenclature_boulangerie(self):
        nomenclatures = {"0000000000001": "020518000000000000"}
        self.assertNotEqual(
            ac._categorie_bvp("U Pain au chocolat pur beurre, 2 pièces, 140g",
                              "0000000000001", nomenclatures),
            BOULANGERIE)

    def test_pain_aux_raisins_exclu_meme_avec_nomenclature_boulangerie(self):
        nomenclatures = {"0000000000001": "020518000000000000"}
        self.assertNotEqual(
            ac._categorie_bvp("U Pain aux raisins pur beurre 2 pièces",
                              "0000000000001", nomenclatures),
            BOULANGERIE)

    def test_pains_chocolat_sans_au_exclu_meme_avec_nomenclature_boulangerie(self):
        # Libelle reel rencontre sur un bon de commande : "au" est absent.
        nomenclatures = {"0000000000001": "020518000000000000"}
        self.assertNotEqual(
            ac._categorie_bvp("U SAVEURS 2 croissants + 2 pains chocolat pur beurre, 260g",
                              "0000000000001", nomenclatures),
            BOULANGERIE)

    def test_pain_au_chocolat_avec_nomenclature_viennoiserie(self):
        nomenclatures = {"0000000000001": "020519000000000000"}
        self.assertEqual(
            ac._categorie_bvp("U Pain au chocolat pur beurre, 2 pièces, 140g",
                              "0000000000001", nomenclatures),
            VIENNOISERIE)

    def test_nomenclature_020519_est_viennoiserie(self):
        nomenclatures = {"0000000000001": "020519000000000000"}
        self.assertEqual(
            ac._categorie_bvp("U Croissant pur beurre, Sélection 5 pièces, 225g",
                              "0000000000001", nomenclatures),
            VIENNOISERIE)

    def test_nomenclature_020520_est_patisserie(self):
        nomenclatures = {"0000000000001": "020520000000000000"}
        self.assertEqual(
            ac._categorie_bvp("U Tarte aux pommes, 6 parts, 595g",
                              "0000000000001", nomenclatures),
            PATISSERIE)

    def test_sans_nomenclature_ni_mot_cle_reste_non_classe(self):
        self.assertEqual(ac._categorie_bvp("Jouet sans rapport", "1", {}), AUTRE)


class TestTriPageBvp(unittest.TestCase):
    """Le tri des groupes de la page BVP place d'abord la Boulangerie, puis
    la Viennoiserie, puis la Patisserie (cf. _elements_rayon dans
    _generer_pdf_rayons, pour la lettre C uniquement)."""

    def test_ordre_par_categorie_devant_heure_et_gencod(self):
        nomenclatures = {
            "0000000000002": "020519000000000000",  # croissant -> viennoiserie
            "0000000000003": "020520000000000000",  # tarte -> patisserie
        }
        groupes = [
            {"gencod": "0000000000003", "libelle": "Tarte aux pommes",
             "lignes": [("CDE1", "1", "08:00")], "adresse": "A"},
            {"gencod": "0000000000002", "libelle": "Croissant pur beurre",
             "lignes": [("CDE2", "1", "07:00")], "adresse": "A"},
            {"gencod": "0000000000001", "libelle": "Baguette au froment",
             "lignes": [("CDE3", "1", "09:00")], "adresse": "A"},
        ]
        groupes.sort(key=lambda g: (ac._categorie_bvp(g["libelle"], g["gencod"], nomenclatures),
                                     g["lignes"][0][2], g["gencod"]))
        self.assertEqual([g["libelle"] for g in groupes],
                          ["Baguette au froment", "Croissant pur beurre", "Tarte aux pommes"])


if __name__ == "__main__":
    unittest.main()
