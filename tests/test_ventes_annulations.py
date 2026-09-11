#!/usr/bin/env python3
"""
Tests de non-regression sur les ventes du jour : le BonDeCommande d'une
commande annulee/remplacee restee dans le dossier Drive BDC ne doit jamais
etre compte dans les ventes (il ferait doublon avec la commande de
remplacement, qui contient les memes produits).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs


BDC_ANNULE = "BonDeCommande_54764266.pdf"
BDC_REMPLACANT = "BonDeCommande_54764433.pdf"
BDC_AUTRE = "BonDeCommande_54770396.pdf"


class TestGenererVentesEcarteLesAnnulees(unittest.TestCase):
    """Le scenario de l'incident du 10/09 : le BDC de la commande remplacee a
    ete archive APRES son annulation (son email de confirmation n'avait pas
    encore ete traite), donc jamais supprime — et les ventes du jour l'ont
    compte en double avec son remplacant."""

    def setUp(self):
        self.dossier = os.path.join(cs.BDC_DIR, "10_09")
        os.makedirs(self.dossier, exist_ok=True)
        for nom in (BDC_ANNULE, BDC_REMPLACANT, BDC_AUTRE):
            with open(os.path.join(self.dossier, nom), "w", encoding="utf-8") as f:
                f.write("")

        self.parses = []
        self._patchs = []

        self._patch("telecharger_bdc_depuis_drive", lambda d: self.dossier)
        self._patch("charger_gencods_r1", lambda: set())
        # pdftotext n'est pas rejoue ici : on retient juste les PDF parcourus.
        self._patch("subprocess", _FakeSubprocess(self.parses))

        self.precompute = os.path.join(cs.WORK_DIR, "ventes_10_09.csv")
        self.precompute_sauve = None
        if os.path.exists(self.precompute):
            with open(self.precompute, "rb") as f:
                self.precompute_sauve = f.read()
            os.remove(self.precompute)

    def tearDown(self):
        for nom, valeur in reversed(self._patchs):
            setattr(cs, nom, valeur)
        for nom in (BDC_ANNULE, BDC_REMPLACANT, BDC_AUTRE):
            chemin = os.path.join(self.dossier, nom)
            if os.path.exists(chemin):
                os.remove(chemin)
        if self.precompute_sauve is not None:
            with open(self.precompute, "wb") as f:
                f.write(self.precompute_sauve)

    def _patch(self, nom, valeur):
        self._patchs.append((nom, getattr(cs, nom)))
        setattr(cs, nom, valeur)

    def _generer(self, annulees):
        self._patch("numeros_annules_registre", lambda: annulees)
        return cs.generer_ventes(_Date(2026, 9, 10))

    def test_le_bdc_annule_est_ecarte(self):
        self._generer({"54764266"})
        self.assertNotIn(BDC_ANNULE, self.parses)
        self.assertIn(BDC_REMPLACANT, self.parses)
        self.assertIn(BDC_AUTRE, self.parses)

    def test_sans_annulation_tous_les_bdc_sont_comptes(self):
        self._generer(set())
        self.assertEqual(sorted(self.parses),
                         sorted([BDC_ANNULE, BDC_REMPLACANT, BDC_AUTRE]))

    def test_registre_indisponible_ne_filtre_rien(self):
        self._patch("_get_drive_service", lambda: None)
        self.assertEqual(cs.numeros_annules_registre(), set())


class _Date:
    """Minimum vital pour generer_ventes : strftime('%d_%m')."""

    def __init__(self, annee, mois, jour):
        from datetime import date
        self._d = date(annee, mois, jour)

    def strftime(self, fmt):
        return self._d.strftime(fmt)


class _FakeSubprocess:
    def __init__(self, parses):
        self._parses = parses

    def run(self, args, **kwargs):
        self._parses.append(os.path.basename(args[-2]))
        return _Resultat()


class _Resultat:
    stdout = ""


if __name__ == "__main__":
    unittest.main()
