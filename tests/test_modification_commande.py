#!/usr/bin/env python3
"""
Tests du traitement d'un mail "commande annulee et remplacee" : la commande
annulee doit TOUJOURS disparaitre de l'app (bons retires de MobUDrive_Bons et
annuler_NUMERO.txt depose), meme si une etape annexe (anticipation, livraison)
echoue. Le 28/09/2026, la cde 55527498 remplacee par 55548605 restait sur
l'app : la lecture de l'archive d'anticipation d'un jour sans dossier
renvoyait set() au lieu de '' et faisait planter tout le traitement du mail.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap


class _Requete:
    def __init__(self, resultat):
        self._resultat = resultat

    def execute(self):
        return self._resultat


class _DriveSansDossier:
    """Drive ou aucun dossier ni fichier n'existe."""

    def files(self):
        class _Files:
            def list(self, **kwargs):
                return _Requete({"files": []})
        return _Files()


class _GmailUnMail:
    """Gmail avec un seul mail de modification, dont on note l'etiquetage."""

    SUJET = ("Modification par le client de la commande N° cde:55527498 : "
             "commande annulée et remplacée par la commande N° cde:55548605")

    def __init__(self):
        self.modifies = []

    def users(self):
        gmail = self

        class _Messages:
            def list(self, **kwargs):
                return _Requete({"messages": [{"id": "m1"}]})

            def get(self, **kwargs):
                return _Requete({"payload": {"headers": [
                    {"name": "Subject", "value": _GmailUnMail.SUJET}]}})

            def modify(self, userId=None, id=None, body=None):
                gmail.modifies.append(id)
                return _Requete({})

        class _Users:
            def messages(self):
                return _Messages()

        return _Users()


class TestArchiveJourAbsente(unittest.TestCase):

    def test_numeros_dossier_absent_ne_plante_pas(self):
        numeros = ap._telecharger_commandes_anticipation_envoyee(
            _DriveSansDossier(), "09_2026", "30_09")
        self.assertEqual(numeros, set())

    def test_texte_dossier_absent_est_vide(self):
        texte = ap._telecharger_texte_archive_jour(
            _DriveSansDossier(), "09_2026", "30_09", "bon_anticipation_envoye_30_09.txt")
        self.assertEqual(texte, "")


class TestModificationToujoursRetireeDeLApp(unittest.TestCase):

    def setUp(self):
        self._origines = {}
        self.appels = []

        def _patch(nom, fn):
            self._origines[nom] = getattr(ap, nom)
            setattr(ap, nom, fn)

        def _plante(*args):
            raise AttributeError("'set' object has no attribute 'strip'")

        self._patch = _patch
        _patch("GMAIL_MODIF_SUBJECTS", ["Modification par le client"])
        _patch("_get_or_create_gmail_label", lambda g, n: "label")
        _patch("_traiter_commande_potentiellement_anticipee", _plante)
        _patch("_traiter_annulation_livraison", _plante)
        for nom in ("_supprimer_bons_drive", "_supprimer_anticipation_archive_drive",
                    "_supprimer_bdc_drive", "_uploader_annulation_drive",
                    "supprimer_commande_avoir_drive"):
            _patch(nom, lambda d, numero, _nom=nom: self.appels.append((_nom, numero)))

    def tearDown(self):
        for nom, fn in self._origines.items():
            setattr(ap, nom, fn)

    def test_etapes_annexes_en_echec(self):
        gmail = _GmailUnMail()
        ap.traiter_modifications_clients(None, gmail, None)
        self.assertIn(("_supprimer_bons_drive", "55527498"), self.appels)
        self.assertIn(("_uploader_annulation_drive", "55527498"), self.appels)
        self.assertEqual(gmail.modifies, ["m1"])


if __name__ == "__main__":
    unittest.main()
