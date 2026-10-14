import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moteur_ombre

BON = b"M,1,4,6,0,54.20,10h05\n3256225454952;THON;2.50\n"


class FauxMoteur:
    sortie = BON

    def __init__(self, dossier):
        self.dossier = dossier

    def executer(self, tables=None):
        print("Programme termine.")
        with open(os.path.join(self.dossier, "bon_prepa.txt"), "wb") as fh:
            fh.write(self.sortie)


class TestMoteurOmbre(unittest.TestCase):
    def setUp(self):
        moteur_ombre._tables.clear()
        self.work = tempfile.mkdtemp()
        for nom in moteur_ombre.ENTREES + ("BonDeCommande_1.pdf",):
            with open(os.path.join(self.work, nom), "wb") as fh:
                fh.write(b"x")
        p = mock.patch.object(moteur_ombre.pdd, "Moteur", FauxMoteur)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(moteur_ombre.pdd, "charger_tables", lambda d: ("t",))
        q.start()
        self.addCleanup(q.stop)

    def _bon_c(self, data):
        with open(os.path.join(self.work, "bon_prepa.txt"), "wb") as fh:
            fh.write(data)

    def _executer(self):
        dossier = moteur_ombre.preparer(self.work, "BonDeCommande_1.pdf")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = moteur_ombre.executer(None, None, "1", dossier, self.work, "", 2.0)
        self.assertFalse(os.path.exists(dossier))  # dossier temporaire nettoyé
        return res, buf.getvalue()

    def test_identique_malgre_prefixe_parasite_du_c(self):
        self._bon_c(b"M,1,4,6,0,54.20,10h05\n-3;3256225454952;THON;2.50\n")
        res, log = self._executer()
        self.assertTrue(res["identique"])
        self.assertIn("Python identique | C 2.00 s", log)

    def test_ecart_detecte_et_depot_sans_contenu_dans_le_log(self):
        self._bon_c(b"M,1,4,6,0,54.20,10h05\n3256225454952;THON;9.99\n")
        with mock.patch.object(moteur_ombre, "deposer_ecart") as dep:
            res, log = self._executer()
        self.assertFalse(res["identique"])
        self.assertIn("DIFFÉRENT : bon_prepa (1 ligne(s))", log)
        self.assertNotIn("THON", log)
        dep.assert_called_once()

    def test_plantage_python_ne_remonte_pas(self):
        self._bon_c(BON)
        with mock.patch.object(FauxMoteur, "executer", side_effect=ValueError("x")):
            res, log = self._executer()
        self.assertFalse(res["identique"])
        self.assertIn("Python EN ERREUR (ValueError)", log)

    def test_interrupteur(self):
        with mock.patch.dict(os.environ, {"MOTEUR_OMBRE": "0"}):
            self.assertFalse(moteur_ombre.actif("c"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(moteur_ombre.actif("c"))
            self.assertFalse(moteur_ombre.actif("python"))


if __name__ == "__main__":
    unittest.main()
