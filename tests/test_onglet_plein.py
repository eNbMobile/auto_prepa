#!/usr/bin/env python3
"""
Tests de l'agrandissement automatique d'un onglet de LIVRAISON DRIVE 2026
plein : quand la premiere ligne libre depasse la grille de l'onglet (l'API
Sheets refuse alors d'ecrire, "exceeds grid limits"), des lignes sont
ajoutees avant l'ecriture, avec la mise en forme et les formules de la
derniere ligne.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import livraison_drive as ld

SPREADSHEET_ID = "id_classeur"


class _Requete:
    def __init__(self, resultat=None):
        self._resultat = resultat if resultat is not None else {}

    def execute(self):
        return self._resultat


class _FakeValues:
    """`classeur` : {onglet: [[cellules], ...]} (en-tete inclus), `formules` :
    {onglet: [[cellules], ...]} renvoye en valueRenderOption=FORMULA."""

    def __init__(self, classeur, formules):
        self._classeur = classeur
        self._formules = formules
        self.updates = []

    @staticmethod
    def _onglet(plage):
        return plage.split('!')[0].strip("'")

    def get(self, spreadsheetId=None, range=None, valueRenderOption=None):
        onglet = self._onglet(range)
        if valueRenderOption == "FORMULA":
            num = int(range.split('!')[1].split(':')[0])
            return _Requete({"values": [list(self._formules[onglet][num - 1])]})
        return _Requete({"values": [list(l) for l in self._classeur[onglet][1:]]})

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self.updates.append((range, body["values"]))
        return _Requete()


class _FakeSpreadsheets:
    def __init__(self, classeur, nb_lignes, formules):
        self._classeur = classeur
        self._nb_lignes = nb_lignes
        self._values = _FakeValues(classeur, formules)
        self.batch_updates = []

    def values(self):
        return self._values

    def get(self, spreadsheetId=None, fields=None):
        return _Requete({"sheets": [
            {"properties": {"title": titre, "sheetId": i,
                            "gridProperties": {"rowCount": self._nb_lignes[titre]}}}
            for i, titre in enumerate(self._classeur)
        ]})

    def batchUpdate(self, spreadsheetId=None, body=None):
        self.batch_updates.append(body["requests"])
        return _Requete()


class _FakeSheets:
    def __init__(self, classeur, nb_lignes, formules=None):
        self._spreadsheets = _FakeSpreadsheets(classeur, nb_lignes, formules or {})

    def spreadsheets(self):
        return self._spreadsheets


def _mois_plein(nb):
    lignes = [["N°", "Date", "Nom", "Prénom", "km", "Frais"]]
    lignes += [[str(55000000 + i), "22/09", f"NOM{i}", f"PRENOM{i}", "5"] for i in range(nb - 1)]
    return lignes


class TestOngletPlein(unittest.TestCase):
    def test_onglet_du_mois_plein_ajoute_une_ligne(self):
        classeur = {"SEPTEMBRE": _mois_plein(134)}
        formules = {"SEPTEMBRE": {133: ["55000132", "22/09", "NOM132", "PRENOM132", "5", "=E134*0,5"]}}
        sheets = _FakeSheets(classeur, {"SEPTEMBRE": 134}, formules)

        ld._inscrire_commande(sheets, SPREADSHEET_ID, date(2026, 9, 29),
                              "PAUMIER", "MARILYNE", "55542291", "6,36")

        requetes = sheets.spreadsheets().batch_updates[0]
        self.assertEqual(requetes[0], {"appendDimension": {
            "sheetId": 0, "dimension": "ROWS", "length": 1}})
        self.assertEqual(requetes[1]["copyPaste"]["pasteType"], "PASTE_FORMAT")
        self.assertEqual(requetes[1]["copyPaste"]["destination"],
                         {"sheetId": 0, "startRowIndex": 134, "endRowIndex": 135})
        # Seule la colonne F (formule Frais) est recopiee en formule.
        self.assertEqual(len(requetes), 3)
        self.assertEqual(requetes[2]["copyPaste"]["pasteType"], "PASTE_FORMULA")
        self.assertEqual(requetes[2]["copyPaste"]["source"]["startColumnIndex"], 5)
        self.assertEqual(sheets.spreadsheets().values().updates[0][0], "'SEPTEMBRE'!A135:E135")

    def test_onglet_en_attente_plein_ajoute_une_ligne(self):
        classeur = {"EN ATTENTE": [["Nom", "Prénom", "Jour", "N° commande", "km"],
                                   ["DUPONT", "JEAN", "30/09", "55500000", "3"]]}
        formules = {"EN ATTENTE": {1: ["DUPONT", "JEAN", "30/09", "55500000", "3"]}}
        sheets = _FakeSheets(classeur, {"EN ATTENTE": 2}, formules)

        ld._inscrire_en_attente(sheets, SPREADSHEET_ID, date(2026, 10, 1),
                                "MARTIN", "LUCIE", "55600000", None)

        requetes = sheets.spreadsheets().batch_updates[0]
        self.assertEqual(requetes[0]["appendDimension"]["length"], 1)
        self.assertEqual([list(r)[0] for r in requetes], ["appendDimension", "copyPaste"])
        self.assertEqual(sheets.spreadsheets().values().updates[0][0], "'EN ATTENTE'!A3:E3")

    def test_onglet_avec_de_la_place_n_est_pas_agrandi(self):
        classeur = {"SEPTEMBRE": _mois_plein(100)}
        sheets = _FakeSheets(classeur, {"SEPTEMBRE": 1000})

        ld._inscrire_commande(sheets, SPREADSHEET_ID, date(2026, 9, 29),
                              "PAUMIER", "MARILYNE", "55542291", "6,36")

        self.assertEqual(sheets.spreadsheets().batch_updates, [])
        self.assertEqual(sheets.spreadsheets().values().updates[0][0], "'SEPTEMBRE'!A101:E101")


if __name__ == "__main__":
    unittest.main()
