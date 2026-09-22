#!/usr/bin/env python3
"""
Tests du WF RenseigneCA : lecture du nombre de produits d'un bon de commande
et écriture ciblée des deux cellules du jour dans l'onglet RÉALISATION du
classeur CA DRIVE (sans toucher au reste du .xlsx).

Lancement : python3 -m unittest discover -s tests
"""

import io
import os
import sys
import unittest
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import renseigne_ca as rc


WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="EFFECTIF" sheetId="1" r:id="rId1"/>'
    '<sheet name="RÉALISATION" sheetId="2" r:id="rId2"/></sheets><calcPr/></workbook>'
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="x" Target="worksheets/sheet2.xml"/></Relationships>'
)
SHARED = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<si><t>S 38</t></si><si><t>S 39</t></si></sst>'
)
FEUILLE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    '<row r="40"><c r="K40" s="102" t="s"><v>0</v></c><c r="L40" s="84"><v>109.0</v></c>'
    '<c r="T40" s="102" t="s"><v>0</v></c><c r="U40" s="84"><v>3656.0</v></c></row>'
    '<row r="41"><c r="K41" s="102" t="s"><v>1</v></c><c r="L41" s="84"><v>101.0</v></c>'
    '<c r="M41" s="159"/><c r="R41" s="115"><f t="shared" si="6"/><v>101</v></c>'
    '<c r="T41" s="102" t="s"><v>1</v></c><c r="U41" s="159"/>'
    '<c r="AA41" s="115"><f t="shared" si="7"/><v>0</v></c></row>'
    '</sheetData></worksheet>'
)
AUTRE_FEUILLE = '<worksheet><sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'


def _xlsx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", RELS)
        zf.writestr("xl/sharedStrings.xml", SHARED)
        zf.writestr("xl/worksheets/sheet1.xml", AUTRE_FEUILLE)
        zf.writestr("xl/worksheets/sheet2.xml", FEUILLE)
    return buf.getvalue()


def _lire(contenu, nom):
    with zipfile.ZipFile(io.BytesIO(contenu)) as zf:
        return zf.read(nom).decode("utf-8")


class TestNbProduitsBon(unittest.TestCase):
    def test_total_de_la_commande(self):
        texte = "BVP > NON\nTotal de la commande\n35 articles\n39 produits\nFRAIS"
        self.assertEqual(rc.nb_produits_bon(texte), 39)

    def test_singulier(self):
        self.assertEqual(rc.nb_produits_bon("Total de la commande 1 article 1 produit"), 1)

    def test_absent(self):
        self.assertIsNone(rc.nb_produits_bon("Bon d'encaissement sans total"))


class TestRenseignerXlsx(unittest.TestCase):
    def test_mardi_semaine_39(self):
        # 22/09/2026 : mardi de la semaine ISO 39 → M41 et V41.
        out = rc.renseigner_xlsx(_xlsx(), date(2026, 9, 22), 77, 2890)
        xml = _lire(out, "xl/worksheets/sheet2.xml")
        self.assertIn('<c r="M41" s="159"><v>77</v></c>', xml)
        # V41 n'existait pas : insérée entre U41 et AA41.
        self.assertIn('<c r="U41" s="159"/><c r="V41"><v>2890</v></c><c r="AA41"', xml)
        # Le reste est intact (autre semaine, formules, autre onglet).
        self.assertIn('<c r="L40" s="84"><v>109.0</v></c>', xml)
        self.assertIn('<c r="L41" s="84"><v>101.0</v></c>', xml)
        self.assertIn('<f t="shared" si="6"/>', xml)
        self.assertEqual(_lire(out, "xl/worksheets/sheet1.xml"), AUTRE_FEUILLE)
        self.assertIn('<calcPr fullCalcOnLoad="1"/>', _lire(out, "xl/workbook.xml"))

    def test_relance_ecrase_la_valeur(self):
        out = rc.renseigner_xlsx(_xlsx(), date(2026, 9, 21), 90, 3000)
        out = rc.renseigner_xlsx(out, date(2026, 9, 21), 95, 3100)
        xml = _lire(out, "xl/worksheets/sheet2.xml")
        self.assertIn('<c r="L41" s="84"><v>95</v></c>', xml)
        self.assertIn('<c r="U41" s="159"><v>3100</v></c>', xml)
        self.assertNotIn("<v>90</v>", xml)

    def test_semaine_absente(self):
        with self.assertRaises(ValueError):
            rc.renseigner_xlsx(_xlsx(), date(2026, 10, 1), 1, 1)


if __name__ == "__main__":
    unittest.main()
