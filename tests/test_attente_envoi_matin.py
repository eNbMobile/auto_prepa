#!/usr/bin/env python3
"""
Tests de la commande arrivee pendant l'envoi de l'anticipation du matin.

29/10/2026, cde 56826337 : email recu a 6h00:02, anticipation partie a
6h00:11, bon genere a 6h00:35 -> le ramequin manquait dans l'anticipation.
- l'envoi part a l'heure du declenchement, sans attendre ;
- un mail de secours part pour une commande du jour arrivee entre 5h59 et
  6h05 (lundi-vendredi) ou 4h59 et 5h05 (samedi), avec ses seuls produits
  des rayons de l'anticipation (A, B, C, D, G).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap
import anticipation_commandes as ac

_TZ = ZoneInfo("Europe/Paris")

_LIGNE = ("3550190501230;Ramequin DURALEX Ovenchef 10cm x4;5,59;5,59;1;NON;0;0;N;"
          "JEUDI 29/10/2026 - 13h30-14h00,56826337,Retrait,x,x,x;AUCUNE ADRESSE;"
          "EQUIPEMENT DE LA MAISON;H;392;00/00/0000;A\n")


class _FakeGmail:
    def __init__(self):
        self.envois = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.envois.append(body)
        return self

    def execute(self):
        return {}


class TestCreneauEnvoiMatin(unittest.TestCase):

    def test_creneaux(self):
        cas = [
            (datetime(2026, 10, 29, 6, 0, 2, tzinfo=_TZ), True),    # jeudi
            (datetime(2026, 10, 29, 5, 59, 0, tzinfo=_TZ), True),
            (datetime(2026, 10, 29, 6, 5, 59, tzinfo=_TZ), True),
            (datetime(2026, 10, 29, 6, 6, 0, tzinfo=_TZ), False),
            (datetime(2026, 10, 29, 5, 58, 59, tzinfo=_TZ), False),
            (datetime(2026, 10, 31, 5, 2, 0, tzinfo=_TZ), True),    # samedi
            (datetime(2026, 10, 31, 6, 0, 0, tzinfo=_TZ), False),
            (datetime(2026, 11, 1, 6, 0, 0, tzinfo=_TZ), False),    # dimanche
            (datetime(2026, 11, 1, 5, 0, 0, tzinfo=_TZ), False),
        ]
        for dt, attendu in cas:
            self.assertEqual(ap._dans_creneau_envoi_matin(dt), attendu, dt)


class TestMailSecours(unittest.TestCase):

    def setUp(self):
        self._dest = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "rayons@example.org"

    def tearDown(self):
        ap.EMAIL_ANTICIPATION = self._dest

    def _alerte(self, dt, jj_mm="29_10", contenu=_LIGNE):
        gmail = _FakeGmail()
        ok = ap._alerter_si_arrivee_pendant_envoi_matin(
            gmail, "56826337", contenu, jj_mm, "10_2026", dt)
        return ok, gmail.envois

    def test_commande_du_jour_dans_le_creneau(self):
        ok, envois = self._alerte(datetime(2026, 10, 29, 6, 0, 2, tzinfo=_TZ))
        self.assertTrue(ok)
        self.assertEqual(len(envois), 1)

    def test_hors_creneau(self):
        ok, envois = self._alerte(datetime(2026, 10, 29, 6, 10, tzinfo=_TZ))
        self.assertFalse(ok)
        self.assertEqual(envois, [])

    def test_commande_d_un_autre_jour(self):
        ok, envois = self._alerte(datetime(2026, 10, 29, 6, 0, 2, tzinfo=_TZ), jj_mm="30_10")
        self.assertFalse(ok)
        self.assertEqual(envois, [])

    def test_produit_hors_rayons_anticipation(self):
        """03/11/2026, cde 57043406 : cheddar du rayon F -> pas de mail."""
        cheddar = ("3060921506682;Cheddar râpé, Petit Marché, 150g;2,70;18,00;1;OUI;0;0;N;"
                   "MARDI 03/11/2026 - 14h00-14h30,57043406,Retrait,x,x,x;M2-KK-7-4;"
                   "FROMAGE A LA COUPE4;P;1052;10/11/2026;F\n")
        ok, envois = self._alerte(datetime(2026, 11, 3, 6, 3, 5, tzinfo=_TZ),
                                  jj_mm="03_11", contenu=cheddar)
        self.assertFalse(ok)
        self.assertEqual(envois, [])

    def test_seuls_les_produits_des_rayons_anticipation(self):
        cheddar = _LIGNE.replace("Ramequin", "Cheddar").rsplit(";", 1)[0] + ";F\n"
        ok, envois = self._alerte(datetime(2026, 10, 29, 6, 0, 2, tzinfo=_TZ),
                                  contenu=_LIGNE + cheddar)
        self.assertTrue(ok)
        import base64, email
        corps = email.message_from_bytes(base64.urlsafe_b64decode(envois[0]["raw"]))
        texte = corps.get_payload(decode=True).decode("utf-8")
        self.assertIn("Ramequin", texte)
        self.assertNotIn("Cheddar", texte)

    def test_rayons_identiques_au_pdf(self):
        self.assertEqual(ap.RAYONS_ANTICIPATION, frozenset(ac.RAYONS_LETTRE))

    def test_sans_heure_de_reception(self):
        ok, envois = self._alerte(None)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
