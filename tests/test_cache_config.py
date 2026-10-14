"""Cache de la config d'adressage entre les runs (CONFIG_CACHE_DIR) : un
fichier inchangé sur Drive (même md5) n'est pas retéléchargé ; un fichier
mis à jour sur Drive l'est, et le workflow est prévenu (config_maj)."""
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap

NOMS = ap.CONFIG_FILES + ["prepa_drive_degrade"]


class _Req:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


class _FakeDrive:
    def __init__(self, contenus):
        self.contenus = contenus  # {nom: bytes} sur Drive

    def files(self):
        return self

    def list(self, q=None, fields=None, pageSize=None):
        if "name='" in q:
            nom = q.split("name='", 1)[1].split("'", 1)[0]
            return _Req({"files": [{"id": nom}] if nom in self.contenus else []})
        return _Req({"files": [{"name": n, "md5Checksum": hashlib.md5(c).hexdigest()}
                               for n, c in self.contenus.items()]})


class TestCacheConfig(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.cache = tempfile.mkdtemp()
        self.sortie = os.path.join(tempfile.mkdtemp(), "out")
        self.telecharges = []
        self.drive = _FakeDrive({n: f"v1 {n}".encode() for n in NOMS})

        def faux_download(svc, file_id, dest):
            self.telecharges.append(file_id)
            with open(dest, "wb") as fh:
                fh.write(svc.contenus[file_id])

        for p in (mock.patch.object(ap, "WORK_DIR", self.work),
                  mock.patch.object(ap, "download_pdf", faux_download),
                  mock.patch.dict(os.environ, {"CONFIG_CACHE_DIR": self.cache,
                                               "GITHUB_OUTPUT": self.sortie})):
            p.start()
            self.addCleanup(p.stop)

    def _config_maj(self):
        return os.path.exists(self.sortie) and "config_maj=true" in open(self.sortie).read()

    def test_premier_run_telecharge_tout_et_remplit_le_cache(self):
        ap.telecharger_config_drive(self.drive)
        self.assertEqual(sorted(self.telecharges), sorted(NOMS))
        self.assertTrue(self._config_maj())
        self.assertEqual(ap.config_manquante(), [])

    def test_cache_a_jour_rien_n_est_telecharge(self):
        ap.telecharger_config_drive(self.drive)
        os.remove(self.sortie)
        self.telecharges.clear()
        for n in NOMS:
            os.remove(os.path.join(self.work, n))  # nouveau run : WORK_DIR vide
        ap.telecharger_config_drive(self.drive)
        self.assertEqual(self.telecharges, [])
        self.assertFalse(self._config_maj())
        self.assertEqual(ap.config_manquante(), [])
        self.assertTrue(os.access(os.path.join(self.work, "prepa_drive_degrade"), os.X_OK))

    def test_fichier_mis_a_jour_sur_drive_est_retelecharge(self):
        ap.telecharger_config_drive(self.drive)
        os.remove(self.sortie)
        self.telecharges.clear()
        self.drive.contenus["chemin_prepa_ramasse.csv"] = b"v2 nouveau chemin"
        ap.telecharger_config_drive(self.drive)
        self.assertEqual(self.telecharges, ["chemin_prepa_ramasse.csv"])
        self.assertTrue(self._config_maj())
        with open(os.path.join(self.work, "chemin_prepa_ramasse.csv"), "rb") as fh:
            self.assertEqual(fh.read(), b"v2 nouveau chemin")


if __name__ == "__main__":
    unittest.main()
