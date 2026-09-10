#!/usr/bin/env python3
"""
Tests de non-regression sur les commandes annulees/remplacees qui
reapparaissaient en double dans l'anticipation du jour (ancien numero +
nouveau numero pour le meme client et le meme creneau).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap
import anticipation_commandes as ac
import assembler_anticipation as aa


def _lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


class _FakeRequete:
    def __init__(self, resultat=None, journal=None, trace=None):
        self._resultat = resultat if resultat is not None else {}
        self._journal = journal
        self._trace = trace

    def execute(self):
        if self._journal is not None and self._trace is not None:
            self._journal.append(self._trace)
        return self._resultat


class _FakeFiles:
    """Ne retient que ce dont les tests ont besoin : les mises a la corbeille."""

    def __init__(self):
        self.corbeille = []

    def update(self, fileId=None, body=None, media_body=None):
        trace = fileId if (body or {}).get("trashed") else None
        return _FakeRequete(journal=self.corbeille if trace else None, trace=trace)

    def list(self, **kwargs):
        return _FakeRequete({"files": []})


class _FakeDrive:
    def __init__(self):
        self._files = _FakeFiles()

    def files(self):
        return self._files

    @property
    def corbeille(self):
        return self._files.corbeille


BON_54764266 = "3256630303000;LESSIVE;12,50;1,50;1;;0;;;LUN 18:00;2;RAYON;;;;C"
BON_54764433 = "3256630303000;LESSIVE;12,50;1,50;1;;0;;;LUN 18:00;2;RAYON;;;;C"
BON_54770396 = "3256228404473;JOUET;9,90;;1;;0;;;LUN 19:00;1;RAYON;;;;A"

BROUILLON = (
    f"#CDE:54764266\n{BON_54764266}\n"
    f"#CDE:54764433\n{BON_54764433}\n"
    f"#CDE:54770396\n{BON_54770396}\n"
)


class TestRetirerBlocs(unittest.TestCase):
    def test_retire_le_bloc_de_la_commande_annulee(self):
        restant = ac.retirer_blocs_commandes(BROUILLON, {"54764266"})
        self.assertNotIn("#CDE:54764266", restant)
        self.assertIn("#CDE:54764433", restant)
        self.assertIn("#CDE:54770396", restant)
        self.assertEqual(ac._commandes_deja_assemblees(restant), {"54764433", "54770396"})

    def test_sans_annulation_le_contenu_est_conserve(self):
        self.assertEqual(
            ac._commandes_deja_assemblees(ac.retirer_blocs_commandes(BROUILLON, set())),
            {"54764266", "54764433", "54770396"})


class TestAppliquerAnnulationsJour(unittest.TestCase):
    def setUp(self):
        self.drive = _FakeDrive()
        self.deposes = []
        self.pdf_publies = []
        self._patchs = []

        def _patch(module, nom, valeur):
            self._patchs.append((module, nom, getattr(module, nom)))
            setattr(module, nom, valeur)

        _patch(ac, "numeros_annules", lambda d, f, sup=(): {"54764266"} | set(sup))
        _patch(ac, "_lister_bons_commande",
               lambda d, f: [("id_66", "54764266"), ("id_33", "54764433")])
        _patch(ac, "telecharger_texte_dossier", lambda d, f, n: (BROUILLON, "id_jour"))
        _patch(ac, "_retirer_commandes_fichier_anticipees", lambda *a, **k: None)
        _patch(ac, "publier_pdf_jour",
               lambda d, f, contenu, jj, mm: self.pdf_publies.append(contenu))
        _patch(ap, "deposer_fichier_jour_anticipation",
               lambda d, chemin, mm, jj: self.deposes.append(_lire(chemin)))

    def tearDown(self):
        for module, nom, valeur in reversed(self._patchs):
            setattr(module, nom, valeur)

    def test_retire_la_commande_annulee_et_son_bon_individuel(self):
        retires = []
        annules, restant, modifie = ac.appliquer_annulations_jour(
            self.drive, "folder", "09_2026", "10_09", retires_out=retires)

        self.assertTrue(modifie)
        self.assertEqual(retires, ["54764266"])
        self.assertIn("54764266", annules)
        self.assertNotIn("#CDE:54764266", restant)
        self.assertIn("#CDE:54764433", restant)
        # le bon individuel part a la corbeille, sinon l'assemblage suivant le
        # reintegrerait (c'est exactement ce qui recreait le doublon)
        self.assertIn("id_66", self.drive.corbeille)
        self.assertNotIn("id_33", self.drive.corbeille)
        self.assertEqual(len(self.deposes), 1)
        self.assertNotIn("#CDE:54764266", self.deposes[0])
        self.assertEqual(len(self.pdf_publies), 1)

    def test_pdf_non_regenere_quand_l_appelant_s_en_charge(self):
        ac.appliquer_annulations_jour(self.drive, "folder", "09_2026", "10_09",
                                      regenerer_pdf=False)
        self.assertEqual(self.pdf_publies, [])

    def test_rien_a_faire_quand_aucune_annulee_n_est_presente(self):
        ac.numeros_annules = lambda d, f, sup=(): {"99999999"}
        ac._lister_bons_commande = lambda d, f: []
        _, restant, modifie = ac.appliquer_annulations_jour(
            self.drive, "folder", "09_2026", "10_09")
        self.assertFalse(modifie)
        self.assertEqual(restant, BROUILLON)
        self.assertEqual(self.deposes, [])


class TestAssemblageIgnoreLesAnnulees(unittest.TestCase):
    """Le scenario de l'incident : la commande remplacee (54764266) a bien un
    bon_anticipation_NUMERO.txt sur Drive — depose apres son annulation, son
    email de confirmation n'ayant ete traite qu'ensuite — et l'assembleur ne
    doit en aucun cas l'integrer."""

    def setUp(self):
        self._patchs = []
        self.contenu_final = []
        self.pdf_publies = []

        def _patch(module, nom, valeur):
            self._patchs.append((module, nom, getattr(module, nom)))
            setattr(module, nom, valeur)

        _patch(ap, "get_credentials", lambda: None)
        _patch(aa, "build", lambda *a, **k: _FakeDrive())
        _patch(ap, "_dossier_anticipation_jour", lambda *a, **k: "folder")
        _patch(ac, "telecharger_texte_dossier", lambda d, f, n: ("", None))
        _patch(ac, "appliquer_annulations_jour",
               lambda d, f, mm, jj, contenu_jour=None, numeros_sup=(), regenerer_pdf=True,
                      retires_out=None: ({"54764266"}, contenu_jour or "", False))
        _patch(ac, "_lister_bons_commande",
               lambda d, f: [("id_66", "54764266"), ("id_33", "54764433")])
        _patch(ac, "_telecharger_texte",
               lambda d, file_id: BON_54764266 if file_id == "id_66" else BON_54764433)
        _patch(ac, "_maj_fichier_commandes_anticipees", lambda *a, **k: None)
        _patch(ac, "publier_pdf_jour",
               lambda d, f, contenu, jj, mm: self.pdf_publies.append(contenu))
        _patch(ap, "deposer_fichier_jour_anticipation",
               lambda d, chemin, mm, jj: self.contenu_final.append(_lire(chemin)))
        os.makedirs(ap.WORK_DIR, exist_ok=True)

    def tearDown(self):
        for module, nom, valeur in reversed(self._patchs):
            setattr(module, nom, valeur)

    def test_la_commande_remplacee_n_est_jamais_assemblee(self):
        sys.argv = ["assembler_anticipation.py", "--numero", "54764433",
                    "--jour", "10_09", "--mois", "09_2026"]
        aa.main()

        self.assertEqual(len(self.contenu_final), 1)
        self.assertNotIn("#CDE:54764266", self.contenu_final[0])
        self.assertIn("#CDE:54764433", self.contenu_final[0])
        self.assertEqual(len(self.pdf_publies), 1)
        self.assertNotIn("#CDE:54764266", self.pdf_publies[0])

    def test_un_run_declenche_par_la_commande_annulee_n_echoue_pas(self):
        sys.argv = ["assembler_anticipation.py", "--numero", "54764266",
                    "--jour", "10_09", "--mois", "09_2026"]
        aa.main()  # ne doit pas sys.exit(1)
        self.assertNotIn("#CDE:54764266", self.contenu_final[0])


class TestEcarterCommandesAnnulees(unittest.TestCase):
    """Une commande annulee avant que son email de confirmation n'ait ete
    traite ne doit plus etre preparee ni anticipee du tout."""

    def setUp(self):
        self._original = ap.commandes_annulees
        ap.commandes_annulees = lambda drive_svc: {"54764266"}
        os.makedirs(ap.CACHE_DIR, exist_ok=True)
        self.cache_pdf = os.path.join(ap.CACHE_DIR, "BonDeCommande_54764266.pdf")
        with open(self.cache_pdf, "w", encoding="utf-8") as f:
            f.write("factice")

    def tearDown(self):
        ap.commandes_annulees = self._original
        if os.path.exists(self.cache_pdf):
            os.remove(self.cache_pdf)

    def test_la_commande_annulee_est_ecartee_du_traitement(self):
        nouveaux = {
            "BonDeCommande_54764266.pdf": ("10_09", "09_2026"),
            "BonDeCommande_54764433.pdf": ("10_09", "09_2026"),
        }
        retenus = ap._ecarter_commandes_annulees(None, nouveaux)
        self.assertEqual(list(retenus), ["BonDeCommande_54764433.pdf"])
        self.assertFalse(os.path.exists(self.cache_pdf))


if __name__ == "__main__":
    unittest.main()
