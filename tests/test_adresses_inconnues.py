import os
import sys
import tempfile
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adresses_inconnues as ai

ENTETE = "M,1,4,6,0,54.20,10h05\n"
INFOS = "MARDI 13/10/2026 - 10h30-11h00,56209742,Retrait,Paiement en ligne,M. X Y,Pas de sacs"


def ligne(gencod, libelle, adresse, nom):
    return (f"{gencod};{libelle};2.50;0.00;1;OUI;0;0;N;{INFOS};"
            f"{adresse};{nom};12;00/00/0000\n")


BON = [
    ENTETE,
    ligne("3256225454952", "THON ENTIER LISTAO", "R1-GG-1-4", "EPICERIE SALEE;F"),
    ligne("3168930001911", "BUGLES CACAHUETE 85G", "M1-AB-9-9", "ADRESSE INCONNUE;W"),
    ligne("3760000000017", "PRODUIT SANS FICHE", "M1-ZZ-0-0", "ADRESSE INCONNUE;W"),
    ligne("3033490004743", "YAOURT NATURE", "AUCUNE ADRESSE", "AUCUNE ADRESSE;L"),
    ligne("3017620422003", "PATE A TARTINER", "AUCUNE ADRESSE", "EPICERIE SUCREE;F"),
    "-3;" + ligne("3045320094084", "CAFE MOULU", "M2-QQ-1-1", "ADRESSE INCONNUE;W"),
    ligne("3700000000025", "SANS ADRESSE NI NOMENCLATURE", "M1-ZZ-0-0", "NON ADRESSÉ;V"),
    ligne("0200123000004", "POMMES GALA VRAC", "AUCUNE ADRESSE", "FRUITS;R"),
    ligne("0200456000007", "CAROTTES VRAC", "AUCUNE ADRESSE", "LEGUMES;S"),
    ligne("3250390000013", "BAGUETTE", "AUCUNE ADRESSE", "BVP;U"),
    ligne("3250390000020", "PAIN DE MIE", "M2-MM-3-1", "PAIN DE MIE1;U"),
]


class FauxFichiers:
    def __init__(self, stock):
        self.stock = stock  # {nom: contenu}
        self.renommes = {}  # {id: nouveau nom}, rapport du soir passé entre-temps

    def list(self, q, **_):
        nom = q.split("name='", 1)[1].split("'", 1)[0] if "name='" in q else None
        return _Exec({"files": [{"id": nom}] if nom in self.stock or nom in ("GITHUB", ai.DOSSIER) else []})

    def get_media(self, fileId):
        return fileId

    def get(self, fileId, fields=None):
        return _Exec({"name": self.renommes.get(fileId, fileId)})

    def update(self, fileId, media_body=None, body=None):
        self.stock[fileId] = media_body._fd.getvalue().decode()
        return _Exec({})

    def create(self, body, media_body=None, fields=None):
        self.stock[body["name"]] = media_body._fd.getvalue().decode() if media_body else ""
        return _Exec({"id": body["name"]})


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


class FauxDrive:
    def __init__(self, stock):
        self._f = FauxFichiers(stock)

    def files(self):
        return self._f


class TestExtraction(unittest.TestCase):
    def test_seuls_les_non_adresses_sont_retenus(self):
        # Replacés via leur nomenclature compris ; fruits (R), légumes (S)
        # et BVP (U) exclus.
        self.assertEqual(ai.extraire_produits_non_adresses(BON), [
            ("3168930001911", "BUGLES CACAHUETE 85G", "M1-AB-9-9"),
            ("3760000000017", "PRODUIT SANS FICHE", ""),
            ("3033490004743", "YAOURT NATURE", ""),
            ("3017620422003", "PATE A TARTINER", ""),
            ("3045320094084", "CAFE MOULU", "M2-QQ-1-1"),
            ("3700000000025", "SANS ADRESSE NI NOMENCLATURE", ""),
        ])

    def test_regroupement_par_gencod(self):
        contenu = ("3168930001911;BUGLES;M1-AB-9-9;111\n"
                   "3168930001911;BUGLES;M1-AB-9-9;222\n"
                   "3760000000017;SANS FICHE;;111\n")
        p = ai.regrouper(contenu)
        self.assertEqual(p["3168930001911"]["commandes"], ["111", "222"])
        self.assertEqual(p["3760000000017"]["adresse"], "")

    def test_produits_adresses_retires(self):
        # Seuls restent les produits absents de gencod_adresses.csv : une
        # adresse hors chemin (AUCUNE ADRESSE / ADRESSE INCONNUE dans le bon)
        # n'en fait pas un produit non adressé.
        p = ai.regrouper("5900130030630;NUII;;111\n"
                         "3529380020097;MORBIER;;111\n"
                         "3168930001911;BUGLES;M1-AB-9-9;111\n"
                         "0201781000009;BOURGUIGNON;;111\n")
        p = ai.retirer_adresses(p, {"5900130030630": "M2-LL-1-10",
                                    "3168930001911": "M1-AB-9-9",
                                    "0201781000009": "M2-KK-4-1"})
        self.assertEqual(list(p), ["3529380020097"])

    def test_pdf_genere(self):
        produits = ai.regrouper("3168930001911;BUGLES;M1-AB-9-9;111\n123;COURT;;111\n")
        with tempfile.TemporaryDirectory() as d:
            chemin = ai.generer_pdf(produits, date(2026, 10, 13), os.path.join(d, "t.pdf"))
            self.assertGreater(os.path.getsize(chemin), 1000)


class TestFichierDuJour(unittest.TestCase):
    def setUp(self):
        self._orig = ai._telecharger_texte
        ai._telecharger_texte = lambda svc, fid: svc.files().stock[fid]

    def tearDown(self):
        ai._telecharger_texte = self._orig

    def test_ajout_puis_regeneration_sans_doublon(self):
        jour = date(2026, 10, 13)
        nom = ai.nom_fichier_jour(jour)
        stock = {}
        drive = FauxDrive(stock)
        ai.noter_produits_non_adresses(drive, "111", [("1", "A", "")], jour)
        ai.noter_produits_non_adresses(drive, "222", [("2", "B", "M1")], jour)
        ai.noter_produits_non_adresses(drive, "111", [("3", "C", "")], jour)  # regeneree
        self.assertEqual(stock[nom].splitlines(), ["2;B;M1;222", "3;C;;111"])

    def test_fichier_envoye_pendant_l_ecriture(self):
        jour = date(2026, 10, 13)
        nom = ai.nom_fichier_jour(jour)
        stock = {nom: "1;A;;111\n"}
        drive = FauxDrive(stock)
        drive.files().renommes[nom] = nom.replace(".txt", "_envoye.txt")
        ai.noter_produits_non_adresses(drive, "222", [("2", "B", "")], jour)
        # La ligne de la commande 222 est reportee dans le fichier du
        # lendemain au lieu d'etre perdue dans le fichier deja parti.
        demain = ai.nom_fichier_jour(date(2026, 10, 14))
        self.assertEqual(stock[demain].splitlines(), ["2;B;;222"])

    def test_apres_le_rapport_du_soir_fichier_du_lendemain(self):
        # Fichier du 13 deja envoye : les bons generes jusqu'a minuit vont
        # dans le fichier du 14, envoye le lendemain soir avec les autres.
        envoye = ai.nom_fichier_jour(date(2026, 10, 13)).replace(".txt", "_envoye.txt")
        stock = {envoye: "1;A;;111\n"}
        drive = FauxDrive(stock)
        soir = datetime(2026, 10, 13, 22, 30, tzinfo=ai._TZ)
        self.assertEqual(ai.jour_du_fichier(drive, ai.DOSSIER, soir), date(2026, 10, 14))
        orig = ai.jour_du_fichier
        ai.jour_du_fichier = lambda svc, d: orig(svc, d, soir)
        try:
            ai.noter_produits_non_adresses(drive, "222", [("2", "B", "")])
        finally:
            ai.jour_du_fichier = orig
        self.assertEqual(stock[ai.nom_fichier_jour(date(2026, 10, 14))].splitlines(),
                         ["2;B;;222"])
        self.assertEqual(stock[envoye], "1;A;;111\n")
        self.assertNotIn(ai.nom_fichier_jour(date(2026, 10, 13)), stock)

    def test_avant_le_rapport_du_soir_fichier_du_jour(self):
        drive = FauxDrive({ai.nom_fichier_jour(date(2026, 10, 13)): "1;A;;111\n"})
        matin = datetime(2026, 10, 13, 9, 0, tzinfo=ai._TZ)
        self.assertEqual(ai.jour_du_fichier(drive, ai.DOSSIER, matin), date(2026, 10, 13))
        # Apres minuit : comportement normal (le fichier envoye est celui de la veille).
        envoye = ai.nom_fichier_jour(date(2026, 10, 13)).replace(".txt", "_envoye.txt")
        drive = FauxDrive({envoye: ""})
        nuit = datetime(2026, 10, 14, 0, 5, tzinfo=ai._TZ)
        self.assertEqual(ai.jour_du_fichier(drive, ai.DOSSIER, nuit), date(2026, 10, 14))

    def test_commandes_annulees_ignorees(self):
        p = ai.regrouper("1;A;;111\n1;A;;222\n2;B;;222\n", annulees={"222"})
        self.assertEqual(list(p), ["1"])
        self.assertEqual(p["1"]["commandes"], ["111"])

    def test_rien_a_noter(self):
        stock = {}
        ai.noter_produits_non_adresses(FauxDrive(stock), "111", [])
        self.assertEqual(stock, {})


if __name__ == "__main__":
    unittest.main()
