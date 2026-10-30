#!/usr/bin/env python3
"""
Tests de la recherche de distance Shopopop dans l'onglet "Terminees" : une
livraison deja faite n'est plus dans "Programmees" (status=schedule) ; sa
distance est alors cherchee parmi les "Terminees" (status=deliveredAndFinished,
valeur confirmee via les DevTools du site app.shopopop.com, cf. shopopop.py).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
import urllib.error
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shopopop

JOUR = date(2026, 10, 2)

# Fonction d'origine, capturee a l'import : test_km_livraison remplace
# shopopop.distance_km le temps de ses tests sans toujours la restaurer.
distance_km = shopopop.distance_km


def _item(prenom, nom, metres):
    return {"recipient": {"first_name": prenom, "last_name": nom}, "delivery_distance": metres}


def _faux_lister(par_statut):
    """`par_statut` : {statut: [items]} ; un statut absent repond HTTP 400."""
    appels = []

    def lister(token, drive_id, jour, statut):
        appels.append(statut)
        if statut not in par_statut:
            raise urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
        return par_statut[statut]
    return lister, appels


class TestTerminees(unittest.TestCase):
    def setUp(self):
        shopopop._statut_terminees = None
        shopopop._terminees_indisponible = False

    def tearDown(self):
        self.setUp()

    def test_programmee_trouvee_sans_chercher_terminees(self):
        lister, appels = _faux_lister({"schedule": [_item("Nadine", "Robert", 4740)]})
        with mock.patch.object(shopopop, "_lister_livraisons", lister):
            self.assertEqual(distance_km("t", "14156", JOUR, "ROBERT NADINE"), 4.74)
        self.assertEqual(appels, ["schedule"])

    def test_livraison_faite_trouvee_dans_terminees(self):
        lister, appels = _faux_lister({"schedule": [],
                                       "deliveredAndFinished": [_item("Céline", "Dubray", 2015)]})
        with mock.patch.object(shopopop, "_lister_livraisons", lister):
            self.assertEqual(distance_km("t", "14156", JOUR, "DUBRAY CELINE"), 2.02)
            # Le statut accepte est memorise : plus d'essais a l'appel suivant.
            appels.clear()
            distance_km("t", "14156", JOUR, "DUBRAY CELINE")
        self.assertEqual(appels, ["schedule", "deliveredAndFinished"])

    def test_aucun_statut_accepte(self):
        lister, _ = _faux_lister({"schedule": []})
        with mock.patch.object(shopopop, "_lister_livraisons", lister):
            self.assertIsNone(distance_km("t", "14156", JOUR, "DUBRAY CELINE"))
        self.assertIsNone(shopopop._statut_terminees)


class TestNomsAbsentsDe(unittest.TestCase):
    """Vérification inverse du workflow "Vérif LAD" : une commande
    'Terminée' côté Shopopop mais absente de notre fichier de livraison."""

    def setUp(self):
        shopopop._statut_terminees = None
        shopopop._terminees_indisponible = False

    def tearDown(self):
        self.setUp()

    def test_commande_shopopop_absente_du_fichier_signalee(self):
        lister, _ = _faux_lister({"deliveredAndFinished": [_item("Nadine", "Robert", 1000),
                                                            _item("Céline", "Dubray", 2000)]})
        with mock.patch.object(shopopop, "_lister_livraisons", lister):
            absents = shopopop.noms_absents_de("t", "14156", JOUR, ["ROBERT NADINE"])
        self.assertEqual(absents, ["Céline Dubray"])

    def test_toutes_les_commandes_shopopop_connues_aucune_absence(self):
        lister, _ = _faux_lister({"deliveredAndFinished": [_item("Nadine", "Robert", 1000)]})
        with mock.patch.object(shopopop, "_lister_livraisons", lister):
            absents = shopopop.noms_absents_de("t", "14156", JOUR, ["ROBERT NADINE"])
        self.assertEqual(absents, [])

    def test_onglet_termines_indisponible_retourne_none(self):
        lister, _ = _faux_lister({})
        with mock.patch.object(shopopop, "_lister_livraisons", lister):
            absents = shopopop.noms_absents_de("t", "14156", JOUR, ["ROBERT NADINE"])
        self.assertIsNone(absents)


if __name__ == "__main__":
    unittest.main()
