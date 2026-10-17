"""Commandes LIVRAISON du lendemain ouvre : inscrites directement dans
l'onglet du mois a partir de 15h, dans EN ATTENTE avant (promotion a 15h)."""
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import livraison_drive as ld

SPREADSHEET_ID = "id_classeur"


class TestHeurePromotion(unittest.TestCase):
    def _traiter(self, heure, minute):
        with mock.patch.object(ld, "_inscrire_commande") as direct, \
                mock.patch.object(ld, "_inscrire_en_attente") as attente:
            ld.traiter_commande_livraison(
                object(), "ID", "DUPONT", "MARIE", "15/10/2026", numero_commande="1",
                maintenant=datetime(2026, 10, 14, heure, minute, tzinfo=ld._TZ))
        return direct.called, attente.called

    def test_avant_15h_en_attente(self):
        self.assertEqual(self._traiter(14, 30), (False, True))

    def test_a_partir_de_15h_directement(self):
        self.assertEqual(self._traiter(15, 0), (True, False))

    def test_constante(self):
        self.assertEqual(ld.HEURE_PROMOTION, 15)


class _ValuesColonne:
    """Simule values().get() en ne renvoyant que la colonne demandee dans
    `range` (A/B/C/...), contrairement a un mock qui renverrait la ligne
    entiere quelle que soit la colonne demandee : necessaire pour detecter
    qu'une fonction lit la mauvaise colonne (cf. promotion_en_attente_necessaire,
    qui lisait Prenom (B) au lieu de Jour (C))."""
    def __init__(self, jours):
        self._jours = jours  # valeur de la colonne Jour (C) pour chaque ligne

    def get(self, spreadsheetId=None, range=None, valueRenderOption=None):
        colonne = range.split('!')[1][0]
        if colonne == "C":
            valeurs = [[j] if j else [] for j in self._jours]
        else:
            valeurs = [[] for _ in self._jours]
        return mock.Mock(execute=lambda: {"values": valeurs})


class _SpreadsheetsOnglet:
    def __init__(self, jours):
        self._values = _ValuesColonne(jours)

    def values(self):
        return self._values

    def get(self, spreadsheetId=None, fields=None):
        return mock.Mock(execute=lambda: {"sheets": [
            {"properties": {"title": ld.ONGLET_EN_ATTENTE}}]})


class _SheetsOnglet:
    def __init__(self, jours):
        self._s = _SpreadsheetsOnglet(jours)

    def spreadsheets(self):
        return self._s


class TestPromotionEnAttenteNecessaire(unittest.TestCase):
    """promotion_en_attente_necessaire doit regarder la colonne Jour (C) de
    EN ATTENTE, pas Prenom (B) : sinon elle ne detecte jamais rien a
    promouvoir et auto_prepa.py ne declenche plus jamais traiter_en_attente()
    (seul declencheur de cette promotion, cf. docstring du module)."""

    def test_ligne_pour_demain_detectee(self):
        sheets = _SheetsOnglet(["12/10", "20/10"])
        self.assertTrue(ld.promotion_en_attente_necessaire(
            sheets, SPREADSHEET_ID,
            maintenant=datetime(2026, 10, 11, 16, 0, tzinfo=ld._TZ)))

    def test_rien_pour_demain(self):
        sheets = _SheetsOnglet(["20/10", "25/10"])
        self.assertFalse(ld.promotion_en_attente_necessaire(
            sheets, SPREADSHEET_ID,
            maintenant=datetime(2026, 10, 11, 16, 0, tzinfo=ld._TZ)))


if __name__ == "__main__":
    unittest.main()
