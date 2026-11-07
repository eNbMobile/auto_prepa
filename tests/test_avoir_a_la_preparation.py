"""Verification des avoirs faite par auto_prepa a chaque commande preparee
(plus de suivi "Commandes en cours" ni de workflow verif_avoirs periodique),
et trace "commande preparee" portee par le BonDeCommande archive."""
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import auto_prepa as ap  # noqa: E402
import verif_avoirs as va  # noqa: E402


class _Req:
    def __init__(self, resultat=None, effet=None):
        self._resultat = resultat or {}
        self._effet = effet

    def execute(self):
        if self._effet:
            self._effet()
        return self._resultat


class _Files:
    def __init__(self, existants=()):
        self.existants = list(existants)
        self.crees = []
        self.maj = []

    def list(self, q="", fields=None, **kw):
        return _Req({"files": [dict(f) for f in self.existants]})

    def create(self, body=None, media_body=None, fields=None):
        return _Req({"id": "nouveau"}, effet=lambda: self.crees.append(body))

    def update(self, fileId=None, body=None, **kw):
        return _Req(effet=lambda: self.maj.append((fileId, body)))


class _Drive:
    def __init__(self, files):
        self._f = files

    def files(self):
        return self._f


class TestArchivageBonGenere(unittest.TestCase):
    def setUp(self):
        self._origines = (ap.DRIVE_BDC_FOLDER_ID, ap._get_or_create_subfolder,
                          ap.MediaFileUpload)
        ap.DRIVE_BDC_FOLDER_ID = "bdc"
        ap._get_or_create_subfolder = lambda d, parent, nom: f"{parent}/{nom}"
        ap.MediaFileUpload = lambda *a, **k: None
        fd, self.pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        self.addCleanup(os.remove, self.pdf)

    def tearDown(self):
        (ap.DRIVE_BDC_FOLDER_ID, ap._get_or_create_subfolder,
         ap.MediaFileUpload) = self._origines

    def test_propriete_posee_si_bon_genere(self):
        files = _Files()
        ap.archiver_pdf_drive(_Drive(files), self.pdf, "12_09", "09_2026", bon_genere=True)
        self.assertEqual(files.crees[0]["appProperties"], {ap.BON_GENERE_PROP: "1"})

    def test_pas_de_propriete_si_generation_echouee(self):
        files = _Files()
        ap.archiver_pdf_drive(_Drive(files), self.pdf, "12_09", "09_2026")
        self.assertNotIn("appProperties", files.crees[0])

    def test_propriete_ajoutee_sur_un_pdf_deja_archive(self):
        files = _Files([{"id": "deja"}])
        ap.archiver_pdf_drive(_Drive(files), self.pdf, "12_09", "09_2026", bon_genere=True)
        self.assertEqual(files.maj, [("deja", {"appProperties": {ap.BON_GENERE_PROP: "1"}})])
        self.assertEqual(files.crees, [])


class TestVerifierAvoirCommande(unittest.TestCase):
    def setUp(self):
        self.lectures = 0
        self.mails = []
        self._origines = (va._lire_avoirs_jaunes, va._envoyer_email_avoir, va._AVOIRS_CACHE)
        avoir = {"onglet": "SEPTEMBRE", "nom": "DUPONT", "prenom": "MARIE",
                 "montant": 7.98, "date_debut": date(2026, 9, 1),
                 "date_fin": date(2099, 12, 1), "raison": ""}

        def _lire(drive, sid, date_ref):
            self.lectures += 1
            return [avoir]

        va._lire_avoirs_jaunes = _lire
        va._envoyer_email_avoir = lambda *a: self.mails.append(a)
        va._AVOIRS_CACHE = None

    def tearDown(self):
        va._lire_avoirs_jaunes, va._envoyer_email_avoir, va._AVOIRS_CACHE = self._origines

    def _verifier(self, nom, prenom):
        va.verifier_avoir_commande(None, None, "sid", "a@b", "", "Mme", "54868421",
                                   nom, prenom, "12/09/2026", "13h00 - 14h00")

    def test_mail_si_avoir_du(self):
        self._verifier("DUPONT", "MARIE")
        self.assertEqual(len(self.mails), 1)

    def test_pas_de_mail_sans_avoir(self):
        self._verifier("MARTIN", "PAUL")
        self.assertEqual(self.mails, [])

    def test_classeur_lu_une_seule_fois_par_run(self):
        self._verifier("DUPONT", "MARIE")
        self._verifier("MARTIN", "PAUL")
        self.assertEqual(self.lectures, 1)

    def test_erreur_de_lecture_sans_exception(self):
        def _plante(*a):
            raise RuntimeError("export Drive en echec")
        va._lire_avoirs_jaunes = _plante
        self._verifier("DUPONT", "MARIE")
        self.assertEqual(self.mails, [])

    def test_sans_cle_de_config(self):
        va.verifier_avoir_commande(None, None, "", "a@b", "", "Mme", "1",
                                   "DUPONT", "MARIE", "12/09/2026", "13h00 - 14h00")
        self.assertEqual(self.lectures, 0)


if __name__ == "__main__":
    unittest.main()
