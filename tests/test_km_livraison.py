#!/usr/bin/env python3
"""
Tests du cycle de vie de la colonne km de LIVRAISON DRIVE 2026 : un km absent
au moment ou la commande est inscrite ne declenche pas d'email tout de suite
(la commande n'est souvent pas encore synchronisee cote Shopopop, et les
retentatives des minutes suivantes recuperent la distance). La commande est
notee dans un fichier d'attente sur Drive, et l'email ne part que si le km
manque encore au bout de _DELAI_SIGNALEMENT_KM_MINUTES.

Lancement : python3 -m unittest discover -s tests
"""

import io
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import controle_stocks as cs
import livraison_drive as ld

_TZ = ZoneInfo("Europe/Paris")
SPREADSHEET_ID = "id_classeur"
CONFIG_FOLDER_ID = "id_config"
MAINTENANT = datetime(2026, 9, 15, 8, 0, tzinfo=_TZ)   # mardi


class _Requete:
    def __init__(self, resultat=None):
        self._resultat = resultat if resultat is not None else {}

    def execute(self):
        return self._resultat


# --------------------------------------------------------------------------
# Faux service Sheets : un dict {onglet: [[cellules], ...]}, en-tete inclus.
# --------------------------------------------------------------------------
class _FakeValues:
    def __init__(self, classeur):
        self._classeur = classeur
        self.updates = []

    @staticmethod
    def _onglet(plage):
        return plage.split('!')[0].strip("'")

    def get(self, spreadsheetId=None, range=None):
        lignes = self._classeur.get(self._onglet(range), [])
        return _Requete({"values": [list(l) for l in lignes[1:]]})

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self.updates.append((range, body["values"]))
        return _Requete()


class _FakeSpreadsheets:
    def __init__(self, classeur):
        self._classeur = classeur
        self._values = _FakeValues(classeur)
        self.formats = []

    def values(self):
        return self._values

    def get(self, spreadsheetId=None, fields=None, ranges=None, includeGridData=None):
        return _Requete({"sheets": [
            {"properties": {"title": titre, "sheetId": i}}
            for i, titre in enumerate(self._classeur)
        ]})

    def batchUpdate(self, spreadsheetId=None, body=None):
        for requete in body["requests"]:
            cellule = requete["repeatCell"]
            self.formats.append((
                cellule["range"]["sheetId"],
                cellule["range"]["startRowIndex"] + 1,
                cellule["range"]["startColumnIndex"],
                cellule["cell"]["userEnteredFormat"].get("backgroundColor"),
            ))
        return _Requete()


class _FakeSheets:
    def __init__(self, classeur):
        self._spreadsheets = _FakeSpreadsheets(classeur)

    def spreadsheets(self):
        return self._spreadsheets


# --------------------------------------------------------------------------
# Faux service Drive : juste de quoi lire/ecrire/supprimer le fichier
# d'attente dans le dossier de config.
# --------------------------------------------------------------------------
class _FakeMedia:
    def __init__(self, contenu):
        self.contenu = contenu


class _FakeDriveFiles:
    def __init__(self, fichiers):
        self.fichiers = fichiers          # {nom: contenu str}
        self.supprimes = []

    def list(self, q=None, fields=None):
        nom = q.split("name='")[1].split("'")[0]
        return _Requete({"files": [{"id": f"id_{nom}"}] if nom in self.fichiers else []})

    def get_media(self, fileId=None):
        return fileId

    def create(self, body=None, media_body=None, fields=None):
        self.fichiers[body["name"]] = media_body.contenu
        return _Requete({"id": f"id_{body['name']}"})

    def update(self, fileId=None, media_body=None):
        self.fichiers[fileId[3:]] = media_body.contenu
        return _Requete()

    def delete(self, fileId=None):
        self.supprimes.append(fileId)
        self.fichiers.pop(fileId[3:], None)
        return _Requete()


class _FakeDrive:
    def __init__(self, fichiers=None):
        self._files = _FakeDriveFiles(dict(fichiers or {}))

    def files(self):
        return self._files

    def attente(self):
        contenu = self._files.fichiers.get(ld.FICHIER_KM_EN_ATTENTE)
        return json.loads(contenu) if contenu else {}


def _fake_download(buf, fileId):
    """Remplace MediaIoBaseDownload : rend le contenu du faux Drive."""
    class _Dl:
        def __init__(self, contenu):
            self._contenu = contenu

        def next_chunk(self):
            buf.write(self._contenu.encode())
            return None, True
    return _Dl(_fake_download.drive._files.fichiers[fileId[3:]])


def _classeur(lignes_mois, lignes_attente=()):
    return {
        "SEPTEMBRE": [["N° cde", "Date", "Nom", "Prénom", "Distance"]]
                     + [list(l) for l in lignes_mois],
        ld.ONGLET_EN_ATTENTE: [["Nom", "Prénom", "Jour", "N° commande", "km"]]
                              + [list(l) for l in lignes_attente],
    }


def _etat(numero="54924251", minutes=0, signale=False):
    """Fichier d'attente contenant `numero`, en attente depuis `minutes`."""
    depuis = (MAINTENANT - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return {ld.FICHIER_KM_EN_ATTENTE: json.dumps(
        {numero: {"depuis": depuis, "signale": signale}})}


class _BaseKm(unittest.TestCase):
    def setUp(self):
        self._config_folder = cs.DRIVE_CONFIG_FOLDER_ID
        cs.DRIVE_CONFIG_FOLDER_ID = CONFIG_FOLDER_ID
        self._download = sys.modules["googleapiclient.http"].MediaIoBaseDownload
        self._upload = sys.modules["googleapiclient.http"].MediaIoBaseUpload
        sys.modules["googleapiclient.http"].MediaIoBaseDownload = _fake_download
        sys.modules["googleapiclient.http"].MediaIoBaseUpload = \
            lambda buf, mimetype=None, resumable=None: _FakeMedia(buf.getvalue().decode())

    def tearDown(self):
        cs.DRIVE_CONFIG_FOLDER_ID = self._config_folder
        sys.modules["googleapiclient.http"].MediaIoBaseDownload = self._download
        sys.modules["googleapiclient.http"].MediaIoBaseUpload = self._upload

    def _drive(self, fichiers=None):
        drive = _FakeDrive(fichiers)
        _fake_download.drive = drive
        return drive

    def _signaler(self, sheets, drive, envoye=True, manquants=None, levees=None,
                  rattrapees=None):
        emails = []
        ld.signaler_km_manquants(
            sheets, drive, SPREADSHEET_ID,
            lambda *args: emails.append(args) or envoye,
            maintenant=MAINTENANT, manquants=manquants,
            envoyer_levee=(lambda *args: levees.append(args)) if levees is not None else None,
            rattrapees=rattrapees)
        return emails


class TestInscriptionSansEmail(_BaseKm):
    """A l'inscription, un km introuvable n'envoie pas d'email : la commande
    est seulement mise en attente, le temps que Shopopop se synchronise."""

    def test_km_absent_signale_a_l_appelant_sans_email(self):
        appels = []
        sheets = _FakeSheets(_classeur([]))
        ld.shopopop.distance_km = lambda *a, **k: appels.append(a) or None
        ld._DELAI_RETRY_KM_SECONDES = 0
        km_manquant = ld.traiter_commande_livraison(
            sheets, SPREADSHEET_ID, "PAUMIER", "MARILYNE", "15/09/2026",
            numero_commande="54924251", maintenant=MAINTENANT,
            shopopop_token="jeton", shopopop_drive_id="14156")
        self.assertTrue(km_manquant)
        self.assertEqual(len(appels), 2, "un 2e essai est fait dans le meme run")

    def test_noter_km_en_attente_ouvre_le_compte_a_rebours(self):
        drive = self._drive()
        self.assertTrue(ld.noter_km_en_attente(drive, "54924251", maintenant=MAINTENANT))
        self.assertEqual(drive.attente(),
                         {"54924251": {"depuis": MAINTENANT.isoformat(timespec="seconds"),
                                       "signale": False}})

    def test_noter_km_en_attente_ne_redemarre_pas_le_compte_a_rebours(self):
        drive = self._drive(_etat(minutes=4))
        self.assertFalse(ld.noter_km_en_attente(drive, "54924251", maintenant=MAINTENANT))
        depuis = drive.attente()["54924251"]["depuis"]
        self.assertEqual(depuis,
                         (MAINTENANT - timedelta(minutes=4)).isoformat(timespec="seconds"))


class TestRetentative(_BaseKm):
    def test_retente_la_livraison_du_jour_et_a_venir(self):
        sheets = _FakeSheets(_classeur([
            ["54924251", "15/09", "PAUMIER", "MARILYNE", ""],       # aujourd'hui
            ["54924252", "16/09", "DUPONT", "JEAN", ""],            # demain
            ["54924253", "12/09", "MARTIN", "LEA", ""],             # livraison passee
            ["54924254", "15/09", "DURAND", "PAUL", "4,2"],         # deja renseignee
        ]))
        a_retenter = ld._km_a_retenter(
            ld.lister_km_manquants(sheets, SPREADSHEET_ID, MAINTENANT), MAINTENANT)
        self.assertEqual([(l[2], l[4]) for l in a_retenter],
                         [("PAUMIER", date(2026, 9, 15)), ("DUPONT", date(2026, 9, 16))])

    def test_ecrit_le_km_recupere_et_le_retire_des_manquants(self):
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", ""]]))
        ld.shopopop.distance_km = lambda token, drive, cible, nom: 5.43
        rattrapees = {}
        restants = ld.retenter_km_manquants(
            sheets, SPREADSHEET_ID, "jeton", "14156", maintenant=MAINTENANT,
            rattrapees=rattrapees)
        self.assertEqual(sheets.spreadsheets().values().updates,
                         [("'SEPTEMBRE'!E2", [[5.43]])])
        self.assertEqual(restants, [], "la ligne rattrapee ne doit plus etre signalable")
        self.assertEqual(rattrapees,
                         {"54924251": ("SEPTEMBRE", 2, "PAUMIER", "MARILYNE", 5.43)},
                         "l'alerte de cette commande pourra etre levee par email")


class TestSignalement(_BaseKm):
    def _sheets(self):
        return _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", ""]]))

    def test_pas_d_email_avant_le_delai(self):
        drive = self._drive(_etat(minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES - 1))
        self.assertEqual(self._signaler(self._sheets(), drive), [])
        self.assertFalse(drive.attente()["54924251"]["signale"])

    def test_email_une_fois_le_delai_ecoule(self):
        sheets, drive = self._sheets(), self._drive(
            _etat(minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES))
        self.assertEqual(self._signaler(sheets, drive),
                         [("54924251", "PAUMIER", "MARILYNE", "15/09/2026")])
        self.assertEqual(sheets.spreadsheets().formats,
                         [(0, 2, 4, ld._ORANGE_KM_A_COMPLETER)],
                         "la cellule km est surlignee pour la saisie manuelle")
        self.assertTrue(drive.attente()["54924251"]["signale"])

    def test_pas_de_second_email_pour_une_commande_deja_signalee(self):
        drive = self._drive(_etat(minutes=30, signale=True))
        self.assertEqual(self._signaler(self._sheets(), drive), [])

    def test_pas_de_marquage_si_l_email_echoue(self):
        sheets, drive = self._sheets(), self._drive(
            _etat(minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES))
        self.assertEqual(len(self._signaler(sheets, drive, envoye=False)), 1)
        self.assertEqual(sheets.spreadsheets().formats, [])
        self.assertFalse(drive.attente()["54924251"]["signale"],
                         "sans email parti, la commande reste a signaler")

    def test_km_recupere_entre_temps_sort_du_fichier_d_attente(self):
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", "5,43"]]))
        drive = self._drive(_etat(minutes=10))
        self.assertEqual(self._signaler(sheets, drive), [])
        self.assertEqual(drive.attente(), {})
        self.assertEqual(drive.files().supprimes, [f"id_{ld.FICHIER_KM_EN_ATTENTE}"],
                         "plus rien en attente : le fichier disparait, les reveils s'arretent")

    def test_commande_annulee_sort_du_fichier_d_attente(self):
        drive = self._drive(_etat(minutes=10))
        self.assertEqual(self._signaler(_FakeSheets(_classeur([])), drive), [])
        self.assertEqual(drive.attente(), {})

    def test_commande_trop_ancienne_abandonnee(self):
        drive = self._drive(_etat(minutes=(ld._RETENTION_KM_EN_ATTENTE_JOURS * 24 * 60) + 1))
        self.assertEqual(self._signaler(self._sheets(), drive), [])
        self.assertEqual(drive.attente(), {})

    def test_signale_aussi_l_onglet_en_attente(self):
        sheets = _FakeSheets(_classeur([], [["DUPONT", "JEAN", "20/09", "54924252", ""]]))
        drive = self._drive(
            _etat(numero="54924252", minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES))
        self.assertEqual(self._signaler(sheets, drive),
                         [("54924252", "DUPONT", "JEAN", "20/09/2026")])

    def test_levee_quand_le_km_arrive_apres_le_signalement(self):
        """Le km recupere par une retentative posterieure a l'email : la
        cellule perd son orange et un second email annule la demande de
        saisie manuelle."""
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", "5,43"]]))
        drive = self._drive(_etat(minutes=30, signale=True))
        levees = []
        self.assertEqual(
            self._signaler(sheets, drive, levees=levees, rattrapees={"54924251": ("SEPTEMBRE", 2, "PAUMIER", "MARILYNE", "5,43")}), [])
        self.assertEqual(levees, [("54924251", "PAUMIER", "MARILYNE", "5,43")])
        self.assertEqual(sheets.spreadsheets().formats, [(0, 2, 4, None)],
                         "le surlignage orange est retire")
        self.assertEqual(drive.attente(), {})

    def test_levee_dans_l_onglet_en_attente(self):
        sheets = _FakeSheets(_classeur([], [["DUPONT", "JEAN", "20/09", "54924252", "4,64"]]))
        drive = self._drive(_etat(numero="54924252", minutes=30, signale=True))
        levees = []
        self._signaler(sheets, drive, levees=levees, rattrapees={"54924252": (ld.ONGLET_EN_ATTENTE, 2, "DUPONT", "JEAN", "4,64")})
        self.assertEqual(levees, [("54924252", "DUPONT", "JEAN", "4,64")])
        self.assertEqual(sheets.spreadsheets().formats, [(1, 2, 4, None)])

    def test_km_saisi_a_la_main_retire_l_orange_sans_email(self):
        """Distance absente de `rattrapees` : elle vient d'etre saisie a la
        main, inutile de l'annoncer a celui qui l'a saisie — mais le
        surlignage, que l'email demandait d'effacer, part quand meme."""
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", "4,7"]]))
        drive = self._drive(_etat(minutes=30, signale=True))
        levees = []
        self._signaler(sheets, drive, levees=levees)
        self.assertEqual(levees, [])
        self.assertEqual(sheets.spreadsheets().formats, [(0, 2, 4, None)])
        self.assertEqual(drive.attente(), {})

    def test_pas_de_levee_si_la_commande_a_ete_annulee(self):
        """Ligne disparue du classeur : il n'y a ni cellule a nettoyer ni
        distance a annoncer."""
        drive = self._drive(_etat(minutes=30, signale=True))
        levees = []
        self._signaler(_FakeSheets(_classeur([])), drive, levees=levees)
        self.assertEqual(levees, [])
        self.assertEqual(drive.attente(), {})

    def test_pas_de_levee_pour_une_commande_jamais_signalee(self):
        """Le km arrive avant l'email : rien n'a ete demande, donc rien a
        lever (et aucune relecture du classeur)."""
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", "5,43"]]))
        drive = self._drive(_etat(minutes=2))
        levees = []
        self._signaler(sheets, drive, levees=levees, rattrapees={"54924251": ("SEPTEMBRE", 2, "PAUMIER", "MARILYNE", "5,43")})
        self.assertEqual(levees, [])
        self.assertEqual(sheets.spreadsheets().formats, [])

    def test_sans_fichier_d_attente_aucun_email(self):
        """Une ligne sans km jamais mise en attente (saisie a la main dans le
        classeur) n'est pas signalee."""
        self.assertEqual(self._signaler(self._sheets(), self._drive()), [])


class TestCycleComplet(_BaseKm):
    """Enchainement reel : inscription sans km, retentatives des minutes
    suivantes, puis email au bout du delai si Shopopop ne repond toujours
    pas."""

    def _run(self, sheets, drive, minutes, km_trouve=None):
        """Simule une execution d'auto_prepa.py `minutes` apres l'inscription :
        retentative Shopopop puis signalement. Retourne les emails envoyes ;
        les levees d'alerte sont empilees dans self.levees."""
        maintenant = MAINTENANT + timedelta(minutes=minutes)
        ld.shopopop.distance_km = lambda *a, **k: km_trouve
        rattrapees = {}
        manquants = ld.retenter_km_manquants(
            sheets, SPREADSHEET_ID, "jeton", "14156", maintenant=maintenant,
            rattrapees=rattrapees)
        emails = []
        self.levees = getattr(self, "levees", [])
        ld.signaler_km_manquants(
            sheets, drive, SPREADSHEET_ID,
            lambda *args: emails.append(args) or True,
            maintenant=maintenant, manquants=manquants,
            envoyer_levee=lambda *args: self.levees.append(args),
            rattrapees=rattrapees)
        return emails

    def test_email_au_bout_du_delai_si_shopopop_ne_repond_pas(self):
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", ""]]))
        drive = self._drive()
        ld.noter_km_en_attente(drive, "54924251", maintenant=MAINTENANT)
        self.assertTrue(ld.km_en_attente_actif(drive.attente()),
                        "le workflow doit etre relance tant que le km manque")

        self.assertEqual(self._run(sheets, drive, minutes=1), [], "trop tot")
        self.assertEqual(
            self._run(sheets, drive, minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES),
            [("54924251", "PAUMIER", "MARILYNE", "15/09/2026")])
        self.assertFalse(ld.km_en_attente_actif(drive.attente()),
                         "commande signalee : plus de reveil du workflow")
        self.assertEqual(self._run(sheets, drive, minutes=20), [],
                         "pas de rappel a chaque execution suivante")

    def test_alerte_levee_si_le_km_arrive_apres_l_email(self):
        """Cas de la commande 55282166 : Shopopop a mis plus longtemps que le
        delai a synchroniser la livraison. L'email de saisie manuelle est
        parti, puis la distance est arrivee d'elle-meme — une levee doit
        suivre, sinon la saisie reste demandee pour rien."""
        sheets = _FakeSheets(_classeur([], [["BONVALLET", "GINETTE", "16/09",
                                             "55282166", ""]]))
        drive = self._drive()
        ld.noter_km_en_attente(drive, "55282166", maintenant=MAINTENANT)

        self.assertEqual(
            self._run(sheets, drive, minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES),
            [("55282166", "BONVALLET", "GINETTE", "16/09/2026")])
        self.assertEqual(self.levees, [])

        # Run suivant : Shopopop finit par rendre la distance, que la
        # retentative ecrit dans la colonne km.
        self.assertEqual(
            self._run(sheets, drive, minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES + 5,
                      km_trouve=4.64),
            [], "pas de nouvelle demande de saisie")
        self.assertEqual(self.levees, [("55282166", "BONVALLET", "GINETTE", 4.64)])
        self.assertEqual(sheets.spreadsheets().formats[-1], (1, 2, 4, None),
                         "la cellule km n'est plus surlignee")
        self.assertEqual(drive.attente(), {})

    def test_pas_d_email_si_shopopop_repond_avant_le_delai(self):
        sheets = _FakeSheets(_classeur([["54924251", "15/09", "PAUMIER", "MARILYNE", ""]]))
        drive = self._drive()
        ld.noter_km_en_attente(drive, "54924251", maintenant=MAINTENANT)

        self.assertEqual(self._run(sheets, drive, minutes=1), [])
        # 2e run : Shopopop a synchronise la commande entre-temps.
        sheets._spreadsheets._classeur["SEPTEMBRE"][1][4] = "5,43"
        self.assertEqual(self._run(sheets, drive, minutes=2, km_trouve=5.43), [])
        self.assertEqual(
            self._run(sheets, drive, minutes=ld._DELAI_SIGNALEMENT_KM_MINUTES), [],
            "le km est arrive a temps : aucun email, meme apres le delai")
        self.assertEqual(drive.attente(), {})


class TestReveilWorkflow(_BaseKm):
    def test_km_en_attente_actif(self):
        self.assertTrue(ld.km_en_attente_actif({"1": {"signale": False}}))
        self.assertFalse(ld.km_en_attente_actif({"1": {"signale": True}}))
        self.assertFalse(ld.km_en_attente_actif({}))


if __name__ == "__main__":
    unittest.main()
