#!/usr/bin/env python3
"""
Tests du cumul du contrôle de stocks sur une période
(cumul_controle_stocks.py) — basé sur les PDF réellement envoyés par email
chaque jour (sujet « Contrôle stocks … »), pas sur un recalcul depuis les
archives de stocks.

Lancement : python3 -m unittest discover -s tests
"""

import base64
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs
import cumul_controle_stocks as ccs


def _generer_pdf_ecarts_test(rows, chemin):
    """Génère un vrai PDF 'écarts' (même mise en page que controle_stocks.py)
    pour tester le parsing bout en bout."""
    cs._construire_pdf_tableau(rows, "<b>Contrôle de stocks — test</b>", chemin)
    with open(chemin, "rb") as f:
        return f.read()


class _FakeExec:
    def __init__(self, valeur):
        self._valeur = valeur

    def execute(self):
        return self._valeur


class _FakeAttachments:
    def __init__(self, data_par_cle):
        self._data = data_par_cle  # {(message_id, attachment_id): bytes}

    def get(self, userId=None, messageId=None, id=None):
        contenu = self._data[(messageId, id)]
        return _FakeExec({"data": base64.urlsafe_b64encode(contenu).decode()})


class _FakeMessages:
    def __init__(self, details, attachments):
        self._details = details
        self._attachments = attachments

    def list(self, userId=None, q=None, maxResults=None, pageToken=None):
        return _FakeExec({"messages": [{"id": i} for i in self._details]})

    def get(self, userId=None, id=None, format=None):
        return _FakeExec(self._details[id])

    def attachments(self):
        return self._attachments


class _FakeService:
    def __init__(self, details, attachments_data):
        self._messages = _FakeMessages(details, _FakeAttachments(attachments_data))

    def users(self):
        return self

    def messages(self):
        return self._messages


def _detail(message_id, sujet, internal_date, attachment_id=None, nom_pj=None):
    parts = []
    if attachment_id:
        parts.append({"filename": nom_pj, "body": {"attachmentId": attachment_id}})
    return {
        "id": message_id,
        "internalDate": str(internal_date),
        "payload": {
            "headers": [{"name": "Subject", "value": sujet}],
            "parts": parts,
        },
    }


class TestCumulerPeriode(unittest.TestCase):

    def setUp(self):
        self._tmp = []

        def _pdf(nom, rows):
            chemin = f"/tmp/_test_{nom}.pdf"
            contenu = _generer_pdf_ecarts_test(rows, chemin)
            self._tmp.append(chemin)
            return contenu

        # 30/09 : deux emails (relance manuelle) — seul le plus récent (B) compte.
        pdf_30_09_ancien = _pdf("30_09_ancien", [
            ("3200000000001", 10.0, 0, 0, 7.0, -3.0, "ECART", "Produit A"),
        ])
        pdf_30_09_recent = _pdf("30_09_recent", [
            ("3200000000001", 10.0, 0, 0, 9.0, -1.0, "ECART", "Produit A"),
            ("3200000000002", 5.0, 0, 0, 8.0, 3.0, "ECART", "Produit B"),
        ])
        # 01/10 : un seul email.
        pdf_01_10 = _pdf("01_10", [
            ("3200000000001", 9.0, 0, 0, 10.0, 1.0, "ECART", "Produit A"),
        ])

        details = {
            "m1": _detail("m1", "Contrôle stocks 30/09/2026 — 1 écart", 1000,
                          "att1", "ecarts_20260930.pdf"),
            "m2": _detail("m2", "Contrôle stocks 30/09/2026 — 2 écarts", 2000,
                          "att2", "ecarts_20260930.pdf"),
            "m3": _detail("m3", "Contrôle stocks 01/10/2026 — 1 écart", 3000,
                          "att3", "ecarts_20261001.pdf"),
            # 03/10 : email envoyé (stock insuffisant) mais sans PDF d'écarts.
            "m4": _detail("m4", "Contrôle stocks 03/10/2026 — 2 stocks bas", 4000),
            # Un email d'un autre workflow (ne doit pas être pris en compte).
            "m5": _detail("m5", "Différence de stocks 02/10/2026 — 1 différence", 5000),
        }
        attachments_data = {
            ("m1", "att1"): pdf_30_09_ancien,
            ("m2", "att2"): pdf_30_09_recent,
            ("m3", "att3"): pdf_01_10,
        }

        self._svc = cs._get_gmail_service
        cs._get_gmail_service = lambda: _FakeService(details, attachments_data)

    def tearDown(self):
        cs._get_gmail_service = self._svc
        for chemin in self._tmp:
            if os.path.exists(chemin):
                os.remove(chemin)

    def test_dernier_email_du_jour_retenu(self):
        lignes, avec, sans_ecart, sans_email = ccs.cumuler_periode(
            date(2026, 9, 30), date(2026, 10, 3))

        self.assertEqual(avec, [date(2026, 9, 30), date(2026, 10, 1)])
        self.assertEqual(sans_ecart, [date(2026, 10, 3)])
        self.assertEqual(sans_email, [date(2026, 10, 2)])

        resultat = {g: (nb, ecart) for g, nb, ecart, _ in lignes}
        # Produit A : -1 (30/09, email le plus récent, pas -3 de l'ancien) + 1 (01/10) = 0.
        self.assertEqual(resultat["3200000000001"], (2, 0.0))
        # Produit B : seulement présent dans l'email retenu du 30/09.
        self.assertEqual(resultat["3200000000002"], (1, 3.0))

    def test_gencod_absent_partout_nest_pas_dans_le_resultat(self):
        lignes, *_ = ccs.cumuler_periode(date(2026, 9, 30), date(2026, 10, 3))
        gencods = {g for g, *_ in lignes}
        self.assertEqual(gencods, {"3200000000001", "3200000000002"})


class TestParserPdfEcarts(unittest.TestCase):

    def test_extrait_gencod_libelle_et_ecart(self):
        chemin = "/tmp/_test_parser.pdf"
        cs._construire_pdf_tableau([
            ("3274080001005", 10.0, 5.0, 5.0, 8.0, 3.0, "ECART",
             "Eau de source CRISTALINE, 6 bouteilles de 1,5l"),
            ("3256224234494", 20.0, 10.0, 10.0, 5.0, -5.0, "ECART",
             "U Lait UHT demi écrémé - 6 briques de 1L"),
        ], "<b>Test</b>", chemin)
        try:
            resultats = ccs.parser_pdf_ecarts(chemin)
        finally:
            os.remove(chemin)
        self.assertEqual(resultats, [
            ("3274080001005", "Eau de source CRISTALINE, 6 bouteilles de 1,5l", 3),
            ("3256224234494", "U Lait UHT demi écrémé - 6 briques de 1L", -5),
        ])


if __name__ == "__main__":
    unittest.main()
