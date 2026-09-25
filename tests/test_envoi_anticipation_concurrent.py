#!/usr/bin/env python3
"""
Tests de non-regression : une commande assemblee PENDANT l'envoi de
l'anticipation du jour (assemblage et WF Anticipation lances a la meme
seconde) ne doit plus etre notee comme envoyee puis effacee sans etre partie
dans le mail (cf. commande 55376672 du 24/09/2026, roti de veau absent de
l'anticipation du 25/09).

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap
import anticipation_commandes as ac


def _lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


class _FakeRequete:
    def __init__(self, resultat=None, action=None):
        self._resultat = resultat if resultat is not None else {}
        self._action = action

    def execute(self):
        if self._action:
            self._action()
        return self._resultat


class _FakeFiles:
    """Dossier Drive du jour : {file_id: (nom, contenu)}, plus la corbeille."""

    def __init__(self, fichiers):
        self.fichiers = dict(fichiers)
        self.corbeille = []

    def update(self, fileId=None, body=None, media_body=None):
        def _action():
            if (body or {}).get("trashed"):
                self.corbeille.append(fileId)
                self.fichiers.pop(fileId, None)
        return _FakeRequete(action=_action)

    def list(self, q="", **kwargs):
        resultat = []
        for file_id, (nom, _) in self.fichiers.items():
            if f"name='{nom}'" in q or ("name contains 'annuler_anticipation_'" in q
                                        and nom.startswith("annuler_anticipation_")):
                resultat.append({"id": file_id, "name": nom})
        return _FakeRequete({"files": resultat})


class _FakeDrive:
    def __init__(self, fichiers):
        self._files = _FakeFiles(fichiers)

    def files(self):
        return self._files

    @property
    def corbeille(self):
        return self._files.corbeille


BON_BOEUF = "3256220303001;ROTI DE BOEUF;12,50;25,00;1;;0,500;;;VEN 18:00;2;BOUCHERIE;;;;B"
BON_VEAU  = "3256220303002;ROTI DE VEAU;15,00;30,00;1;;0,500;;;VEN 16:30;2;BOUCHERIE;;;;B"
BON_JOUET = "3256228404473;JOUET;9,90;;1;;0;;;VEN 19:00;1;BAZAR;;;;A"

ENVOYE = f"#CDE:55370001\n{BON_BOEUF}\n#CDE:55370002\n{BON_JOUET}\n"
AVEC_RETARDATAIRE = ENVOYE + f"#CDE:55376672\n{BON_VEAU}\n"


class TestReinitialisationApresEnvoi(unittest.TestCase):
    def setUp(self):
        self.deposes = []
        self.pdf_publies = []
        self.pdf_corbeille = []
        self._patchs = []

        def _patch(module, nom, valeur):
            self._patchs.append((module, nom, getattr(module, nom)))
            setattr(module, nom, valeur)

        _patch(ac, "numeros_annules", lambda d, f, sup=(): set())
        _patch(ac, "_lister_bons_commande", lambda d, f: [
            (fid, nom[len("bon_anticipation_"):-4])
            for fid, (nom, _) in d.files().fichiers.items()
            if nom.startswith("bon_anticipation_") and nom[17:-4].isdigit()])
        _patch(ac, "_telecharger_texte",
               lambda d, fid: d.files().fichiers[fid][1])
        _patch(ac, "publier_pdf_jour",
               lambda d, f, contenu, jj, mm: self.pdf_publies.append(contenu))
        _patch(ac, "_mettre_pdf_jour_a_la_corbeille",
               lambda d, f, jj: self.pdf_corbeille.append(jj))
        _patch(ap, "deposer_fichier_jour_anticipation",
               lambda d, chemin, mm, jj: self.deposes.append(
                   (os.path.basename(chemin), _lire(chemin))))

    def tearDown(self):
        for module, nom, valeur in reversed(self._patchs):
            setattr(module, nom, valeur)

    def _drive(self, contenu_jour, *numeros):
        fichiers = {"id_jour": ("bon_anticipation_25_09.txt", contenu_jour)}
        for num in numeros:
            fichiers[f"id_{num}"] = (f"bon_anticipation_{num}.txt", "")
        return _FakeDrive(fichiers)

    def test_commande_assemblee_pendant_lenvoi_reste_dans_le_brouillon(self):
        drive = self._drive(AVEC_RETARDATAIRE, "55370001", "55370002", "55376672")

        orphelins, arrivees = ac._reinitialiser_dossier_jour_anticipation(
            drive, "folder", "25_09", "09_2026", ENVOYE)

        self.assertEqual(orphelins, [])
        self.assertEqual(arrivees, ["55376672"])
        # Le brouillon ne contient plus que la commande non envoyee...
        self.assertEqual(len(self.deposes), 1)
        nom, contenu = self.deposes[0]
        self.assertEqual(nom, "bon_anticipation_25_09.txt")
        self.assertEqual(ac._commandes_deja_assemblees(contenu), {"55376672"})
        self.assertIn("ROTI DE VEAU", contenu)
        # ... et son PDF est regenere pour elle seule.
        self.assertEqual(len(self.pdf_publies), 1)
        self.assertEqual(ac._commandes_deja_assemblees(self.pdf_publies[0]), {"55376672"})
        self.assertEqual(self.pdf_corbeille, [])
        # Seuls les bons reellement envoyes partent a la corbeille.
        self.assertIn("id_55370001", drive.corbeille)
        self.assertIn("id_55370002", drive.corbeille)
        self.assertNotIn("id_55376672", drive.corbeille)
        self.assertNotIn("id_jour", drive.corbeille)

    def test_sans_retardataire_le_dossier_est_vide(self):
        drive = self._drive(ENVOYE, "55370001", "55370002")

        orphelins, arrivees = ac._reinitialiser_dossier_jour_anticipation(
            drive, "folder", "25_09", "09_2026", ENVOYE)

        self.assertEqual((orphelins, arrivees), ([], []))
        self.assertEqual(self.deposes, [])
        self.assertEqual(self.pdf_publies, [])
        self.assertEqual(self.pdf_corbeille, ["25_09"])
        self.assertEqual(set(drive.corbeille), {"id_jour", "id_55370001", "id_55370002"})

    def test_bon_jamais_assemble_reste_orphelin(self):
        drive = self._drive(ENVOYE, "55370001", "55370002", "55379999")

        orphelins, arrivees = ac._reinitialiser_dossier_jour_anticipation(
            drive, "folder", "25_09", "09_2026", ENVOYE)

        self.assertEqual((orphelins, arrivees), (["55379999"], []))
        self.assertNotIn("id_55379999", drive.corbeille)


class TestEnvoiAnticipation(unittest.TestCase):
    """main() envoie le PDF genere a partir d'UNE lecture du brouillon et ne
    note comme envoyees que les commandes de cette lecture."""

    def setUp(self):
        self._patchs = []
        self.pdf_generes = []
        self.envoyees = []
        self.reinit = []
        self.alertes_arrivees = []

        def _patch(module, nom, valeur):
            self._patchs.append((module, nom, getattr(module, nom)))
            setattr(module, nom, valeur)

        self._patch = _patch
        _patch(ap, "get_credentials", lambda: None)
        _patch(ac, "build", lambda *a, **k: object())
        _patch(ap, "_charger_config", lambda d: None)
        _patch(ap, "_dossier_anticipation_jour", lambda *a, **k: "folder")
        _patch(ac, "appliquer_annulations_jour",
               lambda *a, **k: (set(), ENVOYE, False))

        def _generer(d, contenu, jj, mm):
            self.pdf_generes.append(contenu)
            chemin = os.path.join(ap.WORK_DIR, f"anticipation_{jj}.pdf")
            os.makedirs(ap.WORK_DIR, exist_ok=True)
            with open(chemin, "wb") as f:
                f.write(b"%PDF")
            return chemin
        _patch(ac, "generer_pdf_jour", _generer)
        _patch(ap, "archiver_resultat_anticipation_drive", lambda *a: True)
        _patch(ac, "_envoyer_email_resultat", lambda *a: True)
        _patch(ac, "_maj_fichier_commandes_envoyees",
               lambda d, commandes, mm, jj: self.envoyees.extend(commandes))
        _patch(ac, "_reinitialiser_dossier_jour_anticipation",
               lambda d, f, jj, mm, contenu: (self.reinit.append(contenu)
                                              or ([], ["55376672"])))
        _patch(ac, "_envoyer_email_commandes_orphelines", lambda *a: None)
        _patch(ac, "_envoyer_email_annulees_rattrapees", lambda *a: None)
        _patch(ac, "_envoyer_email_commandes_arrivees_pendant_envoi",
               lambda g, jj, nums: self.alertes_arrivees.extend(nums))
        _patch(sys, "argv", ["anticipation_commandes.py", "--date", "25/09/2026"])

    def tearDown(self):
        for module, nom, valeur in reversed(self._patchs):
            setattr(module, nom, valeur)

    def test_pdf_liste_envoyee_et_nettoyage_sur_le_meme_contenu(self):
        ac.main()

        self.assertEqual(self.pdf_generes, [ENVOYE])
        self.assertEqual(self.envoyees, ["55370001", "55370002"])
        self.assertEqual(self.reinit, [ENVOYE])
        self.assertEqual(self.alertes_arrivees, ["55376672"])

    def test_rien_a_envoyer_sans_produit(self):
        self._patch(ac, "appliquer_annulations_jour",
                    lambda *a, **k: (set(), "", False))
        self._patch(ac, "generer_pdf_jour", lambda *a: None)
        ac.main()
        self.assertEqual(self.envoyees, [])
        self.assertEqual(self.reinit, [])

    def test_echec_si_pdf_impossible_avec_produits(self):
        # Cas du 25/09 : reportlab absent du runner, le PDF n'etait pas genere
        # et le run se terminait en succes sans rien envoyer. Il doit echouer,
        # sans rien noter comme envoye ni toucher au brouillon.
        self._patch(ac, "generer_pdf_jour", lambda *a: None)
        with self.assertRaises(SystemExit) as ctx:
            ac.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.envoyees, [])
        self.assertEqual(self.reinit, [])


class TestCommandesDuPdf(unittest.TestCase):
    def test_seules_les_commandes_a_rayon_connu_comptent(self):
        inconnu = "3256220303009;DIVERS;1,00;;1;;0;;;VEN 18:00;1;X;;;;Z"
        contenu = ENVOYE + f"#CDE:55370003\n{inconnu}\n"
        self.assertEqual(ac.commandes_du_pdf(contenu), ["55370001", "55370002"])


if __name__ == "__main__":
    unittest.main()
