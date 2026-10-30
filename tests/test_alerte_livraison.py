#!/usr/bin/env python3
"""Tests de l'alerte temporaire : commande en livraison >= 170 EUR signalee
par email au destinataire 1, a partir du 31/10/2026 1h.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap


class TestAlerteLivraison(unittest.TestCase):
    APRES = datetime(2026, 10, 31, 1, 0, tzinfo=ap._TZ)
    AVANT = datetime(2026, 10, 31, 0, 59, tzinfo=ap._TZ)

    def test_seuil(self):
        self.assertTrue(ap._alerte_livraison_due("170.00", self.APRES))
        self.assertTrue(ap._alerte_livraison_due("254.10", self.APRES))
        self.assertFalse(ap._alerte_livraison_due("169.99", self.APRES))

    def test_avant_activation(self):
        self.assertFalse(ap._alerte_livraison_due("300.00", self.AVANT))

    def test_montant_absent(self):
        self.assertFalse(ap._alerte_livraison_due("", self.APRES))
        self.assertFalse(ap._alerte_livraison_due(None, self.APRES))


if __name__ == "__main__":
    unittest.main()
