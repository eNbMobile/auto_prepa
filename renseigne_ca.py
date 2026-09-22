#!/usr/bin/env python3
"""
Renseigne le nombre de commandes et le nombre de produits Drive du jour dans
le classeur "CA DRIVE 2026", onglet "RÉALISATION".

- Nombre de commandes : nombre de BonDeCommande_xxx.pdf du dossier Drive
  BDC/MM_AAAA/JJ_MM du jour (hors commandes annulées / remplacées, comme les
  ventes du jour).
- Nombre de produits : somme des "Total de la commande N articles P produits"
  de chaque bon (P).

La ligne est celle de la semaine ISO du jour ("S 39"), la colonne celle du jour
de la semaine : blocs "NB COMMANDES DRIVE" (L → Q) et "NB PRODUITS DRIVE"
(U → Z), du lundi au samedi. Le dimanche n'a pas de colonne : rien à faire.

Le classeur est un .xlsx stocké sur Drive (pas un Google Sheet) : on le
télécharge, on ne modifie QUE les deux cellules du jour directement dans le
XML de la feuille (styles, formules, commentaires et autres onglets intacts),
puis on renvoie le fichier sur Drive.

Usage : renseigne_ca.py [--date JJ/MM/AAAA]   (défaut : aujourd'hui, Paris)
"""
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import date, datetime

import controle_stocks as cs

# ID du classeur "CA DRIVE 2026.xlsx" (drive.google.com/file/d/<id>).
# Utilisé si absent de config.json (clé "ca_drive_spreadsheet_id").
CA_SPREADSHEET_ID_DEFAUT = "1Z4Ao7OVzRhKLIUNeot1jfQwljDGi2mCo"
ONGLET_REALISATION = "RÉALISATION"

# Colonnes du lundi (index 0) au samedi (index 5).
COLONNES_COMMANDES = ["L", "M", "N", "O", "P", "Q"]
COLONNES_PRODUITS  = ["U", "V", "W", "X", "Y", "Z"]
# Colonnes portant le libellé de semaine ("S 39") de chaque bloc.
COLONNE_SEMAINE_COMMANDES = "K"
COLONNE_SEMAINE_PRODUITS  = "T"

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL  = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_OREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_RE_PRODUITS = re.compile(
    r"Total\s+de\s+la\s+commande\s+\d+\s+articles?\s+(\d+)\s+produits?", re.I)
_RE_PRODUITS_SEUL = re.compile(r"\b(\d+)\s+produits?\b", re.I)


# ─────────────────────────────────────────────────────────────────
# Lecture des bons de commande
# ─────────────────────────────────────────────────────────────────

def nb_produits_bon(texte):
    """Nombre de produits d'un bon (texte pdftotext), ou None si introuvable."""
    m = _RE_PRODUITS.search(texte) or _RE_PRODUITS_SEUL.search(texte)
    return int(m.group(1)) if m else None


def compter_commandes_produits(jour):
    """(nb_commandes, nb_produits, bons_illisibles) pour le jour donné,
    ou None si les bons du jour sont introuvables."""
    bdc_dir = cs.telecharger_bdc_depuis_drive(jour)
    if not bdc_dir or not os.path.isdir(bdc_dir):
        return None

    pdfs = sorted(f for f in os.listdir(bdc_dir)
                  if f.startswith("BonDeCommande_") and f.endswith(".pdf"))

    annulees = cs.numeros_annules_registre()
    retenus = []
    for pdf in pdfs:
        numero = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")
        if numero in annulees:
            print(f"  Commande {numero} annulée/remplacée : non comptée.")
            continue
        retenus.append(pdf)
    if not retenus:
        return None

    nb_produits = 0
    illisibles = []
    for pdf in retenus:
        pt = subprocess.run(["pdftotext", os.path.join(bdc_dir, pdf), "-"],
                            capture_output=True, text=True)
        n = nb_produits_bon(pt.stdout)
        if n is None:
            illisibles.append(pdf)
            continue
        nb_produits += n
    return len(retenus), nb_produits, illisibles


# ─────────────────────────────────────────────────────────────────
# Écriture dans le .xlsx (patch XML ciblé)
# ─────────────────────────────────────────────────────────────────

_RE_CELLULE = re.compile(r'<c\s+r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


def _col_index(col):
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _chemin_feuille(zf, nom_onglet):
    """Chemin de la feuille XML d'un onglet (ex. xl/worksheets/sheet6.xml)."""
    import xml.etree.ElementTree as ET
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rid = None
    for sh in wb.iter(f"{{{NS_MAIN}}}sheet"):
        if sh.get("name", "").strip().upper() == nom_onglet.upper():
            rid = sh.get(f"{{{NS_OREL}}}id")
            break
    if rid is None:
        raise ValueError(f"onglet {nom_onglet!r} introuvable")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.iter(f"{{{NS_REL}}}Relationship"):
        if rel.get("Id") == rid:
            cible = rel.get("Target", "").lstrip("/")
            return cible if cible.startswith("xl/") else f"xl/{cible}"
    raise ValueError(f"feuille de l'onglet {nom_onglet!r} introuvable")


def _chaines_partagees(zf):
    import xml.etree.ElementTree as ET
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    racine = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t"))
            for si in racine.iter(f"{{{NS_MAIN}}}si")]


def _texte_cellule(attrs, contenu, partagees):
    if not contenu:
        return ""
    if 't="s"' in attrs:
        m = re.search(r"<v>(\d+)</v>", contenu)
        return partagees[int(m.group(1))] if m else ""
    m = re.search(r"<t[^>]*>(.*?)</t>", contenu, re.S) or re.search(r"<v>(.*?)</v>", contenu, re.S)
    return m.group(1) if m else ""


def ligne_semaine(xml_feuille, colonne, numero_semaine, partagees):
    """Numéro de ligne dont la cellule de `colonne` vaut "S <numero_semaine>"
    (première occurrence : le bloc du haut, pas le récap CA MAGASIN)."""
    cible = f"S{numero_semaine}"
    for m in _RE_CELLULE.finditer(xml_feuille):
        col, ligne, attrs, contenu = m.groups()
        if col != colonne:
            continue
        if _texte_cellule(attrs, contenu, partagees).replace(" ", "").upper() == cible:
            return int(ligne)
    return None


def ecrire_nombre(xml_feuille, ref, valeur):
    """Écrit un nombre dans la cellule `ref` en gardant son style."""
    col = re.match(r"[A-Z]+", ref).group(0)
    ligne = int(ref[len(col):])
    nouvelle = lambda style: f'<c r="{ref}"{style}><v>{valeur}</v></c>'

    m = re.search(rf'<c\s+r="{ref}"([^>]*?)(?:/>|>.*?</c>)', xml_feuille, re.S)
    if m:
        style = re.search(r'\ss="\d+"', m.group(1))
        return xml_feuille[:m.start()] + nouvelle(style.group(0) if style else "") + xml_feuille[m.end():]

    # Cellule absente : l'insérer à sa place (ordre des colonnes) dans la ligne.
    m_ligne = re.search(rf'<row\s+r="{ligne}"[^>]*?(?:/>|>(.*?)</row>)', xml_feuille, re.S)
    if not m_ligne:
        raise ValueError(f"ligne {ligne} absente de la feuille")
    if m_ligne.group(0).endswith("/>"):
        ouverture = m_ligne.group(0)[:-2] + ">"
        remplacement = ouverture + nouvelle("") + "</row>"
        return xml_feuille[:m_ligne.start()] + remplacement + xml_feuille[m_ligne.end():]
    debut_contenu = m_ligne.start(1)
    pos = m_ligne.end(1)
    for mc in _RE_CELLULE.finditer(m_ligne.group(1)):
        if _col_index(mc.group(1)) > _col_index(col):
            pos = debut_contenu + mc.start()
            break
    return xml_feuille[:pos] + nouvelle("") + xml_feuille[pos:]


def renseigner_xlsx(contenu_xlsx, jour, nb_commandes, nb_produits):
    """Retourne le .xlsx modifié (bytes) avec les deux valeurs du jour."""
    semaine = jour.isocalendar()[1]
    idx = jour.weekday()
    with zipfile.ZipFile(io.BytesIO(contenu_xlsx)) as zf:
        chemin = _chemin_feuille(zf, ONGLET_REALISATION)
        partagees = _chaines_partagees(zf)
        xml = zf.read(chemin).decode("utf-8")

        l_cdes = ligne_semaine(xml, COLONNE_SEMAINE_COMMANDES, semaine, partagees)
        l_prod = ligne_semaine(xml, COLONNE_SEMAINE_PRODUITS, semaine, partagees)
        if not l_cdes or not l_prod:
            raise ValueError(f"ligne de la semaine S {semaine} introuvable "
                             f"dans l'onglet {ONGLET_REALISATION}")
        ref_cdes = f"{COLONNES_COMMANDES[idx]}{l_cdes}"
        ref_prod = f"{COLONNES_PRODUITS[idx]}{l_prod}"
        xml = ecrire_nombre(xml, ref_cdes, nb_commandes)
        xml = ecrire_nombre(xml, ref_prod, nb_produits)
        print(f"  {ONGLET_REALISATION}!{ref_cdes} = {nb_commandes} commandes, "
              f"{ONGLET_REALISATION}!{ref_prod} = {nb_produits} produits")

        # Les totaux/ratios en formule gardent leur ancienne valeur en cache :
        # demander un recalcul complet à l'ouverture.
        wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
        if "fullCalcOnLoad" not in wb_xml:
            if "<calcPr" in wb_xml:
                wb_xml = wb_xml.replace("<calcPr", '<calcPr fullCalcOnLoad="1"', 1)
            else:
                wb_xml = wb_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>', 1)

        sortie = io.BytesIO()
        with zipfile.ZipFile(sortie, "w") as out:
            for info in zf.infolist():
                if info.filename == chemin:
                    donnees = xml.encode("utf-8")
                elif info.filename == "xl/workbook.xml":
                    donnees = wb_xml.encode("utf-8")
                else:
                    donnees = zf.read(info.filename)
                out.writestr(info, donnees, compress_type=info.compress_type)
    return sortie.getvalue()


# ─────────────────────────────────────────────────────────────────
# Drive
# ─────────────────────────────────────────────────────────────────

def _id_classeur_ca(drive_svc):
    from googleapiclient.http import MediaIoBaseDownload
    try:
        res = drive_svc.files().list(
            q=f"name='config.json' and '{cs.DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=res["files"][0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        cfg = json.loads(buf.getvalue().decode())
        return cfg.get("ca_drive_spreadsheet_id", "").strip() or CA_SPREADSHEET_ID_DEFAUT
    except Exception:
        return CA_SPREADSHEET_ID_DEFAUT


def _telecharger(drive_svc, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def _envoyer(drive_svc, file_id, contenu):
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(io.BytesIO(contenu), mimetype=MIME_XLSX, resumable=False)
    drive_svc.files().update(fileId=file_id, media_body=media).execute()


# ─────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    jour = datetime.now(cs._TZ).date()
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                jour = date(int(a), int(m), int(j))
            except Exception:
                print(f"Format de date invalide : {args[i + 1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)

    if jour.weekday() == 6:
        print(f"{jour.strftime('%d/%m/%Y')} est un dimanche : pas de colonne dans "
              f"{ONGLET_REALISATION}, rien à renseigner.")
        return

    cs._charger_config()
    print(f"\nRenseigne CA du {jour.strftime('%d/%m/%Y')} "
          f"(semaine {jour.isocalendar()[1]}) …")

    resultat = compter_commandes_produits(jour)
    if resultat is None:
        print("Aucun BonDeCommande trouvé pour ce jour — classeur non modifié.")
        sys.exit(1)
    nb_commandes, nb_produits, illisibles = resultat
    print(f"  {nb_commandes} commande(s), {nb_produits} produit(s)")
    if illisibles:
        print(f"ERREUR : nombre de produits introuvable dans {len(illisibles)} bon(s) : "
              f"{', '.join(illisibles)} — classeur non modifié.")
        sys.exit(1)

    drive_svc = cs._get_drive_service()
    if not drive_svc:
        print("ERREUR : Drive inaccessible.")
        sys.exit(1)
    file_id = _id_classeur_ca(drive_svc)
    try:
        contenu = renseigner_xlsx(_telecharger(drive_svc, file_id), jour, nb_commandes, nb_produits)
        _envoyer(drive_svc, file_id, contenu)
    except Exception as e:
        print(f"ERREUR mise à jour du classeur CA DRIVE : {e}")
        sys.exit(1)
    print("Classeur CA DRIVE mis à jour.")


if __name__ == "__main__":
    main()
