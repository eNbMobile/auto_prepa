#!/usr/bin/env python3
"""
Tests du mail "Attention commande anticipee et annulee" quand la commande a ete
REMPLACEE : les produits deja sortis en rayon pour l'ancienne commande ne sont
pas forcement ceux de la nouvelle. Le mail doit dire ce qui est a retourner en
rayon, ce qui est a sortir en plus, et ne rien ajouter quand les deux
commandes anticipent exactement les memes produits aux memes quantites.

Lancement : python3 -m unittest discover -s tests
"""

import base64
import os
import sys
import unittest
from email import message_from_bytes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap


def _ligne(gencod, libelle, qte):
    """Ligne de bon_anticipation.txt : 16 champs, cf. anticipation_commandes.py."""
    return f"{gencod};{libelle};12,50;1,50;{qte};;0;;;LUN 18:00;2;RAYON;;;;C"


LESSIVE = _ligne("3256630303000", "LESSIVE X4", 1)
JOUET = _ligne("3256228404473", "JOUET BOIS", 2)
CAFE = _ligne("3256111222333", "CAFE MOULU", 1)


class _FakeRequete:
    def __init__(self, journal=None, corps=None):
        self._journal = journal
        self._corps = corps

    def execute(self):
        if self._journal is not None:
            self._journal.append(self._corps)
            return {"id": "msg1"}
        return self._corps


class _FakeGmail:
    """Service Gmail minimal : conserve les messages envoyes."""

    def __init__(self):
        self.envoyes = []

    def users(self):
        gmail = self

        class _Messages:
            def send(self, userId=None, body=None):
                return _FakeRequete(gmail.envoyes, body)

        class _Users:
            def messages(self):
                return _Messages()

        return _Users()


def _sujet(message):
    brut = base64.urlsafe_b64decode(message["raw"] + "==")
    return message_from_bytes(brut)["subject"]


def _corps(message):
    brut = base64.urlsafe_b64decode(message["raw"] + "==")
    return message_from_bytes(brut).get_payload(decode=True).decode("utf-8")


class TestQuantitesAnticipation(unittest.TestCase):
    def test_lit_gencod_libelle_et_quantite(self):
        self.assertEqual(
            ap._quantites_anticipation(f"{LESSIVE}\n{JOUET}\n"),
            {"3256630303000": ("LESSIVE X4", 1.0),
             "3256228404473": ("JOUET BOIS", 2.0)})

    def test_cumule_les_lignes_d_un_meme_produit(self):
        contenu = f"{LESSIVE}\n{LESSIVE}\n"
        self.assertEqual(ap._quantites_anticipation(contenu)["3256630303000"][1], 2.0)

    def test_tolere_le_prefixe_de_sequence_et_les_lignes_vides(self):
        contenu = f"-1;{LESSIVE}\n\n"
        self.assertEqual(list(ap._quantites_anticipation(contenu)), ["3256630303000"])

    def test_contenu_vide(self):
        self.assertEqual(ap._quantites_anticipation(""), {})
        self.assertEqual(ap._quantites_anticipation(None), {})


class TestComparaisonAnticipations(unittest.TestCase):
    def test_memes_produits_memes_quantites_rien_a_signaler(self):
        contenu = f"{LESSIVE}\n{JOUET}\n"
        self.assertEqual(ap._phrases_comparaison_anticipation(contenu, contenu), [])

    def test_produit_absent_de_la_nouvelle_commande(self):
        phrases = ap._phrases_comparaison_anticipation(f"{LESSIVE}\n{JOUET}\n", JOUET)
        self.assertEqual(len(phrases), 1)
        self.assertIn("Le produit LESSIVE X4 est à retourner en rayon", phrases[0])
        self.assertIn("ne l'a pas commandé dans la nouvelle commande", phrases[0])

    def test_plusieurs_produits_absents_sont_enumeres(self):
        phrases = ap._phrases_comparaison_anticipation(f"{LESSIVE}\n{JOUET}\n{CAFE}\n", CAFE)
        self.assertIn("Les produits LESSIVE X4 et JOUET BOIS (x2) sont à retourner en rayon",
                      phrases[0])
        self.assertIn("ne les a pas commandés", phrases[0])

    def test_produit_ajoute_dans_la_nouvelle_commande(self):
        phrases = ap._phrases_comparaison_anticipation(LESSIVE, f"{LESSIVE}\n{JOUET}\n")
        self.assertEqual(len(phrases), 1)
        self.assertIn("le client a ajouté le produit JOUET BOIS (x2)", phrases[0])
        self.assertIn("prévenir les rayons de l'anticipation supplémentaire", phrases[0])

    def test_produits_en_moins_et_en_plus(self):
        phrases = ap._phrases_comparaison_anticipation(f"{LESSIVE}\n{JOUET}\n",
                                                       f"{JOUET}\n{CAFE}\n")
        self.assertEqual(len(phrases), 2)
        self.assertIn("LESSIVE X4", phrases[0])
        self.assertIn("CAFE MOULU", phrases[1])

    def test_quantite_en_baisse_a_sa_propre_phrase(self):
        # "le client ne l'a pas commandé" enverrait les 3 en retour au lieu de 2.
        phrases = ap._phrases_comparaison_anticipation(_ligne("111", "PATES", 3),
                                                       _ligne("111", "PATES", 1))
        self.assertEqual(len(phrases), 1)
        self.assertIn("réduit sa quantité de PATES (2 sur 3)", phrases[0])
        self.assertIn("à retourner en rayon", phrases[0])
        self.assertNotIn("ne l'a pas commandé", phrases[0])

    def test_quantite_en_hausse_precise_le_supplement(self):
        phrases = ap._phrases_comparaison_anticipation(_ligne("111", "PATES", 1),
                                                       _ligne("111", "PATES", 3))
        self.assertEqual(len(phrases), 1)
        self.assertIn("augmenté sa quantité de PATES (+2)", phrases[0])
        self.assertIn("anticipation supplémentaire", phrases[0])

    def test_nouvelle_commande_sans_anticipation_tout_est_a_retourner(self):
        phrases = ap._phrases_comparaison_anticipation(f"{LESSIVE}\n{JOUET}\n", "")
        self.assertEqual(len(phrases), 1)
        self.assertIn("LESSIVE X4", phrases[0])
        self.assertIn("JOUET BOIS (x2)", phrases[0])

    def test_ancienne_anticipation_introuvable_aucune_affirmation(self):
        # Sans le bon de l'ancienne commande, tous les produits de la nouvelle
        # passeraient pour des ajouts du client : le mail n'affirme rien.
        self.assertEqual(ap._phrases_comparaison_anticipation("", f"{LESSIVE}\n"), [])


class TestMailAnticipationAnnulee(unittest.TestCase):
    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self.gmail = _FakeGmail()

    def tearDown(self):
        ap.EMAIL_ANTICIPATION = self._destinataire

    def test_le_comparatif_figure_dans_le_corps(self):
        ap._envoyer_email_anticipation_annulee(
            self.gmail, "M.", "DUPONT", "Jean", "54764266", "54764433",
            ap._phrases_comparaison_anticipation(f"{LESSIVE}\n{JOUET}\n", f"{JOUET}\n{CAFE}\n"))

        corps = _corps(self.gmail.envoyes[0])
        self.assertIn("remplacée par la commande n°54764433", corps)
        self.assertIn("LESSIVE X4", corps)
        self.assertIn("CAFE MOULU", corps)
        self.assertIn("Merci d'être vigilant", corps)

    def test_anticipation_identique_mail_inchange(self):
        contenu = f"{LESSIVE}\n{JOUET}\n"
        ap._envoyer_email_anticipation_annulee(
            self.gmail, "M.", "DUPONT", "Jean", "54764266", "54764433",
            ap._phrases_comparaison_anticipation(contenu, contenu))

        corps = _corps(self.gmail.envoyes[0])
        self.assertNotIn("à retourner en rayon", corps)
        self.assertNotIn("anticipation supplémentaire", corps)


class TestAlerteImmediateOuDifferee(unittest.TestCase):
    """L'anticipation de la commande de remplacement n'existe que si celle-ci a
    deja ete traitee — et traiter_modifications_clients tourne AVANT
    telecharger_bons_email dans main(). L'alerte doit alors attendre."""

    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self.gmail = _FakeGmail()
        self.en_attente = {}
        self._patchs = []

        def _patch(nom, valeur):
            self._patchs.append((nom, getattr(ap, nom)))
            setattr(ap, nom, valeur)

        _patch("_telecharger_commandes_anticipation_envoyee",
               lambda d, mm, jj: {"54764266"})
        _patch("_client_archive_bdc", lambda d, num: ("M.", "DUPONT", "Jean"))
        _patch("_telecharger_anticipation_drive",
               lambda d, num: self.anticipations.get(num, ""))
        _patch("_telecharger_anticipation_archive_drive", lambda d, num: "")
        _patch("_commande_deja_traitee", lambda d, num: num in self.traitees)
        _patch("_deposer_alerte_anticipation_en_attente",
               lambda d, anc, nouv, civ, nom, prenom, contenu: (
                   self.en_attente.update({nouv: (anc, civ, nom, prenom, contenu)}) or True))
        self.anticipations = {"54764266": f"{LESSIVE}\n{JOUET}\n"}
        self.traitees = set()

    def tearDown(self):
        for nom, valeur in reversed(self._patchs):
            setattr(ap, nom, valeur)
        ap.EMAIL_ANTICIPATION = self._destinataire

    def _alerter(self):
        ap._alerter_si_commande_anticipee_annulee(
            None, self.gmail, "54764266", "10_09", "09_2026", "54764433",
            contenu_ancien=self.anticipations["54764266"])

    def test_remplacement_deja_traite_alerte_immediate_avec_comparatif(self):
        self.anticipations["54764433"] = JOUET
        self.traitees.add("54764433")
        self._alerter()

        self.assertEqual(self.en_attente, {})
        self.assertIn("LESSIVE X4", _corps(self.gmail.envoyes[0]))

    def test_remplacement_sans_anticipation_tout_est_a_retourner(self):
        self.traitees.add("54764433")
        self._alerter()

        corps = _corps(self.gmail.envoyes[0])
        self.assertIn("LESSIVE X4", corps)
        self.assertIn("JOUET BOIS (x2)", corps)

    def test_remplacement_pas_encore_traite_alerte_mise_en_attente(self):
        self._alerter()

        self.assertEqual(self.gmail.envoyes, [])
        self.assertIn("54764433", self.en_attente)
        self.assertEqual(self.en_attente["54764433"][0], "54764266")

    def test_mise_en_attente_impossible_alerte_sans_comparatif(self):
        ap._deposer_alerte_anticipation_en_attente = lambda *a, **k: False
        self._alerter()

        corps = _corps(self.gmail.envoyes[0])
        self.assertIn("remplacée par la commande n°54764433", corps)
        self.assertNotIn("à retourner en rayon", corps)

    def test_annulation_sans_remplacement_mail_inchange(self):
        ap._alerter_si_commande_anticipee_annulee(
            None, self.gmail, "54764266", "10_09", "09_2026")

        corps = _corps(self.gmail.envoyes[0])
        self.assertIn("a été annulée", corps)
        self.assertNotIn("à retourner en rayon", corps)

    def test_commande_hors_anticipation_envoyee_aucun_mail(self):
        ap._telecharger_commandes_anticipation_envoyee = lambda d, mm, jj: set()
        self._alerter()

        self.assertEqual(self.gmail.envoyes, [])
        self.assertEqual(self.en_attente, {})


class TestAlerteEnAttente(unittest.TestCase):
    """Le fichier d'attente est relu au traitement de la commande de
    remplacement : c'est la que l'alerte part, comparatif inclus."""

    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self.gmail = _FakeGmail()
        self.corbeille = []
        self._patchs = []

        def _patch(nom, valeur):
            self._patchs.append((nom, getattr(ap, nom)))
            setattr(ap, nom, valeur)

        self.alerte = (
            "ancien=54764266\nnouveau=54764433\ncivilite=M.\nnom=DUPONT\n"
            "prenom=Jean\nhorodatage=2026-09-17T10:00:00+02:00\n"
            f"{ap._SEPARATEUR_ALERTE}\n{LESSIVE}\n{JOUET}\n")
        _patch("_lire_alerte_anticipation_en_attente",
               lambda d, num: (("id_alerte",) + ap._parser_alerte_anticipation(self.alerte)
                               if num == "54764433" else (None, {}, "")))

        class _FakeFiles:
            def update(_self, fileId=None, body=None):
                return _FakeRequete(self.corbeille, fileId)

        class _FakeDrive:
            def files(_self):
                return _FakeFiles()

        self.drive = _FakeDrive()

    def tearDown(self):
        for nom, valeur in reversed(self._patchs):
            setattr(ap, nom, valeur)
        ap.EMAIL_ANTICIPATION = self._destinataire

    def test_parse_entetes_et_anticipation(self):
        entetes, contenu = ap._parser_alerte_anticipation(self.alerte)
        self.assertEqual(entetes["ancien"], "54764266")
        self.assertEqual(entetes["nouveau"], "54764433")
        self.assertEqual(ap._quantites_anticipation(contenu)["3256630303000"][1], 1.0)

    def test_envoie_l_alerte_avec_le_comparatif_et_purge_le_fichier(self):
        ap._traiter_alerte_anticipation_en_attente(
            self.drive, self.gmail, "54764433", f"{JOUET}\n{CAFE}\n")

        corps = _corps(self.gmail.envoyes[0])
        self.assertIn("LESSIVE X4", corps)
        self.assertIn("CAFE MOULU", corps)
        self.assertEqual(self.corbeille, ["id_alerte"])

    def test_aucune_alerte_en_attente_ne_fait_rien(self):
        ap._traiter_alerte_anticipation_en_attente(self.drive, self.gmail, "99999999", JOUET)

        self.assertEqual(self.gmail.envoyes, [])
        self.assertEqual(self.corbeille, [])


class TestPurgeAlertesEnAttente(unittest.TestCase):
    """La commande de remplacement peut ne jamais etre traitee (email de
    confirmation jamais recu) : l'alerte ne peut pas rester en attente
    indefiniment, elle porte sur des produits deja sortis en rayon."""

    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self.gmail = _FakeGmail()
        self.corbeille = []
        self._patchs = []

        def _patch(nom, valeur):
            self._patchs.append((nom, getattr(ap, nom)))
            setattr(ap, nom, valeur)

        self.age_minutes = ap._DELAI_ALERTE_ANTICIPATION_MINUTES + 1
        _patch("_dossier_annulations", lambda d, creer=True: "folder_annul")
        _patch("_telecharger_texte_drive", lambda d, file_id: self._alerte())
        _patch("_anticipation_commande", lambda d, num, contenu="": "")

        class _FakeFiles:
            def list(_self, **kwargs):
                return _FakeRequete(corps={"files": [
                    {"id": "id_alerte", "name": "alerte_anticipation_54764433.txt"}]})

            def update(_self, fileId=None, body=None):
                return _FakeRequete(self.corbeille, fileId)

        class _FakeDrive:
            def files(_self):
                return _FakeFiles()

        self.drive = _FakeDrive()

    def tearDown(self):
        for nom, valeur in reversed(self._patchs):
            setattr(ap, nom, valeur)
        ap.EMAIL_ANTICIPATION = self._destinataire

    def _alerte(self):
        from datetime import timedelta
        horodatage = (ap.datetime.now(ap._TZ) - timedelta(minutes=self.age_minutes)).isoformat()
        return ("ancien=54764266\nnouveau=54764433\ncivilite=M.\nnom=DUPONT\nprenom=Jean\n"
                f"horodatage={horodatage}\n{ap._SEPARATEUR_ALERTE}\n{LESSIVE}\n")

    def test_alerte_expiree_part_et_le_fichier_est_purge(self):
        ap._purger_alertes_anticipation_en_attente(self.drive, self.gmail)

        self.assertEqual(len(self.gmail.envoyes), 1)
        self.assertIn("54764266", _corps(self.gmail.envoyes[0]))
        self.assertEqual(self.corbeille, ["id_alerte"])

    def test_alerte_recente_reste_en_attente(self):
        self.age_minutes = 1
        ap._purger_alertes_anticipation_en_attente(self.drive, self.gmail)

        self.assertEqual(self.gmail.envoyes, [])
        self.assertEqual(self.corbeille, [])

    def test_remplacement_sur_le_point_d_etre_traite_reste_en_attente(self):
        # L'alerte partira completee depuis traiter_commande_pdf, quelques
        # secondes plus tard dans le meme run.
        ap._purger_alertes_anticipation_en_attente(self.drive, self.gmail, {"54764433"})

        self.assertEqual(self.gmail.envoyes, [])
        self.assertEqual(self.corbeille, [])


class TestMailAnticipationRenouvelee(unittest.TestCase):
    """Le mail "Commande N - anticipation renouvelee" renvoie a l'equipe le bon
    d'anticipation d'une commande annulee/remplacee. Il n'a d'interet que si
    l'anticipation du jour de livraison est DEJA PARTIE : sinon personne n'a
    rien sorti en rayon et le mail est inutile (cas d'une commande annulee la
    veille de sa livraison, avant l'envoi de l'anticipation)."""

    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self.gmail = _FakeGmail()
        self._patchs = []
        self.envoyees = {"54764266"}
        self.anticipation = f"{LESSIVE}\n{JOUET}\n"
        self.alertes = []

        def _patch(nom, valeur):
            self._patchs.append((nom, getattr(ap, nom)))
            setattr(ap, nom, valeur)

        _patch("enregistrer_commande_annulee", lambda d, num: None)
        _patch("_infos_email_original", lambda g, num: (None, "22_09", "09_2026"))
        _patch("_telecharger_anticipation_drive", lambda d, num: self.anticipation)
        _patch("_telecharger_commandes_anticipation_envoyee",
               lambda d, mm, jj: self.envoyees)
        _patch("_alerter_si_commande_anticipee_annulee",
               lambda *a, **k: self.alertes.append((a, k)))
        _patch("_marquer_retrait_anticipation_drive", lambda d, num, mm, jj: None)
        _patch("declencher_retrait_anticipation", lambda num, jj, mm: None)

    def tearDown(self):
        for nom, valeur in reversed(self._patchs):
            setattr(ap, nom, valeur)
        ap.EMAIL_ANTICIPATION = self._destinataire

    def _traiter(self):
        ap._traiter_commande_potentiellement_anticipee(None, self.gmail, "54764266")

    def test_anticipation_deja_envoyee_le_bon_est_renvoye(self):
        self._traiter()

        self.assertEqual(len(self.gmail.envoyes), 1)
        self.assertIn("anticipation renouvelee", _sujet(self.gmail.envoyes[0]))
        self.assertIn("LESSIVE X4", _corps(self.gmail.envoyes[0]))

    def test_anticipation_pas_encore_envoyee_aucun_mail(self):
        self.envoyees = set()
        self._traiter()

        self.assertEqual(self.gmail.envoyes, [])

    def test_la_liste_des_commandes_envoyees_est_passee_a_l_alerte(self):
        # Une seule lecture du fichier commandes_envoyees_JJ_MM.txt pour les
        # deux decisions (mail renouvele et alerte "anticipee et annulee").
        self._traiter()

        self.assertEqual(self.alertes[0][1]["commandes_envoyees"], self.envoyees)


if __name__ == "__main__":
    unittest.main()
