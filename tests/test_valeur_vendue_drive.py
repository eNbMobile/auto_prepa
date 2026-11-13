#!/usr/bin/env python3
"""
Tests de la valeur vendue au Drive (UVC × prix du stock du matin) et de son
inscription dans CA DRIVE AAAA.xlsx (onglet RÉALISATION, K58:R113).

Lancement : python3 -m unittest discover -s tests
"""

import io
import os
import sys
import unittest
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import valeur_vendue_drive as vvd


def _ligne(n, cellules):
    return f'<row r="{n}">' + "".join(cellules) + "</row>"


def _onglet_modele():
    """Onglet minimal : tableau CA MAGASIN en A58:H113, comme le classeur réel."""
    lignes = [_ligne(1, ['<c r="A1" s="4" t="s"><v>0</v></c>'])]
    lignes.append(_ligne(58, ['<c r="A58" s="4" t="s"><v>1</v></c>', '<c r="B58" s="6"/>']))
    lignes.append(_ligne(59, ['<c r="A59" s="18"/>', '<c r="B59" s="19" t="s"><v>2</v></c>',
                              '<c r="H59" s="23" t="s"><v>3</v></c>']))
    for n in range(60, 113):
        lignes.append(_ligne(n, [f'<c r="A{n}" s="32" t="s"><v>4</v></c>',
                                 f'<c r="B{n}" s="44"><v>1000</v></c>']
                             + [f'<c r="{c}{n}" s="44"/>' for c in "CDEFG"]))
    lignes.append(_ligne(113, ['<c r="A113" s="157" t="s"><v>3</v></c>']))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{vvd._NS}"><sheetData>' + "".join(lignes) +
            '</sheetData><mergeCells count="1"><mergeCell ref="A58:H58"/></mergeCells></worksheet>')


def _classeur():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml",
                   f'<workbook xmlns="{vvd._NS}" xmlns:r="{vvd._ONS}"><sheets>'
                   '<sheet name="RÉALISATION N-1" sheetId="1" r:id="rId1"/>'
                   '<sheet name="RÉALISATION" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="{vvd._RNS}">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", "N-1 inchangé")
        z.writestr("xl/worksheets/sheet2.xml", _onglet_modele())
    return buf.getvalue()


def _onglet(contenu_xlsx):
    with zipfile.ZipFile(io.BytesIO(contenu_xlsx)) as z:
        return z.read("xl/worksheets/sheet2.xml").decode(), z.read("xl/worksheets/sheet1.xml")


class TestCalcul(unittest.TestCase):
    def test_somme_uvc_par_prix(self):
        ventes = {"3256225733835": 3, "3256225454952": 2, "0000000000001": 5}
        prix = {"3256225733835": 2.23, "3256225454952": 2.69}
        valeur, sans_prix = vvd.calculer_valeur_vendue(ventes, prix)
        self.assertEqual(valeur, round(3 * 2.23 + 2 * 2.69, 2))
        self.assertEqual(sans_prix, ["0000000000001"])


class TestClasseursCde(unittest.TestCase):
    def test_classeurs_retenus(self):
        for c in ("DRIVE EPICERIE", "Drive Épicerie", "DRIVE DPH", "DRIVE LIQUIDES",
                  "DRIVE S43 TRAFIC HALLOWEEN", "DRIVE S31", "**DRIVE S22 GROS VOLUMES 1**",
                  "DRIVE ANIMAUX", "DRIVE PALETTE COMPLETE", "DRIVE CARTE U AOÛT",
                  "DRIVE CARTE U SEPTEMBRE"):
            self.assertTrue(vvd.est_classeur_cde(c), c)
        for c in ("**DRIVE LGV**", "**DRIVE LGV NE PAS TRANSM**", "**DRIVE STOCK MAGASIN**",
                  "**DRIVE DÉLOTAGE**", "DRIVE PRODUIT A ENLEVER", "DRIVE SPECIAL", ""):
            self.assertFalse(vvd.est_classeur_cde(c), c)

    def test_filtre_selon_classeur_du_jour(self):
        ventes = {"1": 2, "2": 1, "3": 4, "4": 1}
        classeurs = {"1": "DRIVE EPICERIE", "2": "**DRIVE LGV**", "3": "DRIVE S45 TRAFIC"}
        self.assertEqual(vvd.filtrer_classeurs_cde(ventes, classeurs), {"1": 2, "3": 4})


class TestInscription(unittest.TestCase):
    def test_cellule_du_jour_et_totaux(self):
        # Samedi 07/11/2026 = S 45 (ligne 104), colonne Q
        xml, autre = _onglet(vvd.modifier_classeur(_classeur(), date(2026, 11, 7), 1931.02))
        self.assertIn('<c r="Q104" s="44"><v>1931.02</v></c>', xml)
        self.assertIn('<f>SUM(L104:Q104)</f><v>1931.02</v>', xml)
        self.assertIn('<f>SUM(Q60:Q111)</f><v>1931.02</v>', xml)
        self.assertIn('<t>VALEUR VENDUE DRIVE</t>', xml)
        self.assertIn('<mergeCell ref="K58:R58"/>', xml)
        self.assertIn('<mergeCells count="2">', xml)
        # Libellés recopiés du tableau CA MAGASIN, qui reste intact
        self.assertIn('<c r="K104" s="32" t="s"><v>4</v></c>', xml)
        self.assertIn('<c r="B104" s="44"><v>1000</v></c>', xml)
        self.assertEqual(autre, b"N-1 inchang\xc3\xa9")

    def test_valeurs_conservees_et_reecriture(self):
        b = vvd.modifier_classeur(_classeur(), date(2026, 11, 6), 1234.5)   # vendredi
        b = vvd.modifier_classeur(b, date(2026, 11, 7), 100)                # samedi
        b = vvd.modifier_classeur(b, date(2026, 11, 7), 200)                # relance
        xml, _ = _onglet(b)
        self.assertIn('<c r="P104" s="44"><v>1234.5</v></c>', xml)
        self.assertIn('<c r="Q104" s="44"><v>200</v></c>', xml)
        self.assertIn('<f>SUM(L104:Q104)</f><v>1434.5</v>', xml)
        self.assertEqual(xml.count('<mergeCell ref="K58:R58"/>'), 1)
        self.assertEqual(xml.count('<c r="Q104"'), 1)

    def test_tableau_classeurs_cde(self):
        # Samedi 07/11/2026 = S 45 (ligne 104), colonne Z ; total en AA
        b = vvd.modifier_classeur(_classeur(), {date(2026, 11, 7): 1931.02},
                                  valeurs_classeurs={date(2026, 11, 7): 1500.5})
        b = vvd.modifier_classeur(b, {}, valeurs_classeurs={date(2026, 11, 6): 10})
        xml, _ = _onglet(b)
        self.assertIn('<c r="Q104" s="44"><v>1931.02</v></c>', xml)
        self.assertIn('<c r="Z104" s="44"><v>1500.5</v></c>', xml)
        self.assertIn('<c r="Y104" s="44"><v>10</v></c>', xml)
        self.assertIn('<f>SUM(U104:Z104)</f><v>1510.5</v>', xml)
        self.assertIn('<f>SUM(Z60:Z111)</f><v>1500.5</v>', xml)
        self.assertIn('<t>VALEUR VENDUE DRIVE CLASSEURS CDE</t>', xml)
        self.assertIn('<mergeCell ref="T58:AA58"/>', xml)
        self.assertIn('<c r="T104" s="32" t="s"><v>4</v></c>', xml)
        # Ordre des colonnes conservé (R avant T avant Z avant AA)
        ligne = xml[xml.index('<row r="104"'):]
        ligne = ligne[:ligne.index("</row>")]
        self.assertLess(ligne.index('r="R104"'), ligne.index('r="T104"'))
        self.assertLess(ligne.index('r="Z104"'), ligne.index('r="AA104"'))

    def test_semaine_1(self):
        xml, _ = _onglet(vvd.modifier_classeur(_classeur(), date(2026, 1, 2), 50))
        self.assertIn('<c r="P60" s="44"><v>50</v></c>', xml)


if __name__ == "__main__":
    unittest.main()
