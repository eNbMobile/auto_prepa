#!/usr/bin/env python3
"""
Tests du workflow "Deplacer commandes" : un BonDeCommande_NUMERO.pdf archive
dans BDC/MM_AAAA/JJ_MM doit pouvoir passer d'un jour a un autre.

Lancement : python3 -m unittest discover -s tests
"""

import os
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap
import deplacer_commande as dc

BDC_ID = "id_bdc"
DOSSIER = "application/vnd.google-apps.folder"
AUJOURD_HUI = date(2026, 9, 25)   # vendredi


class _FakeRequete:
    def __init__(self, resultat=None, effet=None):
        self._resultat = resultat if resultat is not None else {}
        self._effet = effet

    def execute(self):
        if self._effet is not None:
            self._effet()
        return self._resultat


class _FakeFiles:
    def __init__(self, store):
        self.store = store
        self._n = 0

    def _par_id(self, file_id):
        return next(f for f in self.store if f["id"] == file_id)

    def list(self, q="", fields=None, **kwargs):
        m_parent = re.search(r"'([^']+)' in parents", q)
        m_mime = re.search(r"mimeType='([^']+)'", q)
        m_name = re.search(r"name='([^']+)'", q)
        res = []
        for f in self.store:
            if f.get("trashed"):
                continue
            if m_parent and m_parent.group(1) not in f.get("parents", []):
                continue
            if m_mime and f.get("mimeType") != m_mime.group(1):
                continue
            if m_name and f.get("name") != m_name.group(1):
                continue
            res.append(dict(f))
        return _FakeRequete({"files": res})

    def get(self, fileId=None, fields=None):
        return _FakeRequete(dict(self._par_id(fileId)))

    def create(self, body=None, fields=None, **kwargs):
        self._n += 1
        nouveau = {"id": f"cree{self._n}", "name": body["name"],
                   "mimeType": body.get("mimeType"), "parents": list(body["parents"])}
        self.store.append(nouveau)
        return _FakeRequete({"id": nouveau["id"]})

    def update(self, fileId=None, body=None, addParents=None, removeParents=None, **kwargs):
        def _effet():
            f = self._par_id(fileId)
            if (body or {}).get("trashed"):
                f["trashed"] = True
            if removeParents:
                f["parents"] = [p for p in f["parents"] if p != removeParents]
            if addParents:
                f["parents"].append(addParents)
        return _FakeRequete(effet=_effet)


class _FakeDrive:
    def __init__(self, store):
        self._files = _FakeFiles(store)

    def files(self):
        return self._files


def _dossier(id_, nom, parent):
    return {"id": id_, "name": nom, "mimeType": DOSSIER, "parents": [parent]}


def _bdc(id_, numero, parent):
    return {"id": id_, "name": f"BonDeCommande_{numero}.pdf",
            "mimeType": "application/pdf", "parents": [parent]}


def _store():
    return [
        _dossier(BDC_ID, "BDC", "id_github"),
        _dossier("m09", "09_2026", BDC_ID),
        _dossier("j24", "24_09", "m09"),
        _dossier("j25", "25_09", "m09"),
        _dossier("manuel", "Traitement manuel", BDC_ID),
        _bdc("f1", "54868421", "j24"),
        _bdc("f2", "54868422", "j25"),
    ]


def _parents(drive, file_id):
    return drive.files()._par_id(file_id)["parents"]


class TestSaisie(unittest.TestCase):
    def test_numeros(self):
        self.assertEqual(dc.extraire_numeros("54868421, 54868422;54868421\nBonDeCommande_54868423.pdf"),
                         ["54868421", "54868422", "54868423"])
        self.assertEqual(dc.extraire_numeros("12 abc"), [])

    def test_date_complete(self):
        self.assertEqual(dc.lire_date("26/09/2026", AUJOURD_HUI), date(2026, 9, 26))
        self.assertEqual(dc.lire_date("26-09-26", AUJOURD_HUI), date(2026, 9, 26))

    def test_date_sans_annee_au_plus_pres(self):
        self.assertEqual(dc.lire_date("26/09", AUJOURD_HUI), date(2026, 9, 26))
        self.assertEqual(dc.lire_date("02/01", date(2026, 12, 30)), date(2027, 1, 2))
        self.assertEqual(dc.lire_date("31/12", date(2027, 1, 2)), date(2026, 12, 31))

    def test_date_invalide(self):
        self.assertIsNone(dc.lire_date("31/02/2026", AUJOURD_HUI))
        self.assertIsNone(dc.lire_date("demain", AUJOURD_HUI))

    def test_choix_du_jour(self):
        actuel = date(2026, 9, 24)
        self.assertEqual(dc.date_cible("lendemain de la commande", "", actuel, AUJOURD_HUI),
                         date(2026, 9, 25))
        self.assertEqual(dc.date_cible("", "", actuel, AUJOURD_HUI), date(2026, 9, 25))
        self.assertEqual(dc.date_cible("aujourd'hui", "", actuel, AUJOURD_HUI), AUJOURD_HUI)
        self.assertEqual(dc.date_cible("demain", "", actuel, AUJOURD_HUI), date(2026, 9, 26))
        self.assertEqual(dc.date_cible("après-demain", "", actuel, AUJOURD_HUI), date(2026, 9, 27))

    def test_date_saisie_prioritaire(self):
        self.assertEqual(dc.date_cible("demain", "30/09", date(2026, 9, 24), AUJOURD_HUI),
                         date(2026, 9, 30))
        with self.assertRaises(ValueError):
            dc.date_cible("demain", "32/09", date(2026, 9, 24), AUJOURD_HUI)


class TestDeplacer(unittest.TestCase):
    def setUp(self):
        self._bdc = ap.DRIVE_BDC_FOLDER_ID
        ap.DRIVE_BDC_FOLDER_ID = BDC_ID
        self.drive = _FakeDrive(_store())

    def tearDown(self):
        ap.DRIVE_BDC_FOLDER_ID = self._bdc

    def test_localise_le_jour_actuel(self):
        self.assertEqual(dc.localiser_bdc(self.drive, "54868421"),
                         [{"file_id": "f1", "dossier_id": "j24", "jj_mm": "24_09", "mm_aaaa": "09_2026"}])

    def test_depot_manuel_ignore(self):
        self.drive.files().store.append(_bdc("fm", "54868421", "manuel"))
        self.assertEqual([e["file_id"] for e in dc.localiser_bdc(self.drive, "54868421")], ["f1"])

    def test_vers_le_lendemain(self):
        ok, msg = dc.deplacer(self.drive, "54868421", None, "lendemain de la commande",
                              "", AUJOURD_HUI)
        self.assertTrue(ok, msg)
        self.assertEqual(_parents(self.drive, "f1"), ["j25"])

    def test_vers_un_jour_a_creer(self):
        """Le dossier du jour cible n'existe pas encore (autre mois) : il est cree."""
        ok, msg = dc.deplacer(self.drive, "54868421", date(2026, 10, 2), aujourd_hui=AUJOURD_HUI)
        self.assertTrue(ok, msg)
        store = self.drive.files().store
        mois = next(f for f in store if f["name"] == "10_2026")
        jour = next(f for f in store if f["name"] == "02_10")
        self.assertEqual(mois["parents"], [BDC_ID])
        self.assertEqual(jour["parents"], [mois["id"]])
        self.assertEqual(_parents(self.drive, "f1"), [jour["id"]])

    def test_deja_dans_le_bon_jour(self):
        ok, msg = dc.deplacer(self.drive, "54868422", date(2026, 9, 25), aujourd_hui=AUJOURD_HUI)
        self.assertTrue(ok)
        self.assertIn("rien a faire", msg)
        self.assertEqual(_parents(self.drive, "f2"), ["j25"])

    def test_deja_present_dans_le_jour_cible(self):
        """Deplacement deja fait en partie : l'exemplaire d'origine part a la corbeille."""
        self.drive.files().store.append(_bdc("f1bis", "54868421", "j25"))
        ok, msg = dc.deplacer(self.drive, "54868421", date(2026, 9, 25), aujourd_hui=AUJOURD_HUI)
        self.assertTrue(ok, msg)
        self.assertTrue(self.drive.files()._par_id("f1").get("trashed"))
        self.assertFalse(self.drive.files()._par_id("f1bis").get("trashed"))

    def test_plusieurs_jours_hors_cible(self):
        """Present dans deux jours dont aucun n'est la cible : ambigu, rien ne bouge."""
        self.drive.files().store.append(_bdc("f1bis", "54868421", "j25"))
        ok, msg = dc.deplacer(self.drive, "54868421", date(2026, 9, 28), aujourd_hui=AUJOURD_HUI)
        self.assertFalse(ok)
        self.assertIn("plusieurs jours", msg)
        self.assertEqual(_parents(self.drive, "f1"), ["j24"])
        self.assertEqual(_parents(self.drive, "f1bis"), ["j25"])
        ok, msg = dc.deplacer(self.drive, "54868421", None, "lendemain", "", AUJOURD_HUI)
        self.assertFalse(ok)
        self.assertIn("saisir une date", msg)

    def test_introuvable(self):
        ok, msg = dc.deplacer(self.drive, "99999999", date(2026, 9, 26), aujourd_hui=AUJOURD_HUI)
        self.assertFalse(ok)
        self.assertIn("introuvable", msg)


if __name__ == "__main__":
    unittest.main()
