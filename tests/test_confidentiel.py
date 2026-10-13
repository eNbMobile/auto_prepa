import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import confidentiel


def _sortie(fonction, *args, github=True):
    confidentiel._deja_masques.clear()
    env = {"GITHUB_ACTIONS": "true"} if github else {}
    buf = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(buf):
        fonction(*args)
    return buf.getvalue().splitlines()


class TestConfidentiel(unittest.TestCase):
    def test_masque_nom_et_chaque_mot(self):
        lignes = _sortie(confidentiel.masquer, "PEYROT SEILLIER", "Eloane")
        self.assertIn("::add-mask::PEYROT SEILLIER", lignes)
        self.assertIn("::add-mask::PEYROT", lignes)
        self.assertIn("::add-mask::SEILLIER", lignes)
        self.assertIn("::add-mask::ELOANE", lignes)
        self.assertIn("::add-mask::Eloane", lignes)

    def test_ignore_valeurs_trop_courtes(self):
        self.assertEqual(_sortie(confidentiel.masquer, "LY", "", None), [])

    def test_rien_hors_github_actions(self):
        self.assertEqual(_sortie(confidentiel.masquer, "DUPONT", github=False), [])
        self.assertEqual(_sortie(confidentiel.masquer_config, {"a": "secretvaleur"}, github=False), [])

    def test_masque_toute_la_config(self):
        cfg = {"email_destinataire": "drive@exemple.fr",
               "liste": ["Confirmation de commande"],
               "sous": {"id": "1AbCdEfGhIjKlMnOp"},
               "actif": True, "n": 3}
        lignes = _sortie(confidentiel.masquer_config, cfg)
        self.assertEqual(sorted(lignes), sorted([
            "::add-mask::drive@exemple.fr",
            "::add-mask::Confirmation de commande",
            "::add-mask::1AbCdEfGhIjKlMnOp",
        ]))

    def test_cle_obligatoire(self):
        self.assertEqual(confidentiel.cle_obligatoire({"k": " v "}, "k"), "v")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            confidentiel.cle_obligatoire({"k": ""}, "k")


if __name__ == "__main__":
    unittest.main()
