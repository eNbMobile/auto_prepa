import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prepa_drive_degrade as pdd


class TestScanf(unittest.TestCase):
    def test_entiers_et_litteraux(self):
        f = pdd.Flux(b"1-AB-12-3;reste")
        self.assertEqual(f.scanf("%d-"), [1])
        self.assertEqual(f.scanf("%c%c-%d-%d;"), [65, 66, 12, 3])
        self.assertEqual(pdd.champ(f, pdd.NL), b"reste")

    def test_arret_au_premier_echec_comme_le_c(self):
        # Adresse tronquee « R1-AA-1- » : le dernier %d echoue, le ';' reste a lire.
        f = pdd.Flux(b"AA-1-;gencod")
        self.assertEqual(f.scanf("%c%c-%d-%d;"), [65, 65, 1, None])
        self.assertEqual(pdd.champ(f, pdd.SEMI), b"")

    def test_flottants(self):
        f = pdd.Flux(b"12.34;0.5;")
        a, b = f.scanf("%f;%f;")
        self.assertAlmostEqual(a, 12.34, places=5)
        self.assertEqual(b, 0.5)


class TestGencods(unittest.TestCase):
    def test_correspondance_12_chiffres_et_zeros_de_tete(self):
        self.assertTrue(pdd.gencod_correspond(b"3256225454952", b"3256225454951"))
        self.assertTrue(pdd.gencod_correspond(b"0003045320094", b"30453200"))
        self.assertFalse(pdd.gencod_correspond(b"0003045320094", b"3045"))  # code court

    def test_index_identique_au_parcours_lineaire(self):
        rnd = random.Random(7)
        refs = []
        for _ in range(3000):
            n = rnd.choice([4, 8, 9, 11, 12, 13, 13, 13])
            refs.append("".join(rnd.choice("0123") for _ in range(n)))
        data = "".join(f"{r};V{i}\r\n" for i, r in enumerate(refs)).encode()
        table = pdd.TableGencods(data)
        for _ in range(3000):
            produit = "".join(rnd.choice("0123") for _ in range(13)).encode()
            attendu = next((i for i, (g, _) in enumerate(table.lignes)
                            if pdd.gencod_correspond(produit, g)), None)
            self.assertEqual(table.chercher(produit), attendu, produit)


class TestRangementEtDlc(unittest.TestCase):
    def test_dlc(self):
        m = pdd.Moteur(".")
        m.get_dlc(28, 2, 2026, 2)
        self.assertEqual((m.jour2, m.mois2, m.annee2), (2, 3, 2026))
        m.get_dlc(30, 12, 2026, 4)
        self.assertEqual((m.jour2, m.mois2, m.annee2), (3, 1, 2027))
        self.assertEqual(m._dlc(b"02052010\r", 1, 1, 2026), 2)
        self.assertIsNone(m._dlc(b"0301\r", 1, 1, 2026))

    def test_rangement_par_chemin(self):
        m = pdd.Moteur(".")
        m.printf = lambda t: None
        m.f["prepaNEW"] = pdd.Fichier()
        m.f["prepaNEW"].ajouter(b"333;5;LIB C\n111;2;LIB A\n222;9;LIB B\n")
        m.rangement_produits(0)
        m.rangement_produits(1)
        self.assertEqual(m.f["prepaNEW"].data, b"111;LIB A;2\n333;LIB C;5\n222;LIB B;9\n")


class TestNomClientAgp(unittest.TestCase):
    """Bon AGP (substitution au produit) : la civilite est en colonne 0 de la
    ligne client, le nom doit quand meme etre repris dans l'en-tete."""

    ENCAISSEMENT = (
        "    Commande" + " " * 40 + "BON D'ENCAISSEMENT" + " " * 49 + "LUNDI 26/10/2026\n"
        + " " * 52 + "Magasin : ARNAGE\n"
        + " " * 52 + "0243212223" + " " * 53 + "17h30 - 18h00\n"
        "\n\n\n\n"
        "Commande : 12345678 -" + " " * 30 + "99000000000000\n"
        "RETRAIT" + " " * 117 + "PAIEMENT EN LIGNE\n"
        "\n"
        "Mme DUPONT MARIE" + " " * 108 + "Carte de fidelite : 00000000000000\n"
        "Tel : / 0600000000\n"
        "  Substitution > AU PRODUIT\n"
        "      1" + " " * 48 + "Produit test SUBSTI.(Oui)\n"
    ).encode()

    def test_nom_client_en_debut_de_ligne(self):
        m = pdd.Moteur(".")
        m.printf = lambda t: None
        m.encaissement = self.ENCAISSEMENT
        en_tetes = []
        inverse = m.inverse_data
        m.inverse_data = lambda: (en_tetes.append(m.f["base"].premiere_ligne()), inverse())
        m.test_bon_encaissement()
        self.assertEqual(len(en_tetes), 1)
        self.assertIn(b",Mme DUPONT MARIE", en_tetes[0])


if __name__ == "__main__":
    unittest.main()
