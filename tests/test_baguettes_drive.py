#!/usr/bin/env python3
"""
Tests des 4 baguettes tradition du Drive ajoutees d'office a la page BVP de
l'anticipation du jour : presence, non-empilement quand le PDF est regenere
(a chaque commande assemblee comme a chaque annulation), fusion avec une
baguette identique reellement commandee par un client, et absence dans
l'anticipation du lendemain generee ou lancee en amont la veille.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap
import anticipation_commandes as ac


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
        return _FakeRequete({"files": [{"id": "id_pdf"}]})


class _FakeDrive:
    def __init__(self):
        self._files = _FakeFiles()

    def files(self):
        return self._files

    @property
    def corbeille(self):
        return self._files.corbeille


# Un pain BVP (lettre C) et un jouet bazar (lettre A) : de quoi avoir une page
# BVP a laquelle ajouter les baguettes, et une page sans elles.
BON_BVP   = "3256220303001;PAIN DE MIE;2,10;;1;;0;;;LUN 18:00;2;RAYON BVP;;;;C"
BON_BAZAR = "3256228404473;JOUET;9,90;;1;;0;;;LUN 19:00;1;RAYON BAZAR;;;;A"
# Meme gencod que les baguettes du Drive, mais commande par un vrai client.
BON_BAGUETTE_CLIENT = (
    f"{ac._GENCOD_BAGUETTE_DRIVE};BAGUETTE TRADITION;1,05;;2;;0;;;LUN 07:00;"
    f"1;RAYON BVP;;;;C"
)

BROUILLON = f"#CDE:54764266\n{BON_BVP}\n#CDE:54770396\n{BON_BAZAR}\n"


class TestBaguettesDrivePDF(unittest.TestCase):
    def setUp(self):
        self.drive = _FakeDrive()
        self.generations = []
        self._patchs = []

        def _patch(module, nom, valeur):
            self._patchs.append((module, nom, getattr(module, nom)))
            setattr(module, nom, valeur)

        _patch(ac, "_charger_ordre_chemin_prepa", lambda d: {})
        _patch(ac, "_generer_pdf_rayons",
               lambda produits_pdf, jj, date, ordre: self.generations.append(produits_pdf))
        _patch(ap, "deposer_fichier_jour_anticipation", lambda *a, **k: None)
        # Par defaut, le PDF du 10/09 est genere le 10/09 lui-meme.
        self.aujourdhui = date(2026, 9, 10)
        _patch(ac, "_aujourdhui", lambda: self.aujourdhui)

    def tearDown(self):
        for module, nom, valeur in reversed(self._patchs):
            setattr(module, nom, valeur)

    def _publier(self, contenu):
        ac.publier_pdf_jour(self.drive, "folder", contenu, "10_09", "09_2026")
        return self.generations[-1] if self.generations else None

    def _baguettes(self, produits_pdf):
        return [p for p in produits_pdf.get("C", [])
                if p["commande"] == ac._COMMANDE_BAGUETTES_DRIVE
                and p["gencod"] == ac._GENCOD_BAGUETTE_DRIVE]

    def test_les_4_baguettes_sont_sur_la_page_bvp(self):
        produits_pdf = self._publier(BROUILLON)
        baguettes = self._baguettes(produits_pdf)

        self.assertEqual(len(baguettes), 1)
        self.assertEqual(baguettes[0]["qte"], str(ac._QTE_BAGUETTES_DRIVE))
        self.assertEqual(baguettes[0]["heure"], ac._HEURE_BAGUETTES_DRIVE)
        self.assertEqual(baguettes[0]["lettre"], "C")
        # Pas de baguette glissee dans les autres rayons.
        self.assertEqual(self._baguettes({"C": produits_pdf.get("A", [])}), [])

    def test_une_seule_page_bvp_creee_quand_seul_le_bazar_est_commande(self):
        produits_pdf = self._publier(f"#CDE:54770396\n{BON_BAZAR}\n")
        self.assertEqual(len(self._baguettes(produits_pdf)), 1)
        self.assertEqual(len(produits_pdf["C"]), 1)

    def test_aucun_pdf_quand_rien_nest_a_anticiper(self):
        # Les baguettes accompagnent l'anticipation du jour : seules, elles ne
        # justifient pas un PDF (et l'ancien est mis a la corbeille).
        self.assertFalse(ac.publier_pdf_jour(self.drive, "folder", "", "10_09", "09_2026"))
        self.assertEqual(self.generations, [])
        self.assertEqual(self.drive.corbeille, ["id_pdf"])

    def test_pas_dempilement_quand_le_pdf_est_regenere(self):
        for _ in range(3):
            produits_pdf = self._publier(BROUILLON)
        self.assertEqual(len(self._baguettes(produits_pdf)), 1)

    def test_fusionnees_avec_une_baguette_commandee_par_un_client(self):
        produits_pdf = self._publier(f"#CDE:54764266\n{BON_BAGUETTE_CLIENT}\n")
        groupes = ac._grouper_produits(produits_pdf["C"])
        groupe = [g for g in groupes if g["gencod"] == ac._GENCOD_BAGUETTE_DRIVE]

        # Un seul groupe (une seule ligne du tableau), quantite totale a
        # ramasser = les 4 du Drive + les 2 du client.
        self.assertEqual(len(groupe), 1)
        self.assertEqual(ac._qte_totale(groupe[0]["lignes"]),
                         str(ac._QTE_BAGUETTES_DRIVE + 2))

    def test_pas_de_baguettes_dans_lanticipation_lancee_la_veille(self):
        # Le 09/09 a 12h55, l'anticipation du 10/09 est lancee en amont : les
        # baguettes sont pour l'anticipation du 09/09, pas pour celle-ci
        # (sinon elles repartiraient une seconde fois le 10/09).
        self.aujourdhui = date(2026, 9, 9)
        produits_pdf = self._publier(BROUILLON)
        self.assertEqual(self._baguettes(produits_pdf), [])
        self.assertEqual(len(produits_pdf["C"]), 1)

    def test_pas_de_page_bvp_creee_la_veille_quand_seul_le_bazar_est_commande(self):
        self.aujourdhui = date(2026, 9, 9)
        produits_pdf = self._publier(f"#CDE:54770396\n{BON_BAZAR}\n")
        self.assertNotIn("C", produits_pdf)

    def test_baguettes_ajoutees_le_jour_meme_au_brouillon_prepare_la_veille(self):
        self.aujourdhui = date(2026, 9, 9)
        self.assertEqual(self._baguettes(self._publier(BROUILLON)), [])
        self.aujourdhui = date(2026, 9, 10)
        self.assertEqual(len(self._baguettes(self._publier(BROUILLON))), 1)


class TestEstAnticipationDuJour(unittest.TestCase):
    def setUp(self):
        self._orig = ac._aujourdhui
        ac._aujourdhui = lambda: date(2026, 9, 23)

    def tearDown(self):
        ac._aujourdhui = self._orig

    def test_jour_meme(self):
        self.assertTrue(ac._est_anticipation_du_jour("23_09", "09_2026"))

    def test_lendemain(self):
        self.assertFalse(ac._est_anticipation_du_jour("24_09", "09_2026"))

    def test_meme_jour_autre_annee(self):
        self.assertFalse(ac._est_anticipation_du_jour("23_09", "09_2025"))

    def test_dossier_invalide(self):
        self.assertFalse(ac._est_anticipation_du_jour("xx", "09_2026"))


if __name__ == "__main__":
    unittest.main()
