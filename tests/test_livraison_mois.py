#!/usr/bin/env python3
"""
Tests de LIVRAISON DRIVE 2026 autour du 02/10/2026 :
- l'onglet du mois manquant (OCTOBRE) est cree, copie du mois precedent ;
- une commande EN ATTENTE qui n'a pas pu etre promue n'est pas effacee ;
- l'annulation d'une commande modifiee ne supprime pas la ligne de sa
  commande de remplacement (meme client, meme jour, autre numero) ;
- rattrapage_livraison : lecture des dates, reconnaissance d'une livraison.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import livraison_drive as ld
import rattrapage_livraison as rl

SPREADSHEET_ID = "id_classeur"


class _Requete:
    def __init__(self, resultat=None):
        self._resultat = resultat if resultat is not None else {}

    def execute(self):
        return self._resultat


class _FakeValues:
    def __init__(self, classeur):
        self._classeur = classeur
        self.updates, self.clears = [], []

    def get(self, spreadsheetId=None, range=None, valueRenderOption=None):
        onglet = range.split('!')[0].strip("'")
        if valueRenderOption == "FORMULA":
            return _Requete({"values": []})
        return _Requete({"values": [list(l) for l in self._classeur.get(onglet, [[]])[1:]]})

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self.updates.append((range, body["values"]))
        onglet = range.split('!')[0].strip("'")
        self._classeur.setdefault(onglet, [[]])
        return _Requete()

    def clear(self, spreadsheetId=None, range=None, body=None):
        self.clears.append(range)
        return _Requete()


class _FakeSpreadsheets:
    def __init__(self, classeur):
        self.classeur = classeur
        self._values = _FakeValues(classeur)
        self.requetes = []

    def values(self):
        return self._values

    def get(self, spreadsheetId=None, fields=None):
        return _Requete({"sheets": [
            {"properties": {"title": titre, "sheetId": 100 + i, "index": i,
                            "gridProperties": {"rowCount": 1000}}}
            for i, titre in enumerate(self.classeur)]})

    def batchUpdate(self, spreadsheetId=None, body=None):
        self.requetes += body["requests"]
        reponses = []
        for r in body["requests"]:
            if "duplicateSheet" in r:
                titre = r["duplicateSheet"]["newSheetName"]
                self.classeur[titre] = [["N° cde", "Date", "Nom", "Prénom", "Distance", "Frais"]]
                reponses.append({"duplicateSheet": {"properties": {"sheetId": 999, "title": titre}}})
            elif "addSheet" in r:
                self.classeur[r["addSheet"]["properties"]["title"]] = [[]]
                reponses.append({})
            elif "deleteDimension" in r:
                reponses.append({})
        return _Requete({"replies": reponses})


class _FakeSheets:
    def __init__(self, classeur):
        self._s = _FakeSpreadsheets(classeur)

    def spreadsheets(self):
        return self._s


def _septembre():
    return [["N° cde", "Date", "Nom", "Prénom", "Distance", "Frais"],
            ["55621211", "30/09", "VILLEPASTOUR", "MAÉVA", "1,81"]]


class TestCreationOngletMois(unittest.TestCase):
    def test_onglet_manquant_copie_du_mois_precedent(self):
        sheets = _FakeSheets({"AOÛT": [[]], "SEPTEMBRE": _septembre(), "EN ATTENTE": [[]]})

        ligne = ld._inscrire_commande(sheets, SPREADSHEET_ID, date(2026, 10, 3),
                                      "ROBERT", "NADINE", "55792220", "4,7")

        s = sheets.spreadsheets()
        dup = next(r["duplicateSheet"] for r in s.requetes if "duplicateSheet" in r)
        self.assertEqual(dup, {"sourceSheetId": 101, "insertSheetIndex": 2,
                               "newSheetName": "OCTOBRE"})
        # Donnees A:E de la copie effacees, surlignage compris.
        self.assertIn("'OCTOBRE'!A2:E1000", s.values().clears)
        fond = next(r["repeatCell"] for r in s.requetes if "repeatCell" in r)
        self.assertEqual(fond["range"]["sheetId"], 999)
        self.assertEqual(fond["range"]["endColumnIndex"], 5)
        self.assertEqual(ligne, 2)
        self.assertEqual(s.values().updates[-1],
                         ("'OCTOBRE'!A2:E2", [["55792220", "03/10", "ROBERT", "NADINE", "4,7"]]))

    def test_sans_mois_precedent_onglet_vierge(self):
        sheets = _FakeSheets({"EN ATTENTE": [[]]})
        ld._inscrire_commande(sheets, SPREADSHEET_ID, date(2026, 10, 3),
                              "ROBERT", "NADINE", "55792220", None)
        s = sheets.spreadsheets()
        self.assertTrue(any("addSheet" in r for r in s.requetes))
        self.assertEqual(s.values().updates[0][0], "'OCTOBRE'!A1:F1")

    def test_onglet_existant_pas_recree(self):
        sheets = _FakeSheets({"SEPTEMBRE": _septembre(), "OCTOBRE": [["N° cde"]]})
        ld._inscrire_commande(sheets, SPREADSHEET_ID, date(2026, 10, 3),
                              "ROBERT", "NADINE", "55792220", None)
        self.assertFalse(any("duplicateSheet" in r for r in sheets.spreadsheets().requetes))


class TestEnAttenteNonPerdue(unittest.TestCase):
    def test_commande_non_promue_reste_en_attente(self):
        classeur = {"EN ATTENTE": [["Nom", "Prénom", "Jour", "N° commande", "km"],
                                   ["DUPONT", "JEAN", "02/10", "55700000", "3"],
                                   ["MARTIN", "LUCIE", "06/10", "55700001", ""]]}
        sheets = _FakeSheets(classeur)
        with mock.patch.object(ld, "_inscrire_commande", return_value=False):
            ld.traiter_en_attente(sheets, SPREADSHEET_ID,
                                  maintenant=datetime(2026, 10, 1, 14, 3, tzinfo=ld._TZ))
        reecrit = sheets.spreadsheets().values().updates[-1][1]
        self.assertEqual(sorted(r[3] for r in reecrit), ["55700000", "55700001"])


class TestAnnulationCommandeModifiee(unittest.TestCase):
    def test_ligne_de_la_commande_de_remplacement_epargnee(self):
        # La nouvelle commande 55792220 est deja inscrite ; l'ancienne
        # 55256662 (meme cliente, meme jour) n'a pas de ligne : rien ne doit
        # etre supprime.
        classeur = {"OCTOBRE": [["N° cde", "Date", "Nom", "Prénom", "Distance"],
                                ["55792220", "03/10", "ROBERT", "NADINE", "4,7"]]}
        sheets = _FakeSheets(classeur)
        supprime = ld.annuler_commande_livraison(sheets, SPREADSHEET_ID, "ROBERT", "NADINE",
                                                 "03/10/2026", numero_commande="55256662")
        self.assertFalse(supprime)
        self.assertFalse(any("deleteDimension" in r for r in sheets.spreadsheets().requetes))

    def test_ligne_trouvee_par_numero(self):
        classeur = {"OCTOBRE": [["N° cde", "Date", "Nom", "Prénom", "Distance"],
                                ["55792220", "03/10", "ROBERT", "NADINE", "4,7"],
                                ["55256662", "03/10", "ROBERT", "NADINE", "4,7"]]}
        sheets = _FakeSheets(classeur)
        self.assertTrue(ld.annuler_commande_livraison(
            sheets, SPREADSHEET_ID, "ROBERT", "NADINE", "03/10/2026", numero_commande="55256662"))
        suppr = next(r["deleteDimension"] for r in sheets.spreadsheets().requetes
                     if "deleteDimension" in r)
        self.assertEqual(suppr["range"]["startIndex"], 2)  # ligne 3

    def test_repli_nom_date_sans_numero_en_colonne_a(self):
        # Anciens onglets (colonne A = initiales du preparateur) : le repli
        # nom+jour fonctionne toujours.
        classeur = {"OCTOBRE": [["Prépa", "Date", "Nom", "Prénom", "Distance"],
                                ["LA", "03/10", "ROBERT", "NADINE", "4,7"]]}
        sheets = _FakeSheets(classeur)
        self.assertTrue(ld.annuler_commande_livraison(
            sheets, SPREADSHEET_ID, "ROBERT", "NADINE", "03/10/2026", numero_commande="55256662"))


class TestRattrapage(unittest.TestCase):
    def test_lire_dates(self):
        self.assertEqual(rl.lire_dates("02/10/2026, 03/10/2026 02/10/2026"),
                         ["02/10/2026", "03/10/2026"])
        with self.assertRaises(ValueError):
            rl.lire_dates("31/02/2026")

    def test_quota_gmail_retente(self):
        from googleapiclient.errors import HttpError

        class _Resp(dict):
            status = 403
            reason = "Forbidden"

        class _Req:
            def __init__(self):
                self.n = 0

            def execute(self):
                self.n += 1
                if self.n < 3:
                    raise HttpError(_Resp(), b'{"error": {"errors": [{"reason": "rateLimitExceeded"}]}}')
                return {"ok": True}

        req = _Req()
        with mock.patch.object(rl.time, "sleep"):
            self.assertEqual(rl._executer(req), {"ok": True})
        self.assertEqual(req.n, 3)

    def test_est_livraison(self):
        self.assertTrue(rl.est_livraison("mon mode de remise Je reçois mes courses\n chez moi"))
        self.assertFalse(rl.est_livraison("mon mode de remise Je récupère mes courses au drive"))


if __name__ == "__main__":
    unittest.main()
