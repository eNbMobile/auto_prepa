#!/usr/bin/env python3
"""
Tests du workflow "Deplacer commandes" : un BonDeCommande_NUMERO.pdf archive
dans BDC/MM_AAAA/JJ_MM doit pouvoir passer d'un jour a un autre.

Lancement : python3 -m unittest discover -s tests
"""

import os
import re
import sys
import tempfile
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

    def get_media(self, fileId=None):
        return self._par_id(fileId).get("contenu", b"")

    def create(self, body=None, fields=None, media_body=None, **kwargs):
        self._n += 1
        nouveau = {"id": f"cree{self._n}", "name": body["name"],
                   "mimeType": body.get("mimeType"), "parents": list(body["parents"])}
        if media_body is not None:
            nouveau["contenu"] = media_body.contenu
        self.store.append(nouveau)
        return _FakeRequete({"id": nouveau["id"]})

    def update(self, fileId=None, body=None, addParents=None, removeParents=None,
               media_body=None, **kwargs):
        def _effet():
            f = self._par_id(fileId)
            if (body or {}).get("trashed"):
                f["trashed"] = True
            if removeParents:
                f["parents"] = [p for p in f["parents"] if p != removeParents]
            if addParents:
                f["parents"].append(addParents)
            if media_body is not None:
                f["contenu"] = media_body.contenu
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


class _FakeMediaFileUpload:
    def __init__(self, path, mimetype=None, resumable=False):
        with open(path, "rb") as f:
            self.contenu = f.read()


class _FakeMediaIoBaseDownload:
    def __init__(self, buf, contenu):
        self._buf, self._contenu = buf, contenu

    def next_chunk(self):
        self._buf.write(self._contenu)
        return None, True


class TestFileAttente(unittest.TestCase):
    """Mode par defaut (sans --forcer) : la demande n'est pas appliquee tout de
    suite, elle est inscrite dans un marqueur Drive GITHUB/DeplacementsEnAttente/."""

    def setUp(self):
        self._bdc = ap.DRIVE_BDC_FOLDER_ID
        ap.DRIVE_BDC_FOLDER_ID = BDC_ID
        self.drive = _FakeDrive(_store())
        self._upload = dc.MediaFileUpload
        self._download = dc.MediaIoBaseDownload
        dc.MediaFileUpload = _FakeMediaFileUpload
        dc.MediaIoBaseDownload = _FakeMediaIoBaseDownload
        self._tmp = tempfile.TemporaryDirectory()
        self._work_dir = ap.WORK_DIR
        ap.WORK_DIR = self._tmp.name

    def tearDown(self):
        ap.DRIVE_BDC_FOLDER_ID = self._bdc
        dc.MediaFileUpload = self._upload
        dc.MediaIoBaseDownload = self._download
        ap.WORK_DIR = self._work_dir
        self._tmp.cleanup()

    def _marqueurs_store(self):
        return [f for f in self.drive.files().store
                if not f.get("trashed") and re.match(r"^deplacer_\d+\.txt$", f["name"])]

    def test_mettre_en_attente_ne_deplace_rien(self):
        ok, msg = dc.mettre_en_attente(self.drive, "54868421", None,
                                        "lendemain de la commande", "", AUJOURD_HUI)
        self.assertTrue(ok, msg)
        self.assertIn("22h", msg)
        self.assertEqual(_parents(self.drive, "f1"), ["j24"])  # pas deplace

    def test_mettre_en_attente_depose_un_marqueur_lisible(self):
        dc.mettre_en_attente(self.drive, "54868421", None,
                             "lendemain de la commande", "", AUJOURD_HUI)
        marqueurs = dc.lister_marqueurs_attente(self.drive)
        self.assertEqual([(n, c) for _id, n, c in marqueurs],
                         [("54868421", date(2026, 9, 25))])

    def test_mettre_en_attente_introuvable(self):
        ok, msg = dc.mettre_en_attente(self.drive, "99999999", date(2026, 9, 26),
                                       aujourd_hui=AUJOURD_HUI)
        self.assertFalse(ok)
        self.assertIn("introuvable", msg)
        self.assertEqual(self._marqueurs_store(), [])

    def test_nouvelle_demande_remplace_le_marqueur(self):
        dc.mettre_en_attente(self.drive, "54868421", date(2026, 9, 26), aujourd_hui=AUJOURD_HUI)
        dc.mettre_en_attente(self.drive, "54868421", date(2026, 9, 28), aujourd_hui=AUJOURD_HUI)
        marqueurs = dc.lister_marqueurs_attente(self.drive)
        self.assertEqual([(n, c) for _id, n, c in marqueurs], [("54868421", date(2026, 9, 28))])
        self.assertEqual(len(self._marqueurs_store()), 1)

    def test_lister_vide_si_aucun_dossier(self):
        self.assertEqual(dc.lister_marqueurs_attente(self.drive), [])

    def test_traitement_du_soir_deplace_et_supprime_le_marqueur(self):
        """Simule deplacer_commandes_attente.py : chaque marqueur en attente est
        applique via dc.deplacer, puis mis a la corbeille."""
        dc.mettre_en_attente(self.drive, "54868421", None,
                             "lendemain de la commande", "", AUJOURD_HUI)
        for file_id, numero, cible in dc.lister_marqueurs_attente(self.drive):
            ok, msg = dc.deplacer(self.drive, numero, cible)
            self.assertTrue(ok, msg)
            self.drive.files().update(fileId=file_id, body={"trashed": True}).execute()

        self.assertEqual(_parents(self.drive, "f1"), ["j25"])
        self.assertEqual(dc.lister_marqueurs_attente(self.drive), [])

    def test_suppression_en_attente_ne_supprime_rien(self):
        ok, msg = dc.mettre_en_attente_suppression(self.drive, "54868421")
        self.assertTrue(ok, msg)
        self.assertIn("22h", msg)
        self.assertFalse(self.drive.files()._par_id("f1").get("trashed"))
        self.assertEqual([(n, c) for _id, n, c in dc.lister_marqueurs_attente(self.drive)],
                         [("54868421", dc.SUPPRIMER)])

    def test_suppression_en_attente_introuvable(self):
        ok, msg = dc.mettre_en_attente_suppression(self.drive, "99999999")
        self.assertFalse(ok)
        self.assertIn("introuvable", msg)
        self.assertEqual(self._marqueurs_store(), [])

    def test_suppression_remplace_un_deplacement_en_attente(self):
        dc.mettre_en_attente(self.drive, "54868421", date(2026, 9, 26), aujourd_hui=AUJOURD_HUI)
        dc.mettre_en_attente_suppression(self.drive, "54868421")
        self.assertEqual([(n, c) for _id, n, c in dc.lister_marqueurs_attente(self.drive)],
                         [("54868421", dc.SUPPRIMER)])
        self.assertEqual(len(self._marqueurs_store()), 1)

    def test_traitement_du_soir_supprime(self):
        dc.mettre_en_attente_suppression(self.drive, "54868421")
        dc.mettre_en_attente(self.drive, "54868422", date(2026, 9, 26), aujourd_hui=AUJOURD_HUI)
        for _file_id, numero, cible in dc.lister_marqueurs_attente(self.drive):
            ok, msg = dc.traiter_marqueur(self.drive, numero, cible)
            self.assertTrue(ok, msg)
        self.assertTrue(self.drive.files()._par_id("f1").get("trashed"))
        self.assertEqual(_parents(self.drive, "f2"), [next(
            f["id"] for f in self.drive.files().store if f["name"] == "26_09")])


class TestSupprimer(unittest.TestCase):
    """--supprimer --forcer : suppression immediate (corbeille Drive)."""

    def setUp(self):
        self._bdc = ap.DRIVE_BDC_FOLDER_ID
        ap.DRIVE_BDC_FOLDER_ID = BDC_ID
        self.drive = _FakeDrive(_store())

    def tearDown(self):
        ap.DRIVE_BDC_FOLDER_ID = self._bdc

    def test_supprime_tous_les_exemplaires(self):
        self.drive.files().store.append(_bdc("f1bis", "54868421", "j25"))
        ok, msg = dc.supprimer(self.drive, "54868421", None, "lendemain", "", AUJOURD_HUI)
        self.assertTrue(ok, msg)
        self.assertTrue(self.drive.files()._par_id("f1").get("trashed"))
        self.assertTrue(self.drive.files()._par_id("f1bis").get("trashed"))
        self.assertFalse(self.drive.files()._par_id("f2").get("trashed"))

    def test_depot_manuel_non_supprime(self):
        self.drive.files().store.append(_bdc("fm", "54868421", "manuel"))
        dc.supprimer(self.drive, "54868421")
        self.assertFalse(self.drive.files()._par_id("fm").get("trashed"))

    def test_introuvable(self):
        ok, msg = dc.supprimer(self.drive, "99999999")
        self.assertFalse(ok)
        self.assertIn("introuvable", msg)

    def test_parser_args(self):
        self.assertEqual(dc._parser_args(["--numeros", "54868421", "--supprimer"]),
                         ("54868421", "", "", False, True))
        self.assertEqual(dc._parser_args(["--numeros", "54868421", "--forcer", "--supprimer"]),
                         ("54868421", "", "", True, True))


if __name__ == "__main__":
    unittest.main()
