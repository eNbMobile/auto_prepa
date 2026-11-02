#!/usr/bin/env python3
"""
Tests de la commande arrivee pendant l'envoi de l'anticipation du matin.

29/10/2026, cde 56826337 : email recu a 6h00:02, anticipation partie a
6h00:11, bon genere a 6h00:35 -> le ramequin manquait dans l'anticipation.
- l'envoi attend desormais les commandes en cours de traitement ;
- un mail de secours part pour une commande du jour arrivee entre 5h59 et
  6h05 (lundi-vendredi) ou 4h59 et 5h05 (samedi).

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

    def test_sans_heure_de_reception(self):
        ok, envois = self._alerte(None)
        self.assertFalse(ok)


class TestAttenteCommandes(unittest.TestCase):

    def _attendre(self, etats):
        """etats : liste de {workflow: ids} renvoyes appel apres appel."""
        appels = {"n": 0}
        sommeils = []

        def runs(wf):
            i = min(appels["n"], len(etats) - 1)
            return set(etats[i].get(wf, ()))

        def sommeil(s):
            sommeils.append(s)
            appels["n"] += 1

        horloge = iter(range(0, 10_000, 10))
        with mock.patch.object(ac, "_runs_en_cours", side_effect=runs):
            ok = ac.attendre_commandes_en_cours(sommeil=sommeil, horloge=lambda: next(horloge))
        return ok, sommeils

    def test_rien_en_cours(self):
        ok, sommeils = self._attendre([{}])
        self.assertTrue(ok)
        self.assertEqual(sommeils, [])

    def test_attend_le_run_puis_l_assemblage(self):
        ok, sommeils = self._attendre([
            {"auto_prepa.yml": {1}},
            {"anticipation_assemble.yml": {2}},
            {},
        ])
        self.assertTrue(ok)
        self.assertIn(ac._ATTENTE_DISPATCH_S, sommeils)

    def test_ignore_les_runs_lances_apres_le_depart(self):
        ok, _ = self._attendre([
            {"auto_prepa.yml": {1}},
            {"auto_prepa.yml": {3}},
        ])
        self.assertTrue(ok)

    def test_plafond(self):
        ok, _ = self._attendre([{"anticipation_assemble.yml": {2}}])
        self.assertFalse(ok)

    def test_api_inaccessible(self):
        with mock.patch.object(ac, "_runs_en_cours", return_value=None):
            self.assertFalse(ac.attendre_commandes_en_cours(sommeil=lambda s: None))


if __name__ == "__main__":
    unittest.main()
