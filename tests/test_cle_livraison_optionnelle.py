"""Sans « livraison_spreadsheet_id » dans config.json, aut_prep ne s'arrete
pas : les bons sont generes, seules les etapes LIVRAISON sont sautees."""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap


class _Dl:
    def __init__(self, buf, _req, contenu):
        buf.write(contenu)

    def next_chunk(self):
        return None, True


class TestCleLivraisonOptionnelle(unittest.TestCase):
    def _charger(self, cfg):
        drive = mock.MagicMock()
        drive.files().list().execute.return_value = {"files": [{"id": "x"}]}
        contenu = json.dumps(cfg).encode()
        with mock.patch.object(ap, "DRIVE_CONFIG_FOLDER_ID", "dossier"), \
                mock.patch.object(ap, "MediaIoBaseDownload",
                                  lambda buf, req: _Dl(buf, req, contenu)), \
                contextlib.redirect_stdout(io.StringIO()):
            ap._charger_config(drive)
        return ap.LIVRAISON_SPREADSHEET_ID

    def test_cle_absente_pas_d_arret(self):
        cfg = {"drive_bons_folder_id": "b", "drive_bdc_folder_id": "c"}
        self.assertEqual(self._charger(cfg), "")

    def test_cle_presente(self):
        cfg = {"drive_bons_folder_id": "b", "drive_bdc_folder_id": "c",
               "livraison_spreadsheet_id": " ID "}
        self.assertEqual(self._charger(cfg), "ID")


if __name__ == "__main__":
    unittest.main()
