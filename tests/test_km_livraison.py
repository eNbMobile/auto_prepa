#!/usr/bin/env python3
"""
Tests du cycle de vie de la colonne km de LIVRAISON DRIVE 2026 : un km absent
au moment ou la commande est inscrite ne doit PAS declencher d'email tout de
suite (la commande n'est souvent pas encore synchronisee cote Shopopop, et la
retentative du run suivant recupere la distance). L'email n'est envoye
qu'une fois la date de livraison passee, une seule fois par ligne (cellule km
surlignee en orange).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import livraison_drive as ld

_TZ = ZoneInfo("Europe/Paris")
SPREADSHEET_ID = "id_classeur"


class _Requete:
    def __init__(self, resultat):
        self._resultat = resultat

    def execute(self):
        return self._resultat


class _FakeValues:
    """spreadsheets().values() : lit/ecrit un dict {onglet: [[cellules], ...]}."""

    def __init__(self, classeur):
        self._classeur = classeur
        self.updates = []

    @staticmethod
    def _onglet(plage):
        return plage.split('!')[0].strip("'")

    def get(self, spreadsheetId=None, range=None):
        lignes = self._classeur.get(self._onglet(range), [])
        # A2:E... : les lignes commencent a la 2e (l'en-tete n'est pas relu).
        return _Requete({"values": [list(l) for l in lignes[1:]]})

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self.updates.append((range, body["values"]))
        return _Requete({})

    def append(self, **kwargs):
        return _Requete({})


class _FakeSpreadsheets:
    def __init__(self, classeur, fonds):
        self._classeur = classeur
        self._fonds = fonds          # {onglet: {ligne: backgroundColor}}
        self._values = _FakeValues(classeur)
        self.formats = []            # backgroundColor poses via batchUpdate

    def values(self):
        return self._values

    def get(self, spreadsheetId=None, fields=None, ranges=None, includeGridData=None):
        if not includeGridData:
            return _Requete({"sheets": [
                {"properties": {"title": titre, "sheetId": i}}
                for i, titre in enumerate(self._classeur)
            ]})
        onglet = ranges[0].split('!')[0].strip("'")
        fonds = self._fonds.get(onglet, {})
        nb_lignes = max(len(self._classeur.get(onglet, [])) - 1, 0)
        return _Requete({"sheets": [{"data": [{"rowData": [
            {"values": [{"effectiveFormat": {"backgroundColor": fonds.get(
                2 + i, {"red": 1.0, "green": 1.0, "blue": 1.0})}}]}
            for i in range(nb_lignes)
        ]}]}]})

    def batchUpdate(self, spreadsheetId=None, body=None):
        for requete in body["requests"]:
            cellule = requete["repeatCell"]
            self.formats.append((
                cellule["range"]["sheetId"],
                cellule["range"]["startRowIndex"] + 1,
                cellule["range"]["startColumnIndex"],
                cellule["cell"]["userEnteredFormat"]["backgroundColor"],
            ))
        return _Requete({})


class _FakeSheets:
    def __init__(self, classeur, fonds=None):
        self._spreadsheets = _FakeSpreadsheets(classeur, fonds or {})

    def spreadsheets(self):
        return self._spreadsheets


def _classeur(lignes_septembre, lignes_attente=()):
    return {
        "SEPTEMBRE": [["N° cde", "Date", "Nom", "Prénom", "Distance"]] + [list(l) for l in lignes_septembre],
        ld.ONGLET_EN_ATTENTE: [["Nom", "Prénom", "Jour", "N° commande", "km"]] + [list(l) for l in lignes_attente],
    }


MAINTENANT = datetime(2026, 9, 15, 8, 0, tzinfo=_TZ)   # mardi


class TestInscriptionSansEmail(unittest.TestCase):
    """A l'inscription, un km introuvable n'envoie plus d'email : il est juste
    signale a l'appelant, la retentative des runs suivants s'en charge."""

    def test_km_absent_signale_a_l_appelant_sans_email(self):
        appels = []
        sheets = _FakeSheets(_classeur([]))
        ld.shopopop.distance_km = lambda *a, **k: appels.append(a) or None
        ld._DELAI_RETRY_KM_SECONDES = 0
        km_manquant = ld.traiter_commande_livraison(
            sheets, SPREADSHEET_ID, "PAUMIER", "MARILYNE", "15/09/2026",
            numero_commande="54924251", maintenant=MAINTENANT,
            shopopop_token="jeton", shopopop_drive_id="14156")
        self.assertTrue(km_manquant)
        self.assertEqual(len(appels), 2, "un 2e essai est fait dans le meme run")


class TestRetentative(unittest.TestCase):
    def test_retente_la_livraison_du_jour_et_a_venir(self):
        sheets = _FakeSheets(_classeur([
            ["54924251", "15/09", "PAUMIER", "MARILYNE", ""],       # aujourd'hui
            ["54924252", "16/09", "DUPONT", "JEAN", ""],            # demain
            ["54924253", "12/09", "MARTIN", "LEA", ""],             # livraison passee
            ["54924254", "15/09", "DURAND", "PAUL", "4,2"],         # deja renseignee
        ]))
        a_retenter = ld._km_a_retenter(
            ld.lister_km_manquants(sheets, SPREADSHEET_ID, MAINTENANT), MAINTENANT)
        self.assertEqual([(l[2], l[4]) for l in a_retenter],
                         [("PAUMIER", date(2026, 9, 15)), ("DUPONT", date(2026, 9, 16))])

    def test_ecrit_le_km_recupere(self):
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", ""]]))
        ld.shopopop.distance_km = lambda token, drive, cible, nom: 5.43
        self.assertEqual(
            ld.retenter_km_manquants(sheets, SPREADSHEET_ID, "jeton", "14156", MAINTENANT), 1)
        self.assertEqual(sheets.spreadsheets().values().updates,
                         [("'SEPTEMBRE'!E2", [[5.43]])])


class TestSignalementDefinitif(unittest.TestCase):
    def _signaler(self, sheets, envoye=True):
        emails = []
        ld.signaler_km_manquants_definitifs(
            sheets, SPREADSHEET_ID,
            lambda *args: emails.append(args) or envoye,
            maintenant=MAINTENANT)
        return emails

    def test_pas_d_email_avant_la_date_de_livraison(self):
        sheets = _FakeSheets(_classeur([
            ["54924251", "15/09", "PAUMIER", "MARILYNE", ""],   # livraison du jour
            ["54924252", "16/09", "DUPONT", "JEAN", ""],        # livraison a venir
        ]))
        self.assertEqual(self._signaler(sheets), [])

    def test_email_une_fois_la_livraison_passee(self):
        sheets = _FakeSheets(_classeur([["54924251", "14/09", "PAUMIER", "MARILYNE", ""]]))
        self.assertEqual(self._signaler(sheets),
                         [("54924251", "PAUMIER", "MARILYNE", "14/09/2026")])
        self.assertEqual(sheets.spreadsheets().formats,
                         [(0, 2, 4, ld._ORANGE_KM_A_COMPLETER)],
                         "la cellule km est surlignee pour ne pas re-signaler la ligne")

    def test_pas_de_second_email_pour_une_ligne_deja_signalee(self):
        sheets = _FakeSheets(
            _classeur([["54924251", "14/09", "PAUMIER", "MARILYNE", ""]]),
            fonds={"SEPTEMBRE": {2: ld._ORANGE_KM_A_COMPLETER}})
        self.assertEqual(self._signaler(sheets), [])

    def test_pas_de_marquage_si_l_email_echoue(self):
        sheets = _FakeSheets(_classeur([["54924251", "14/09", "PAUMIER", "MARILYNE", ""]]))
        self.assertEqual(len(self._signaler(sheets, envoye=False)), 1)
        self.assertEqual(sheets.spreadsheets().formats, [],
                         "sans email parti, la ligne doit etre re-signalee au run suivant")

    def test_ignore_les_livraisons_trop_anciennes(self):
        sheets = _FakeSheets(_classeur([["54924251", "01/09", "PAUMIER", "MARILYNE", ""]]))
        self.assertEqual(self._signaler(sheets), [])

    def test_signale_aussi_l_onglet_en_attente(self):
        sheets = _FakeSheets(_classeur([], [["DUPONT", "JEAN", "14/09", "54924252", ""]]))
        self.assertEqual(self._signaler(sheets),
                         [("54924252", "DUPONT", "JEAN", "14/09/2026")])


if __name__ == "__main__":
    unittest.main()
