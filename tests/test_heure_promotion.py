"""Commandes LIVRAISON du lendemain ouvre : inscrites directement dans
l'onglet du mois a partir de 15h, dans EN ATTENTE avant (promotion a 15h)."""
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import livraison_drive as ld


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


if __name__ == "__main__":
    unittest.main()
