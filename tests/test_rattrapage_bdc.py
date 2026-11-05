#!/usr/bin/env python3
"""
Rattrapage le soir des BonDeCommande dont l'archivage Drive par aut_prep a
echoue (03/11/2026, cde 57069955 : 502 de Drive, commande absente des ventes
du 04/11). Le PDF est repris depuis l'email de confirmation, sauf s'il existe
deja ailleurs dans Drive (deplace vers un autre jour, ou mis a la corbeille).

Lancement : python3 -m unittest discover -s tests
"""

import base64
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs


class _Req:
    def __init__(self, valeur):
        self.valeur = valeur

    def execute(self):
        return self.valeur


SUJETS = {
    "m1": "Confirmation commande 04/11/2026 à 10:30 -- Mme A - N° cde:57069955",  # manquant
    "m2": "Confirmation commande 04/11/2026 à 11:00 -- Mme B - N° cde:57000001",  # deja la
    "m3": "Confirmation commande 04/11/2026 à 12:00 -- Mme C - N° cde:57000002",  # deplace
    "m4": "Confirmation commande 05/11/2026 à 12:00 -- Mme D - N° cde:57000003",  # autre jour
}


class _Gmail:
    def users(self):
        return self

    def messages(self):
        return self

    def attachments(self):
        return self

    def list(self, **kw):
        return _Req({"messages": [{"id": i} for i in SUJETS]})

    def get(self, userId, id, format=None, metadataHeaders=None, messageId=None):
        if messageId:  # piece jointe
            return _Req({"data": base64.urlsafe_b64encode(b"%PDF").decode()})
        return _Req({"payload": {
            "headers": [{"name": "Subject", "value": SUJETS[id]}],
            "parts": [{"filename": "bon_encaissement.pdf", "body": {"attachmentId": "a1"}}],
        }})


class _Drive:
    def __init__(self):
        self.crees = []

    def files(self):
        return self

    def list(self, q, **kw):
        if "in parents" in q:  # contenu du dossier du jour
            return _Req({"files": [{"name": "BonDeCommande_57000001.pdf"}]})
        if "57000002" in q:  # existe dans un autre dossier
            return _Req({"files": [{"id": "x"}]})
        return _Req({"files": []})

    def create(self, body, media_body, fields):
        self.crees.append(body["name"])
        return _Req({"id": "nouveau"})


class TestRattrapageBdc(unittest.TestCase):
    def setUp(self):
        self.drive = _Drive()
        self._sauve = {n: getattr(cs, n) for n in (
            "DRIVE_BDC_FOLDER_ID", "_charger_gmail_filters", "_get_gmail_service",
            "_get_drive_service", "_get_or_create_subfolder_drive")}
        cs.DRIVE_BDC_FOLDER_ID = "bdc"
        cs._charger_gmail_filters = lambda: {"conf_from": "no-reply@exemple.fr"}
        cs._get_gmail_service = lambda: _Gmail()
        cs._get_drive_service = lambda: self.drive
        cs._get_or_create_subfolder_drive = lambda svc, parent, nom: f"{parent}/{nom}"

    def tearDown(self):
        for nom, valeur in self._sauve.items():
            setattr(cs, nom, valeur)

    def test_seul_le_bdc_jamais_archive_est_rattrape(self):
        rattrapes = cs.rattraper_bdc_manquants_gmail(date(2026, 11, 4))
        self.assertEqual(rattrapes, ["57069955"])
        self.assertEqual(self.drive.crees, ["BonDeCommande_57069955.pdf"])

    def test_sans_dossier_bdc_configure_rien_n_est_fait(self):
        cs.DRIVE_BDC_FOLDER_ID = ""
        self.assertEqual(cs.rattraper_bdc_manquants_gmail(date(2026, 11, 4)), [])
        self.assertEqual(self.drive.crees, [])


if __name__ == "__main__":
    unittest.main()
