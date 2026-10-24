import base64
import email
import os
import sys
import unittest
from email.header import decode_header

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arbitrage_fruits_legumes as afl


class TestClassification(unittest.TestCase):
    def test_fruit_avec_pays(self):
        self.assertEqual(afl.classifier_fruit_legume("POMMES GALA FRANCE"), ("fruit", None))

    def test_legume_avec_pays(self):
        self.assertEqual(afl.classifier_fruit_legume("CAROTTES BOTTE FRANCE"), ("legume", None))

    def test_pomme_de_terre_nest_pas_un_fruit(self):
        self.assertEqual(afl.classifier_fruit_legume("POMMES DE TERRE FRANCE"), ("legume", None))

    def test_libelle_sans_fruit_ni_legume_non_concerne(self):
        self.assertEqual(afl.classifier_fruit_legume("YAOURT NATURE"), (None, None))

    def test_pays_introuvable_doute(self):
        categorie, raison = afl.classifier_fruit_legume("POMMES GALA")
        self.assertIsNone(categorie)
        self.assertIn("pays", raison)

    def test_ambigu_fruit_et_legume_doute(self):
        categorie, raison = afl.classifier_fruit_legume("MELANGE POMMES CAROTTES FRANCE")
        self.assertIsNone(categorie)
        self.assertIn("ambigu", raison)

    def test_accents_et_casse_indifferents(self):
        self.assertEqual(afl.classifier_fruit_legume("pêches espagne"), ("fruit", None))

    def test_poisson_peche_en_nest_pas_une_peche(self):
        self.assertEqual(afl.classifier_fruit_legume(
            "Dos de Cabillaud, gadus morhua, pêché en Atlantique Nord Est, ATLA.NE"),
            (None, None))

    def test_peche_de_vigne_reste_un_fruit(self):
        self.assertEqual(afl.classifier_fruit_legume("PECHES DE VIGNE FRANCE"), ("fruit", None))

    def test_cote_d_ivoire(self):
        self.assertEqual(afl.classifier_fruit_legume("BANANES CÔTE D'IVOIRE"), ("fruit", None))


class TestCodeNomenclatureRayon(unittest.TestCase):
    CONTENU = "0200000;FRUITS;R\n0300000;LEGUMES;S\nM1-AA-1-1;RAYON;A\n"

    def test_fruit(self):
        self.assertEqual(afl.code_nomenclature_rayon(self.CONTENU, "R"), "0200000")

    def test_legume(self):
        self.assertEqual(afl.code_nomenclature_rayon(self.CONTENU, "S"), "0300000")

    def test_absent(self):
        self.assertIsNone(afl.code_nomenclature_rayon(self.CONTENU, "U"))


class TestArbitrer(unittest.TestCase):
    def test_repartition(self):
        produits = {
            "1": {"libelle": "POMMES GALA FRANCE"},
            "2": {"libelle": "CAROTTES BOTTE FRANCE"},
            "3": {"libelle": "POMMES GALA"},           # doute : pays introuvable
            "4": {"libelle": "YAOURT NATURE"},          # non concerné
            "5": {"libelle": "THON ENTIER"},
        }
        nomenclatures = {"5": "0100000"}  # déjà connu
        ajouts, doutes, restants = afl.arbitrer(produits, nomenclatures)

        self.assertEqual(sorted(ajouts), [
            ("1", "POMMES GALA FRANCE", "fruit"),
            ("2", "CAROTTES BOTTE FRANCE", "legume"),
        ])
        self.assertEqual(len(doutes), 1)
        self.assertEqual(doutes[0][0], "3")
        self.assertEqual(set(restants), {"4", "5"})


class FausseCs:
    """Simule le module controle_stocks pour ajouter_nomenclatures()."""
    def __init__(self, chemin_ramasse=""):
        self._chemin_ramasse = chemin_ramasse
        self.ecrit = None

    def _lire_config_drive(self, nom):
        if nom == "chemin_prepa_ramasse.csv":
            return self._chemin_ramasse
        return None

    def ajouter_lignes_config_drive(self, nom, lignes):
        self.ecrit = (nom, list(lignes))
        return True


class TestAjouterNomenclatures(unittest.TestCase):
    CHEMIN = "0200000;FRUITS;R\n0300000;LEGUMES;S\n"

    def test_ecriture(self):
        cs = FausseCs(self.CHEMIN)
        ajouts = [("1", "POMMES GALA FRANCE", "fruit"), ("2", "CAROTTES FRANCE", "legume")]
        reportes = afl.ajouter_nomenclatures(cs, ajouts)
        self.assertEqual(reportes, [])
        self.assertEqual(cs.ecrit, ("gencod_nomenclatures.csv", ["1;0200000", "2;0300000"]))

    def test_code_manquant_reporte_en_doute(self):
        cs = FausseCs("0200000;FRUITS;R\n")  # pas de code légume
        ajouts = [("1", "CAROTTES FRANCE", "legume")]
        reportes = afl.ajouter_nomenclatures(cs, ajouts)
        self.assertEqual(len(reportes), 1)
        self.assertEqual(reportes[0][0], "1")
        self.assertIsNone(cs.ecrit)

    def test_rien_a_ajouter(self):
        cs = FausseCs()
        self.assertEqual(afl.ajouter_nomenclatures(cs, []), [])
        self.assertIsNone(cs.ecrit)


class _ExecMessages:
    def __init__(self, captures):
        self._captures = captures

    def send(self, userId, body):
        self._captures.append(body)
        return self

    def execute(self):
        return {}


class FauxGmail:
    def __init__(self):
        self.captures = []

    def users(self):
        return self

    def messages(self):
        return _ExecMessages(self.captures)


class TestEnvoyerEmailDoute(unittest.TestCase):
    def test_destinataire_seul_sans_copie(self):
        gmail = FauxGmail()
        doutes = [("1", "POMMES GALA", "pays d'origine introuvable dans le libellé")]
        afl.envoyer_email_doute(gmail, "resp@example.com", doutes)

        self.assertEqual(len(gmail.captures), 1)
        raw = base64.urlsafe_b64decode(gmail.captures[0]["raw"]).decode()
        msg = email.message_from_string(raw)
        corps = msg.get_payload(decode=True).decode("utf-8")

        sujet = str(decode_header(msg["Subject"])[0][0], "utf-8")

        self.assertEqual(msg["To"], "resp@example.com")
        self.assertIsNone(msg["Cc"])
        self.assertIn("1 produit", sujet)
        self.assertIn("1 produit", corps)
        self.assertIn("POMMES GALA", corps)

    def test_gencod_en_double_une_seule_ligne(self):
        gmail = FauxGmail()
        doute = ("1", "POMMES GALA", "pays d'origine introuvable dans le libellé")
        afl.envoyer_email_doute(gmail, "resp@example.com", [doute, doute])

        raw = base64.urlsafe_b64decode(gmail.captures[0]["raw"]).decode()
        corps = email.message_from_string(raw).get_payload(decode=True).decode("utf-8")
        self.assertIn("1 produit ressemble", corps)
        self.assertEqual(corps.count("POMMES GALA"), 1)

    def test_rien_a_envoyer(self):
        gmail = FauxGmail()
        afl.envoyer_email_doute(gmail, "resp@example.com", [])
        self.assertEqual(gmail.captures, [])


if __name__ == "__main__":
    unittest.main()
