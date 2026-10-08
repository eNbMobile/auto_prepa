#!/usr/bin/env python3
"""
Tests du cumul du contrôle de stocks sur une période
(cumul_controle_stocks.py).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cumul_controle_stocks as ccs


class TestCumulerPeriode(unittest.TestCase):
    """Deux jours fictifs : stocks et ventes fournis directement, sans Drive."""

    def setUp(self):
        # Jour 1 (01/01) : gencod "1" écart -3, gencod "2" OK.
        # Jour 2 (02/01) : gencod "1" écart +3 (s'annule sur la période),
        #                  gencod "2" toujours OK, gencod "3" écart +5 (un seul jour).
        self.stocks = {
            ("01_01_2026", "soir"):  {"1": 10.0, "2": 5.0},
            ("02_01_2026", "matin"): {"1": 7.0,  "2": 5.0},   # écart jour 1 : 1 → -3, 2 → 0
            ("02_01_2026", "soir"):  {"1": 7.0,  "2": 5.0, "3": 2.0},
            ("03_01_2026", "matin"): {"1": 10.0, "2": 5.0, "3": 7.0},  # jour 2 : 1 → +3, 3 → +5
        }
        self.ventes = {
            date(2026, 1, 1): ({}, {}),
            date(2026, 1, 2): ({}, {}),
        }

        def _fake_telecharger_fichier_archive(subfolder, nom, dest, root_id=None):
            # nom suit cs.nom_archive_stock : "stock_JJ_MM_AAAA_{matin,soir}.xlsx"
            parts = nom.removeprefix("stock_").removesuffix(".xlsx").rsplit("_", 1)
            jour_str, moment = parts[0], parts[1]
            cle = (jour_str, moment)
            if cle not in self.stocks:
                return None
            with open(dest, "w") as f:
                f.write("fake")
            return dest

        self.patchers = [
            mock.patch("controle_stocks.charger_gencods_r1", return_value=None),
            mock.patch("controle_stocks.charger_libelles_dict", return_value={}),
            mock.patch("controle_stocks.telecharger_fichier_archive",
                      side_effect=_fake_telecharger_fichier_archive),
            mock.patch("controle_stocks.generer_ventes",
                      side_effect=lambda d: self.ventes[d]),
        ]
        for p in self.patchers:
            p.start()

        # lire_stock : associe chaque chemin temporaire au bon stock via son
        # nom (encodé par _fake_telecharger_fichier_archive dans le contenu).
        originaux = dict(self.stocks)

        def _lire_stock(chemin, classeur_requis=True):
            # chemin = "_cumul_{soir,matin}_{AAAAMMJJ}.xlsx"
            base = os.path.basename(chemin).removesuffix(".xlsx").lstrip("_")
            _, moment, ymd = base.split("_")
            jour_str = f"{ymd[6:8]}_{ymd[4:6]}_{ymd[0:4]}"
            stock = originaux[(jour_str, moment)]
            return dict(stock), {}, {}

        self.patchers.append(mock.patch("controle_stocks.lire_stock", side_effect=_lire_stock))
        self.patchers[-1].start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_ecarts_additionnes_par_gencod_sur_la_periode(self):
        lignes, jours_ok, jours_ignores = ccs.cumuler_periode(
            date(2026, 1, 1), date(2026, 1, 2))
        self.assertEqual(jours_ok, 2)
        self.assertEqual(jours_ignores, [])
        resultat = {g: (nb_jours, ecart) for g, nb_jours, ecart, _ in lignes}
        # "1" a eu -3 puis +3 : il apparaît, même si le cumul net vaut 0.
        self.assertIn("1", resultat)
        self.assertEqual(resultat["1"], (2, 0.0))
        # "2" n'a jamais eu d'écart : absent du résultat.
        self.assertNotIn("2", resultat)
        # "3" n'a eu d'écart qu'un seul jour.
        self.assertEqual(resultat["3"], (1, 5.0))

    def test_jour_sans_archive_est_ignore(self):
        lignes, jours_ok, jours_ignores = ccs.cumuler_periode(
            date(2026, 1, 1), date(2026, 1, 3))
        self.assertEqual(jours_ok, 2)
        self.assertEqual(jours_ignores, [date(2026, 1, 3)])


if __name__ == "__main__":
    unittest.main()
