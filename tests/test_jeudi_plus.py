import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collecte_jeudi_plus as cjp
import jeudi_plus as jp

INFOS = "JEUDI 29/10/2026 - 10h30-11h00,56209742,Retrait,Paiement en ligne,M. X Y,Pas de sacs"
WHISKY = "5000267014203"
RHUM = "3263280115018"
AUTRE = "3017620422003"


def ligne(gencod, libelle, qte):
    return (f"{gencod};{libelle};24,90;0.00;{qte};OUI;0;0;N;{INFOS};"
            f"M1-AB-1-1;ALCOOLS;F;12;00/00/0000\n")


BON = [
    "M,1,4,6,0,54.20,10h05\n",
    ligne(WHISKY, "WHISKY JW RED 70CL", 2),
    ligne(AUTRE, "PATE A TARTINER", 1),
    "-3;" + ligne(RHUM, "RHUM AMBRE 70CL", 1),
    ligne(WHISKY, "WHISKY JW RED 70CL", 1),
]
EANS = {WHISKY: "WHISKY JW RED", RHUM: "", "3560070000005": "WHISKY U 1L"}


class FauxFichiers:
    def __init__(self, stock):
        self.stock = stock

    def list(self, q, **_):
        nom = q.split("name='", 1)[1].split("'", 1)[0]
        return _Exec({"files": [{"id": nom}] if nom in self.stock or nom in ("GITHUB", jp.DOSSIER) else []})

    def get_media(self, fileId):
        return fileId

    def update(self, fileId, media_body=None):
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


class FauxTelechargement:
    def __init__(self, buf, stock_id):
        buf.write(FauxDrive.stock[stock_id].encode())

    def next_chunk(self):
        return None, True


class TestExtraction(unittest.TestCase):
    def test_lecture_liste(self):
        self.assertEqual(jp.lire_liste_eans("ean;libelle\n5000267014203;JW RED\n0263280115011\n\n"),
                         {WHISKY: "JW RED", "0263280115011": ""})

    def test_quantites_cumulees_et_prefixe_retire(self):
        self.assertEqual(jp.extraire_quantites(BON, EANS), {
            WHISKY: ("WHISKY JW RED 70CL", 3),
            RHUM: ("RHUM AMBRE 70CL", 1),
        })

    def test_recap_tous_les_produits_plus_vendus_en_tete(self):
        lignes = [f"2026-10-29;111;29/10/2026;{WHISKY};JW;3",
                  f"2026-10-29;222;30/10/2026;{WHISKY};JW;1",
                  f"2026-10-29;222;30/10/2026;{RHUM};RHUM AMBRE;2",
                  f"2026-10-28;333;29/10/2026;{RHUM};RHUM AMBRE;5"]
        self.assertEqual(jp.recapituler(lignes, EANS, "2026-10-29").splitlines(), [
            jp.ENTETE_RECAP,
            f"{WHISKY};WHISKY JW RED;4;2",
            f"{RHUM};RHUM AMBRE;2;1",
            "3560070000005;WHISKY U 1L;0;0",
        ])


class TestReleveDrive(unittest.TestCase):
    def setUp(self):
        import googleapiclient.http as gh
        self._dl = gh.MediaIoBaseDownload
        self.stock = {jp.FICHIER_EANS: "ean;libelle\n" + "".join(f"{e};{l}\n" for e, l in EANS.items())}
        FauxDrive.stock = self.stock
        gh.MediaIoBaseDownload = FauxTelechargement
        jp._eans_cache = None
        self.drive = FauxDrive(self.stock)

    def tearDown(self):
        import googleapiclient.http as gh
        gh.MediaIoBaseDownload = self._dl
        jp._eans_cache = None

    def recap(self):
        return self.stock["jeudi_plus_2026-10-29.csv"].splitlines()

    def test_noter_regenerer_puis_annuler(self):
        jour = date(2026, 10, 29)
        jp.noter_commande(self.drive, "111", BON, "29/10/2026", jour=jour)
        jp.noter_commande(self.drive, "222", BON[:2], "30/10/2026", jour=jour)
        self.assertEqual(self.recap()[1], f"{WHISKY};WHISKY JW RED;5;2")
        # Régénération : les anciennes lignes de 111 sont remplacées.
        jp.noter_commande(self.drive, "111", BON[:2], "29/10/2026", jour=jour)
        self.assertEqual(self.recap()[1:3], [f"{WHISKY};WHISKY JW RED;4;2",
                                             f"{RHUM};;0;0"])
        jp.retirer_commande(self.drive, "222")
        self.assertEqual(self.stock[jp.FICHIER_COMMANDES].splitlines(), [
            jp.ENTETE_COMMANDES,
            f"2026-10-29;111;29/10/2026;{WHISKY};WHISKY JW RED 70CL;2",
        ])
        self.assertEqual(self.recap()[1], f"{WHISKY};WHISKY JW RED;2;1")

    def test_sans_liste_rien_n_est_ecrit(self):
        del self.stock[jp.FICHIER_EANS]
        jp.noter_commande(self.drive, "111", BON, "29/10/2026", jour=date(2026, 10, 29))
        self.assertNotIn(jp.FICHIER_COMMANDES, self.stock)


class TestCollecte(unittest.TestCase):
    def test_ean_de_l_url_image(self):
        url = ("https://www.coursesu.com/dw/image/v2/BBQX_PRD/on/demandware.static/-/"
               f"Sites-digitalu-master-catalog/default/dw1234567/{WHISKY}_A.jpg?sw=300")
        self.assertEqual(cjp.eans_dans_url(url), [WHISKY])
        self.assertEqual(cjp.eans_dans_url("https://x/img/1234567890123.jpg"), [])  # clé fausse

    def test_une_entree_par_vignette_lien_en_repli(self):
        produits = [
            ([f"https://x/{WHISKY}.jpg", f"https://x/{WHISKY}.jpg?sw=600"], [], "JW RED"),
            (["https://x/sans-ean.jpg"], [f"https://x/p/rhum/{RHUM}.html"], "RHUM"),
            (["https://x/logo.png"], ["https://x/aide"], "Logo"),
        ]
        self.assertEqual(cjp.eans_des_produits(produits), {WHISKY: "JW RED", RHUM: "RHUM"})

    def test_liste_collee(self):
        self.assertEqual(list(cjp.eans_du_texte(f"{WHISKY}, {RHUM}\n1234567890123")), [WHISKY, RHUM])

    def test_page_dans_chromium(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            self.skipTest("playwright absent")
        if os.path.exists("/opt/pw-browsers/chromium"):
            os.environ.setdefault("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
        tuiles = "".join(
            f'<div class="product-tile"><a href="/p/x/{e}.html" title="P{i}">'
            f'<img data-src="/img/{e}_A.jpg" src="data:image/gif;base64,R0lGOD" alt="P{i}"></a></div>'
            for i, e in enumerate([WHISKY, RHUM]))
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(f"<html><body><button>Tout accepter</button>{tuiles}</body></html>")
        try:
            self.assertEqual(cjp.collecter_page("file://" + f.name), {WHISKY: "P0", RHUM: "P1"})
        finally:
            os.remove(f.name)


if __name__ == "__main__":
    unittest.main()
