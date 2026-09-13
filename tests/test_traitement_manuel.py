#!/usr/bin/env python3
"""
Tests du filet de secours "traitement manuel" : un bon de commande depose a la
main dans le dossier Drive GITHUB/BDC/Traitement manuel doit etre traite comme
s'il etait arrive en piece jointe d'un email de confirmation.

Lancement : python3 -m unittest discover -s tests
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap

BDC_ID = "id_bdc"
BONS_ID = "id_bons"
MANUEL_ID = "id_manuel"

TEXTE_BON = """\
Commande : 54868421 - H9 99008447250800 LIVRAISON PAIEMENT EN LIGNE

Mme WADY FATENE                    BON D'ENCAISSEMENT

                                   SAMEDI 12/09/2026      13h00 - 14h00

Total de la commande 37 articles 78 produits
"""

DOSSIER_MANUEL = {"id": MANUEL_ID, "name": "traitement manuel", "parents": [BDC_ID],
                  "mimeType": "application/vnd.google-apps.folder"}

# GITHUB/Avoir/Commandes en cours : trace qu'une commande a ete preparee.
SUIVI_AVOIR = [
    {"id": "id_github", "name": "GITHUB", "parents": ["root"],
     "mimeType": "application/vnd.google-apps.folder"},
    {"id": "id_avoir", "name": "Avoir", "parents": ["id_github"],
     "mimeType": "application/vnd.google-apps.folder"},
    {"id": "id_sheet", "name": ap.AVOIR_SHEET_FILENAME, "parents": ["id_avoir"],
     "mimeType": "application/vnd.google-apps.spreadsheet"},
]
CSV_AVOIR = ("Civilité,N° commande,Nom,Prénom,Date,Créneau\r\n"
             "Mme,54868421,WADY,FATENE,12/09/2026,13h00 - 14h00\r\n")


class _FakeRequete:
    def __init__(self, resultat=None, effet=None):
        self._resultat = resultat if resultat is not None else {}
        self._effet = effet

    def execute(self):
        if self._effet is not None:
            self._effet()
        return self._resultat


class _FakeExport:
    """Imite MediaIoBaseDownload sur un export CSV : ecrit le contenu d'un coup."""

    def __init__(self, contenu):
        self.contenu = contenu


class _FakeDownloader:
    def __init__(self, buf, requete):
        self._buf = buf
        self._requete = requete

    def next_chunk(self):
        self._buf.write(self._requete.contenu.encode("utf-8"))
        return None, True


class _FakeFiles:
    """Mini moteur Drive : filtre le store sur les seuls criteres utilises par
    auto_prepa (parents, mimeType, name)."""

    def __init__(self, store, suivi_avoir=""):
        self.store = store
        self.suivi_avoir = suivi_avoir
        self.corbeille = []

    def export_media(self, fileId=None, mimeType=None):
        return _FakeExport(self.suivi_avoir)

    def list(self, q="", fields=None, **kwargs):
        resultats = []
        m_parent = re.search(r"'([^']+)' in parents", q)
        m_mime = re.search(r"mimeType='([^']+)'", q)
        m_name = re.search(r"name='([^']+)'", q)
        corbeille_demandee = "trashed=true" in q
        for f in self.store:
            if bool(f.get("trashed")) != corbeille_demandee:
                continue
            if m_parent and m_parent.group(1) not in f.get("parents", []):
                continue
            if m_mime and f.get("mimeType") != m_mime.group(1):
                continue
            if m_name and f.get("name") != m_name.group(1):
                continue
            resultats.append(dict(f))
        return _FakeRequete({"files": resultats})

    def update(self, fileId=None, body=None, **kwargs):
        def _effet():
            if (body or {}).get("trashed"):
                self.corbeille.append(fileId)
                for f in self.store:
                    if f["id"] == fileId:
                        f["trashed"] = True
        return _FakeRequete(effet=_effet)


class _FakeDrive:
    def __init__(self, store, suivi_avoir=""):
        self._files = _FakeFiles(store, suivi_avoir)

    def files(self):
        return self._files

    @property
    def corbeille(self):
        return self._files.corbeille


def _faux_download(drive_svc, file_id, dest):
    with open(dest, "wb") as f:
        f.write(b"%PDF")


class _FakeSortie:
    def __init__(self, stdout):
        self.stdout = stdout


class TestNumeroBonDepose(unittest.TestCase):
    def test_numero_lu_dans_le_nom(self):
        self.assertEqual(
            ap._numero_bon_depose("BonDeCommande_54868421.pdf", ""), "54868421")

    def test_numero_lu_dans_le_pdf_si_nom_non_parlant(self):
        self.assertEqual(
            ap._numero_bon_depose("bon_encaissement (1).pdf", TEXTE_BON), "54868421")

    def test_le_pdf_prime_sur_un_nombre_quelconque_du_nom(self):
        """Un nom du type '20260912_bon.pdf' ne doit pas passer pour un numero."""
        self.assertEqual(
            ap._numero_bon_depose("20260912_bon.pdf", TEXTE_BON), "54868421")

    def test_nombre_du_nom_en_dernier_recours(self):
        self.assertEqual(
            ap._numero_bon_depose("cde 54868421.pdf", ""), "54868421")

    def test_aucun_numero(self):
        self.assertEqual(ap._numero_bon_depose("bon.pdf", "texte sans numero"), "")


class TestDossierTraitementManuel(unittest.TestCase):
    def setUp(self):
        ap.DRIVE_BDC_FOLDER_ID = BDC_ID
        ap.DRIVE_BONS_FOLDER_ID = BONS_ID

    def test_trouve_quelle_que_soit_la_casse(self):
        drive = _FakeDrive([dict(DOSSIER_MANUEL)])
        self.assertEqual(ap._dossier_traitement_manuel(drive), MANUEL_ID)

    def test_trouve_aussi_sous_le_dossier_des_bons(self):
        drive = _FakeDrive([
            {"id": MANUEL_ID, "name": "Traitement manuel", "parents": [BONS_ID],
             "mimeType": "application/vnd.google-apps.folder"},
        ])
        self.assertEqual(ap._dossier_traitement_manuel(drive), MANUEL_ID)

    def test_absent(self):
        drive = _FakeDrive([
            {"id": "autre", "name": "09_2026", "parents": [BDC_ID],
             "mimeType": "application/vnd.google-apps.folder"},
        ])
        self.assertIsNone(ap._dossier_traitement_manuel(drive))


class TestCommandeDejaTraitee(unittest.TestCase):
    def setUp(self):
        self._download = ap.MediaIoBaseDownload
        ap.MediaIoBaseDownload = _FakeDownloader

    def tearDown(self):
        ap.MediaIoBaseDownload = self._download

    def test_le_depot_lui_meme_ne_compte_pas(self):
        drive = _FakeDrive([
            {"id": "f1", "name": "BonDeCommande_54868421.pdf", "parents": [MANUEL_ID],
             "mimeType": "application/pdf"},
        ] + SUIVI_AVOIR, CSV_AVOIR)
        self.assertFalse(
            ap._commande_deja_traitee(drive, "54868421", ignorer_parents=(MANUEL_ID,)))

    def test_bon_archive_et_commande_suivie(self):
        drive = _FakeDrive([
            {"id": "f1", "name": "BonDeCommande_54868421.pdf", "parents": [MANUEL_ID],
             "mimeType": "application/pdf"},
            {"id": "f2", "name": "BonDeCommande_54868421.pdf", "parents": ["id_jour"],
             "mimeType": "application/pdf"},
        ] + SUIVI_AVOIR, CSV_AVOIR)
        self.assertTrue(
            ap._commande_deja_traitee(drive, "54868421", ignorer_parents=(MANUEL_ID,)))

    def test_bon_archive_mais_generation_echouee(self):
        """PDF archive sans ligne de suivi : la generation a echoue juste apres
        l'archivage, la commande reste a preparer."""
        drive = _FakeDrive([
            {"id": "f2", "name": "BonDeCommande_54868421.pdf", "parents": ["id_jour"],
             "mimeType": "application/pdf"},
        ] + SUIVI_AVOIR, "Civilité,N° commande,Nom,Prénom,Date,Créneau\r\n")
        self.assertFalse(
            ap._commande_deja_traitee(drive, "54868421", ignorer_parents=(MANUEL_ID,)))

    def test_sans_drive(self):
        self.assertFalse(ap._commande_deja_traitee(None, "54868421"))


class TestTelechargerBonsTraitementManuel(unittest.TestCase):
    def setUp(self):
        ap.DRIVE_BDC_FOLDER_ID = BDC_ID
        ap.DRIVE_BONS_FOLDER_ID = BONS_ID
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)

        self._download = ap.download_pdf
        self._run = ap.subprocess.run
        self._media = ap.MediaIoBaseDownload
        ap.download_pdf = _faux_download
        ap.subprocess.run = lambda *a, **k: _FakeSortie(TEXTE_BON)
        ap.MediaIoBaseDownload = _FakeDownloader

    def tearDown(self):
        ap.download_pdf = self._download
        ap.subprocess.run = self._run
        ap.MediaIoBaseDownload = self._media

    def test_bon_depose_pret_a_etre_traite(self):
        drive = _FakeDrive([
            dict(DOSSIER_MANUEL),
            {"id": "depot1", "name": "BonDeCommande_54868421.pdf",
             "parents": [MANUEL_ID], "mimeType": "application/pdf"},
        ])
        nouveaux, depots = ap.telecharger_bons_traitement_manuel(drive, self.cache)

        self.assertEqual(nouveaux, {"BonDeCommande_54868421.pdf": ("12_09", "09_2026")})
        self.assertEqual(depots, {"BonDeCommande_54868421.pdf": "depot1"})
        self.assertTrue(os.path.exists(
            os.path.join(self.cache, "BonDeCommande_54868421.pdf")))
        # Le depot n'est mis a la corbeille qu'une fois la commande traitee.
        self.assertEqual(drive.corbeille, [])

    def test_numero_absent_du_nom_du_fichier(self):
        drive = _FakeDrive([
            dict(DOSSIER_MANUEL),
            {"id": "depot1", "name": "bon_encaissement.pdf",
             "parents": [MANUEL_ID], "mimeType": "application/pdf"},
        ])
        nouveaux, depots = ap.telecharger_bons_traitement_manuel(drive, self.cache)
        self.assertEqual(list(nouveaux), ["BonDeCommande_54868421.pdf"])
        self.assertEqual(list(depots.values()), ["depot1"])

    def test_commande_deja_traitee_mise_a_la_corbeille(self):
        drive = _FakeDrive([
            dict(DOSSIER_MANUEL),
            {"id": "depot1", "name": "BonDeCommande_54868421.pdf",
             "parents": [MANUEL_ID], "mimeType": "application/pdf"},
            {"id": "archive", "name": "BonDeCommande_54868421.pdf",
             "parents": ["id_jour"], "mimeType": "application/pdf"},
        ] + SUIVI_AVOIR, CSV_AVOIR)
        nouveaux, depots = ap.telecharger_bons_traitement_manuel(drive, self.cache)

        self.assertEqual(nouveaux, {})
        self.assertEqual(depots, {})
        self.assertEqual(drive.corbeille, ["depot1"])
        self.assertFalse(os.path.exists(
            os.path.join(self.cache, "BonDeCommande_54868421.pdf")))

    def test_depot_repris_apres_un_echec_de_generation(self):
        """Un run precedent a archive le PDF puis echoue avant de generer le
        bon : le depot doit etre repris, pas mis a la corbeille."""
        drive = _FakeDrive([
            dict(DOSSIER_MANUEL),
            {"id": "depot1", "name": "BonDeCommande_54868421.pdf",
             "parents": [MANUEL_ID], "mimeType": "application/pdf"},
            {"id": "archive", "name": "BonDeCommande_54868421.pdf",
             "parents": ["id_jour"], "mimeType": "application/pdf"},
        ] + SUIVI_AVOIR, "Civilité,N° commande,Nom,Prénom,Date,Créneau\r\n")
        nouveaux, depots = ap.telecharger_bons_traitement_manuel(drive, self.cache)

        self.assertEqual(nouveaux, {"BonDeCommande_54868421.pdf": ("12_09", "09_2026")})
        self.assertEqual(depots, {"BonDeCommande_54868421.pdf": "depot1"})
        self.assertEqual(drive.corbeille, [])

    def test_pdf_illisible_ignore_sans_supprimer_le_depot(self):
        ap.subprocess.run = lambda *a, **k: _FakeSortie("")
        drive = _FakeDrive([
            dict(DOSSIER_MANUEL),
            {"id": "depot1", "name": "BonDeCommande_54868421.pdf",
             "parents": [MANUEL_ID], "mimeType": "application/pdf"},
        ])
        nouveaux, depots = ap.telecharger_bons_traitement_manuel(drive, self.cache)

        self.assertEqual((nouveaux, depots), ({}, {}))
        self.assertEqual(drive.corbeille, [])
        self.assertEqual(os.listdir(self.cache), [])

    def test_date_de_livraison_absente_du_pdf(self):
        ap.subprocess.run = lambda *a, **k: _FakeSortie(
            "Commande : 54868421 - H9\nMme WADY FATENE\n")
        drive = _FakeDrive([
            dict(DOSSIER_MANUEL),
            {"id": "depot1", "name": "BonDeCommande_54868421.pdf",
             "parents": [MANUEL_ID], "mimeType": "application/pdf"},
        ])
        nouveaux, depots = ap.telecharger_bons_traitement_manuel(drive, self.cache)

        self.assertEqual((nouveaux, depots), ({}, {}))
        self.assertEqual(drive.corbeille, [])
        self.assertEqual(os.listdir(self.cache), [])

    def test_sans_dossier_de_depot(self):
        drive = _FakeDrive([])
        self.assertEqual(ap.telecharger_bons_traitement_manuel(drive, self.cache),
                         ({}, {}))


if __name__ == "__main__":
    unittest.main()
