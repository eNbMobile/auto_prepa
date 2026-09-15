#!/usr/bin/env python3
"""
Tests de l'alerte "aucun bon de prepa genere".

Une commande dont la generation echoue disparait silencieusement : son PDF est
archive sur Drive avant la generation, son email de confirmation est libellise
des le telechargement (donc jamais repris), et le workflow reste vert. C'est
ce qui a fait disparaitre une vingtaine de commandes du 15/09/2026, le binaire
de generation plantant sur certaines d'entre elles. Chaque sortie de
traiter_commande_pdf qui ne produit pas de bon doit desormais envoyer un email.

Lancement : python3 -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_prepa as ap


class _FakeRequete:
    def __init__(self, journal=None, corps=None):
        self._journal = journal
        self._corps = corps

    def execute(self):
        if self._journal is not None:
            self._journal.append(self._corps)
            return {"id": "msg1"}
        return self._corps


class _FakeMessages:
    def __init__(self, gmail):
        self._gmail = gmail

    def send(self, userId=None, body=None):
        return _FakeRequete(self._gmail.envoyes, body)

    def list(self, userId=None, q=None, maxResults=None):
        self._gmail.recherches.append(q)
        trouves = [{"id": "sent1"}] if self._gmail.alerte_deja_envoyee else []
        return _FakeRequete(corps={"messages": trouves})


class _FakeUsers:
    def __init__(self, gmail):
        self._gmail = gmail

    def messages(self):
        return _FakeMessages(self._gmail)


class _FakeGmail:
    """Service Gmail minimal : conserve les messages envoyes et les recherches."""

    def __init__(self, alerte_deja_envoyee=False):
        self.envoyes = []
        self.recherches = []
        self.alerte_deja_envoyee = alerte_deja_envoyee

    def users(self):
        return _FakeUsers(self)


def _sujet_et_corps(message):
    """Decode le message brut (base64url) en (sujet, corps)."""
    import base64
    from email import message_from_bytes

    brut = base64.urlsafe_b64decode(message["raw"] + "==")
    msg = message_from_bytes(brut)
    return msg["subject"], msg.get_payload(decode=True).decode("utf-8")


class TestEnvoiAlerteBonAbsent(unittest.TestCase):
    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self.gmail = _FakeGmail()

    def tearDown(self):
        ap.EMAIL_ANTICIPATION = self._destinataire

    def test_alerte_envoyee_avec_motif_et_detail(self):
        envoye = ap._envoyer_email_bon_absent(
            self.gmail, "54985295", "plantage du binaire de generation (code -11)",
            "stderr : Segmentation fault")

        self.assertTrue(envoye)
        self.assertEqual(len(self.gmail.envoyes), 1)
        sujet, corps = _sujet_et_corps(self.gmail.envoyes[0])
        self.assertIn("54985295", sujet)
        self.assertIn("AUCUN bon de prepa", sujet)
        self.assertIn("plantage du binaire de generation (code -11)", corps)
        self.assertIn("Segmentation fault", corps)
        # La marche a suivre pour rattraper la commande doit figurer dans le mail.
        self.assertIn(ap.DOSSIER_TRAITEMENT_MANUEL, corps)
        self.assertIn("BonDeCommande_54985295.pdf", corps)

    def test_une_seule_alerte_par_commande(self):
        # Un bon depose a la main dont la generation echoue est repris a chaque
        # run : sans ce garde-fou, l'alerte repartirait toutes les minutes.
        gmail = _FakeGmail(alerte_deja_envoyee=True)
        self.assertFalse(
            ap._envoyer_email_bon_absent(gmail, "54985295", "plantage du binaire"))
        self.assertEqual(gmail.envoyes, [])
        self.assertIn("54985295", gmail.recherches[0])
        self.assertIn("in:sent", gmail.recherches[0])

    def test_recherche_impossible_alerte_quand_meme(self):
        class _GmailListeCassee(_FakeGmail):
            def users(self):
                users = super().users()
                messages = users.messages()
                messages.list = lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("quota Gmail"))
                users.messages = lambda: messages
                return users

        gmail = _GmailListeCassee()
        self.assertTrue(
            ap._envoyer_email_bon_absent(gmail, "54985295", "plantage du binaire"))
        self.assertEqual(len(gmail.envoyes), 1)

    def test_sans_destinataire_configure(self):
        ap.EMAIL_ANTICIPATION = ""
        self.assertFalse(
            ap._envoyer_email_bon_absent(self.gmail, "54985295", "bon de prepa vide"))
        self.assertEqual(self.gmail.envoyes, [])

    def test_echec_d_envoi_sans_exception(self):
        class _GmailCasse:
            def users(self):
                raise RuntimeError("Gmail indisponible")

        # Une alerte qui ne part pas ne doit pas interrompre le traitement des
        # commandes suivantes.
        self.assertFalse(
            ap._envoyer_email_bon_absent(_GmailCasse(), "54985295", "bon de prepa vide"))


class TestAlerteDepuisTraiterCommandePdf(unittest.TestCase):
    """La config d'adressage indisponible est le seul chemin d'echec testable
    sans le binaire de generation : il s'arrete avant de l'appeler."""

    def setUp(self):
        self._destinataire = ap.EMAIL_ANTICIPATION
        self._work, self._cache, self._bdc = ap.WORK_DIR, ap.CACHE_DIR, ap.BDC_DIR
        self._drive_bdc = ap.DRIVE_BDC_FOLDER_ID

        ap.EMAIL_ANTICIPATION = "prepa@exemple.fr"
        self._tmp = tempfile.TemporaryDirectory()
        ap.WORK_DIR = os.path.join(self._tmp.name, "work")
        ap.CACHE_DIR = os.path.join(self._tmp.name, "cache")
        ap.BDC_DIR = os.path.join(self._tmp.name, "bdc")
        ap.DRIVE_BDC_FOLDER_ID = ""   # pas d'archivage Drive dans le test
        os.makedirs(ap.WORK_DIR)
        os.makedirs(ap.CACHE_DIR)
        with open(os.path.join(ap.CACHE_DIR, "BonDeCommande_54985295.pdf"), "wb") as f:
            f.write(b"%PDF-1.4\n")
        self.gmail = _FakeGmail()

    def tearDown(self):
        ap.EMAIL_ANTICIPATION = self._destinataire
        ap.WORK_DIR, ap.CACHE_DIR, ap.BDC_DIR = self._work, self._cache, self._bdc
        ap.DRIVE_BDC_FOLDER_ID = self._drive_bdc
        self._tmp.cleanup()

    def test_gencod_indisponible_alerte_et_arret(self):
        statut, _, _, _ = ap.traiter_commande_pdf(
            None, self.gmail, None, "BonDeCommande_54985295.pdf", "15_09", "09_2026",
            "08h00", None, None, False)

        self.assertEqual(statut, "stop")
        self.assertEqual(len(self.gmail.envoyes), 1)
        sujet, corps = _sujet_et_corps(self.gmail.envoyes[0])
        self.assertIn("54985295", sujet)
        self.assertIn("gencod_adresses.csv", corps)


if __name__ == "__main__":
    unittest.main()
