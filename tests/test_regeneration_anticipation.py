#!/usr/bin/env python3
"""
Tests de la regeneration d'une commande deja assemblee dans l'anticipation du
jour.

Le 12/10/2026, la commande 56158358 a ete redeposee apres l'ajout d'une regle
de detection BVP (baguettes au mais absentes de gencod_nomenclatures) : son
nouveau bon_anticipation_NUMERO.txt n'aurait jamais remplace l'ancien bloc
'#CDE:' deja present dans bon_anticipation_JJ_MM.txt, l'assembleur ignorant
toute commande deja assemblee. Avec --regenerer, le bloc est remplace (ou
retire si la commande n'anticipe plus rien).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap
import anticipation_commandes as ac
import assembler_anticipation as aa
from test_annulations_anticipation import _FakeDrive, _lire

ANCIEN = "3760242644772;COMBUSTIBLE;29,99;1,50;2;;0;;;MAR 12:00;2;RAYON;;;;A"
NOUVEAU_BAGUETTE = "2000000000000;BAGUETTE MAIS;1,20;;3;;0;;;MAR 12:00;1;BVP;;;;U"
AUTRE = "3256228404473;JOUET;9,90;;1;;0;;;MAR 14:00;1;RAYON;;;;A"

BROUILLON = (
    f"#CDE:56158358\n{ANCIEN}\n"
    f"#CDE:56165370\n{AUTRE}\n"
)


class TestAssemblageRegeneration(unittest.TestCase):
    def setUp(self):
        self._patchs = []
        self.contenu_final = []
        self.pdf_publies = []
        self.bons = {"id_58": ANCIEN + "\n" + NOUVEAU_BAGUETTE, "id_70": AUTRE}
        self.liste_bons = [("id_58", "56158358"), ("id_70", "56165370")]

        def _patch(module, nom, valeur):
            self._patchs.append((module, nom, getattr(module, nom)))
            setattr(module, nom, valeur)

        _patch(ap, "get_credentials", lambda: None)
        _patch(aa, "build", lambda *a, **k: _FakeDrive())
        _patch(ap, "_dossier_anticipation_jour", lambda *a, **k: "folder")
        _patch(ac, "telecharger_texte_dossier", lambda d, f, n: (BROUILLON, "id_jour"))
        _patch(ac, "appliquer_annulations_jour",
               lambda d, f, mm, jj, contenu_jour=None, numeros_sup=(), regenerer_pdf=True,
                      retires_out=None: (set(), contenu_jour or "", False))
        _patch(ac, "_lister_bons_commande", lambda d, f: list(self.liste_bons))
        _patch(ac, "_telecharger_texte", lambda d, file_id: self.bons[file_id])
        _patch(ac, "_maj_fichier_commandes_anticipees", lambda *a, **k: None)
        _patch(ac, "publier_pdf_jour",
               lambda d, f, contenu, jj, mm: self.pdf_publies.append(contenu))
        _patch(ap, "deposer_fichier_jour_anticipation",
               lambda d, chemin, mm, jj: self.contenu_final.append(_lire(chemin)))
        os.makedirs(ap.WORK_DIR, exist_ok=True)
        self._argv = sys.argv

    def tearDown(self):
        sys.argv = self._argv
        for module, nom, valeur in reversed(self._patchs):
            setattr(module, nom, valeur)

    def _lancer(self, *options):
        sys.argv = ["assembler_anticipation.py", "--numero", "56158358",
                    "--jour", "13_10", "--mois", "10_2026", *options]
        aa.main()

    def test_sans_regenerer_le_bloc_existant_est_conserve(self):
        self._lancer()
        self.assertEqual(self.contenu_final, [])
        self.assertEqual(self.pdf_publies, [])

    def test_regenerer_remplace_le_bloc(self):
        self._lancer("--regenerer")

        self.assertEqual(len(self.contenu_final), 1)
        contenu = self.contenu_final[0]
        self.assertEqual(contenu.count("#CDE:56158358"), 1)
        self.assertIn(NOUVEAU_BAGUETTE, contenu)
        self.assertEqual(contenu.count(ANCIEN), 1)
        # L'autre commande du jour n'est pas touchee.
        self.assertEqual(contenu.count("#CDE:56165370"), 1)
        self.assertEqual(len(self.pdf_publies), 1)
        self.assertIn(NOUVEAU_BAGUETTE, self.pdf_publies[0])

    def test_regenerer_sans_plus_rien_a_anticiper_retire_le_bloc(self):
        self.liste_bons = [("id_70", "56165370")]
        self._lancer("--regenerer")  # ne doit pas sys.exit(1)

        self.assertEqual(len(self.contenu_final), 1)
        self.assertNotIn("#CDE:56158358", self.contenu_final[0])
        self.assertIn("#CDE:56165370", self.contenu_final[0])
        self.assertNotIn("#CDE:56158358", self.pdf_publies[0])


if __name__ == "__main__":
    unittest.main()
