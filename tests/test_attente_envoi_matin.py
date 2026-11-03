#!/usr/bin/env python3
"""
Tests de la commande arrivee pendant l'envoi de l'anticipation du matin.

29/10/2026, cde 56826337 : email recu a 6h00:02, anticipation partie a
6h00:11, bon genere a 6h00:35 -> le ramequin manquait dans l'anticipation.
- l'envoi part a l'heure du declenchement, sauf commande en cours de
  traitement : il attend alors la fin de son traitement ;
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


def _job(*etapes):
    """Job d'un run aut_prep : etapes (nom, status, conclusion)."""
    return {"jobs": [{"status": "in_progress", "steps": [
        {"name": n, "status": st, "conclusion": c} for n, st, c in etapes]}]}


_VERIF = ac._ETAPE_VERIF_COMMANDES
_SUIV = "Restaurer pdftotext"
_EXEC = ac._ETAPE_TRAITEMENT


class TestEtatRunCommandes(unittest.TestCase):

    def _etat(self, rep):
        with mock.patch.object(ac, "_api_github", return_value=rep):
            return ac._etat_run_commandes(1)

    def test_hors_fenetre(self):
        self.assertEqual(self._etat(_job((_VERIF, "completed", "skipped"))), "sans_commande")

    def test_rien_de_nouveau(self):
        self.assertEqual(self._etat(_job((_VERIF, "completed", "success"),
                                         (_SUIV, "completed", "skipped"))), "sans_commande")

    def test_verification_en_cours(self):
        self.assertEqual(self._etat(_job((_VERIF, "in_progress", None),
                                         (_SUIV, "queued", None))), "en_cours")

    def test_commande_en_cours(self):
        self.assertEqual(self._etat(_job((_VERIF, "completed", "success"),
                                         (_SUIV, "completed", "success"),
                                         (_EXEC, "in_progress", None))), "en_cours")

    def test_commande_traitee(self):
        self.assertEqual(self._etat(_job((_VERIF, "completed", "success"),
                                         (_SUIV, "completed", "success"),
                                         (_EXEC, "completed", "success"))), "termine")

    def test_run_en_file(self):
        self.assertEqual(self._etat({"jobs": []}), "en_cours")


class TestAttenteCommandes(unittest.TestCase):

    def _attendre(self, runs, etats, assemblages):
        """runs : ids aut_prep au depart ; etats/assemblages : listes
        consommees a chaque passage (le dernier element se repete)."""
        sommeils = []
        n = {"etat": 0, "assemblage": 0}

        def runs_en_cours(wf, age_max_s=None):
            if wf == ac._WORKFLOW_COMMANDES:
                return set(runs)
            i = min(n["assemblage"], len(assemblages) - 1)
            n["assemblage"] += 1
            return set(assemblages[i])

        def etat(run_id):
            i = min(n["etat"], len(etats) - 1)
            return etats[i]

        def sommeil(s):
            sommeils.append(s)
            n["etat"] += 1

        horloge = iter(range(0, 100_000, 5))
        with mock.patch.object(ac, "_runs_en_cours", side_effect=runs_en_cours), \
             mock.patch.object(ac, "_etat_run_commandes", side_effect=etat):
            ok = ac.attendre_commandes_en_cours(sommeil=sommeil, horloge=lambda: next(horloge))
        return ok, sommeils

    def test_rien_en_cours_envoi_immediat(self):
        ok, sommeils = self._attendre([], ["termine"], [()])
        self.assertTrue(ok)
        self.assertEqual(sommeils, [])

    def test_run_sans_commande_envoi_immediat(self):
        ok, sommeils = self._attendre([1], ["sans_commande"], [()])
        self.assertTrue(ok)
        self.assertEqual(sommeils, [])

    def test_attend_la_commande_puis_son_assemblage(self):
        ok, sommeils = self._attendre([1], ["en_cours", "en_cours", "termine"],
                                      [(2,), (2,), ()])
        self.assertTrue(ok)
        self.assertIn(ac._ATTENTE_DISPATCH_S, sommeils)
        self.assertEqual(sommeils.count(ac._ATTENTE_INTERVALLE_S), 4)

    def test_assemblage_en_cours_au_depart(self):
        ok, sommeils = self._attendre([], ["termine"], [(2,), ()])
        self.assertTrue(ok)
        self.assertEqual(sommeils, [ac._ATTENTE_INTERVALLE_S])

    def test_garde_fou_run_bloque(self):
        ok, _ = self._attendre([1], ["en_cours"], [()])
        self.assertFalse(ok)

    def test_run_fantome_ignore(self):
        """03/11/2026 : run 36803839599 « queued » depuis le 01/10, sans job,
        attendu 25 min -> il doit etre ignore."""
        rep = {"workflow_runs": [
            {"id": 36803839599, "created_at": "2026-10-01T02:01:10Z"},
            {"id": 2, "created_at": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")},
        ]}
        with mock.patch.object(ac, "_api_github", return_value=rep):
            self.assertEqual(ac._runs_en_cours(ac._WORKFLOW_COMMANDES,
                                               ac._AGE_MAX_RUN_COMMANDES_S), {2})
            self.assertEqual(ac._runs_en_cours(ac._WORKFLOW_ASSEMBLAGE), {36803839599, 2})

    def test_api_inaccessible(self):
        with mock.patch.object(ac, "_runs_en_cours", return_value=None):
            self.assertFalse(ac.attendre_commandes_en_cours(sommeil=lambda s: None))


if __name__ == "__main__":
    unittest.main()
