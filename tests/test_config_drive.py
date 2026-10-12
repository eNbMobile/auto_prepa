#!/usr/bin/env python3
"""
Tests du telechargement de la config depuis Drive.

Le 12/10/2026, une erreur 500 passagere de Drive a empeche de telecharger le
binaire prepa_drive_degrade : le run a quand meme recupere l'email de la
commande 56158358 (libellise, donc jamais repris) puis plante faute de
binaire, sans bon ni alerte. Desormais l'erreur est retentee, et si le binaire
manque toujours, les commandes ne sont pas recuperees.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap


class _Requete:
    def __init__(self, drive, q):
        self._drive = drive
        self._q = q

    def execute(self):
        nom = self._q.split("'")[1]
        self._drive.appels.append(nom)
        if self._drive.echecs.get(nom, 0) > 0:
            self._drive.echecs[nom] -= 1
            raise RuntimeError("HttpError 500 Internal Error")
        return {"files": [{"id": nom}]}


class _Files:
    def __init__(self, drive):
        self._drive = drive

    def list(self, q=None, fields=None):
        return _Requete(self._drive, q)


class _FakeDrive:
    def __init__(self, echecs):
        self.echecs = dict(echecs)
        self.appels = []

    def files(self):
        return _Files(self)


def _faux_download(drive_svc, file_id, dest):
    with open(dest, "w") as f:
        f.write("contenu")


class TestTelechargerConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patches = [
            mock.patch.object(ap, "WORK_DIR", self._tmp.name),
            mock.patch.object(ap, "download_pdf", _faux_download),
            mock.patch.object(ap.time, "sleep", lambda s: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_erreur_passagere_retentee(self):
        drive = _FakeDrive({"prepa_drive_degrade": 2})
        ap.telecharger_config_drive(drive)
        self.assertEqual(drive.appels.count("prepa_drive_degrade"), 3)
        self.assertEqual(ap.config_manquante(), [])

    def test_erreur_persistante_signalee(self):
        drive = _FakeDrive({"prepa_drive_degrade": 99})
        ap.telecharger_config_drive(drive)
        self.assertEqual(drive.appels.count("prepa_drive_degrade"),
                         ap.CONFIG_TENTATIVES)
        self.assertEqual(ap.config_manquante(), ["prepa_drive_degrade"])

    def test_fichier_vide_signale(self):
        ap.telecharger_config_drive(_FakeDrive({}))
        open(os.path.join(self._tmp.name, "gencod_adresses.csv"), "w").close()
        self.assertEqual(ap.config_manquante(), ["gencod_adresses.csv"])


if __name__ == "__main__":
    unittest.main()
