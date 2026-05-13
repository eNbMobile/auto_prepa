#!/usr/bin/env python3
"""
controle_stocks.py — Comparaison stock théorique vs stock réel

Usage :
  python controle_stocks.py <stock_j1.csv> <stock_j.csv> [--date JJ/MM/AAAA] [--upload]

Arguments :
  stock_j1.csv   Export stock J-1 (multi-colonnes, colonnes "Gencod" et "Stock UC" requises)
  stock_j.csv    Export stock J   (même format)

Options :
  --date JJ/MM/AAAA  Date de J-1 pour trouver les BDC (défaut : hier)
  --upload           Upload le CSV résultat vers Google Drive

Calcul :
  stock_théo = stock_j1 - ventes_j1   (ventes extraites des BonDeCommande du jour J-1)
  écart      = stock_j - stock_théo
"""

import sys
import os
import csv
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

_BASE    = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.environ.get("WORK_DIR", os.path.join(_BASE, "v 4.0.0"))
BDC_DIR  = os.environ.get("BDC_DIR",  os.path.join(_BASE, "BDC"))

TEMP_FILES = [
    "bon_prepa.txt", "bon_anticipation.txt", "bon_prepa_NEW.txt", "bon_prepa_dlc.txt",
    "bon_encaissement.pdf", "bon_encaissement.csv", "bon_encaissement_NEW.csv",
    "base_client.txt", "tri_cde.txt", "tri_heures.txt",
    "tmp", "tmp2", "tmp_NEW", "temp", "gentemp.txt", "temp_lib.txt",
]
# Fichiers de sortie du C++ en mode mono (un PDF à la fois)
# Tuple (nom, idx_libelle, idx_qty)
_SORTIE_CANDIDATS = [
    ("bon_encaissement.csv", 1, 4),  # gencod;libellé;prix;remise;qty
    ("bon_prepa.txt",        1, 4),  # gencod;libellé;prix;remise;qty (toujours généré)
]

DRIVE_CONTROLE_FOLDER_ID  = "1GVu_mv2IiMRB3LabFA-6jf2I-9RMSjpa"
DRIVE_BDC_FOLDER_ID       = "10gxP-IbO_-F03QiS75B027HLgKXI0mPs"
DRIVE_CONFIG_FOLDER_ID   = "1rWyZiKe89c7c67eemD33gN4eSLal_FeV"
_CONFIG_FILES            = ["gencod_adresses.csv", "libelles_dict.csv"]

TOKEN_FILE         = os.path.expanduser("~/.auto_prepa_token.json")
SCOPES             = ["https://www.googleapis.com/auth/drive"]
EMAIL_DESTINATAIRE = "superu.arnage.drive@systeme-u.fr"


# ─────────────────────────────────────────────────────────────────
# Lecture fichier stock multi-colonnes
# ─────────────────────────────────────────────────────────────────

def _col_index(ref):
    """Convertit une référence Excel type 'AB' en index 0-based."""
    idx = 0
    for ch in ref:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1


def _rows_depuis_xlsx(chemin):
    """
    Lit un .xlsx via zipfile + xml.etree (aucune dépendance externe).
    Itère les lignes de la première feuille sous forme de listes de strings.
    """
    NS  = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    RNS = 'http://schemas.openxmlformats.org/package/2006/relationships'
    ONS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

    with zipfile.ZipFile(chemin) as zf:
        names = zf.namelist()

        # Chaînes partagées
        shared = []
        if 'xl/sharedStrings.xml' in names:
            with zf.open('xl/sharedStrings.xml') as f:
                for si in ET.parse(f).findall(f'.//{{{NS}}}si'):
                    shared.append(''.join(e.text or '' for e in si.iter(f'{{{NS}}}t')))

        # Première feuille via relations
        sheet_path = 'xl/worksheets/sheet1.xml'
        if 'xl/workbook.xml' in names and 'xl/_rels/workbook.xml.rels' in names:
            with zf.open('xl/workbook.xml') as f:
                wb_tree = ET.parse(f)
            first_sheet = wb_tree.find(f'.//{{{NS}}}sheet')
            if first_sheet is not None:
                rid = first_sheet.get(f'{{{ONS}}}id')
                with zf.open('xl/_rels/workbook.xml.rels') as f:
                    for rel in ET.parse(f).findall(f'{{{RNS}}}Relationship'):
                        if rel.get('Id') == rid:
                            target = rel.get('Target', '').lstrip('/')
                            sheet_path = target if target.startswith('xl/') else f'xl/{target}'
                            break

        with zf.open(sheet_path) as f:
            ws_tree = ET.parse(f)

        for row_el in ws_tree.findall(f'.//{{{NS}}}row'):
            row = []
            for c in row_el.findall(f'{{{NS}}}c'):
                ref = ''.join(ch for ch in c.get('r', '') if ch.isalpha())
                col = _col_index(ref) if ref else len(row)
                while len(row) < col:
                    row.append('')
                t    = c.get('t', '')
                v_el = c.find(f'{{{NS}}}v')
                val  = ''
                if v_el is not None and v_el.text:
                    if t == 's':
                        idx = int(v_el.text)
                        val = shared[idx] if idx < len(shared) else ''
                    elif t == 'inlineStr':
                        ie = c.find(f'.//{{{NS}}}t')
                        val = ie.text if ie is not None else ''
                    else:
                        val = v_el.text
                row.append(str(val).strip())
            yield row


def _rows_depuis_csv(chemin):
    """Itère les lignes d'un fichier CSV (détection auto du séparateur)."""
    with open(chemin, newline='', encoding='utf-8-sig') as f:
        sample = f.read(2048)
    sep = ';' if sample.count(';') >= sample.count(',') else ','
    with open(chemin, newline='', encoding='utf-8-sig') as f:
        yield from csv.reader(f, delimiter=sep)


def lire_stock(chemin):
    """
    Lit un export stock multi-colonnes (.xlsx ou .csv).
    Cherche les colonnes "Gencod", "Stock UC" et optionnellement "Libellé".
    Retourne ({gencod: stock_uc}, {gencod: libelle}).
    """
    ext = os.path.splitext(chemin)[1].lower()
    rows = _rows_depuis_xlsx(chemin) if ext in ('.xlsx', '.xls') else _rows_depuis_csv(chemin)

    data     = {}
    libelles = {}
    idx_gencod = idx_stock = idx_libelle = None

    for row in rows:
        if idx_gencod is None:
            row_norm = [c.strip().lower() for c in row]
            if 'gencod' in row_norm:
                idx_gencod = row_norm.index('gencod')
                for i, h in enumerate(row_norm):
                    if re.match(r'stock\s*uc', h):
                        idx_stock = i
                    if re.match(r'lib', h):
                        idx_libelle = i
                if idx_stock is None:
                    raise ValueError(
                        f"Colonne 'Stock UC' introuvable dans {chemin}.\n"
                        f"En-têtes trouvées : {[c.strip() for c in row]}")
            continue

        max_idx = max(idx_gencod, idx_stock)
        if len(row) <= max_idx:
            continue
        gencod = row[idx_gencod].strip().lstrip('0').zfill(13) if row[idx_gencod].strip().isdigit() else row[idx_gencod].strip()
        if not re.match(r'^\d{5,}$', gencod):
            continue
        val_str = row[idx_stock].strip().replace(',', '.').replace(' ', '')
        if not val_str:
            data[gencod] = 0.0
        else:
            try:
                data[gencod] = float(val_str)
            except ValueError:
                pass
        if idx_libelle is not None and len(row) > idx_libelle:
            lib = row[idx_libelle].strip()
            if lib:
                libelles[gencod] = lib

    if idx_gencod is None:
        raise ValueError(f"Colonne 'Gencod' introuvable dans {chemin}.")
    return data, libelles


# ─────────────────────────────────────────────────────────────────
# Dictionnaire libellés coursesu.com (build_libelles.py)
# ─────────────────────────────────────────────────────────────────

def charger_libelles_dict():
    """Charge libelles_dict.csv si disponible. Retourne {gencod: libelle}."""
    chemin = os.path.join(WORK_DIR, "libelles_dict.csv")
    if not os.path.exists(chemin):
        return {}
    d = {}
    with open(chemin, newline='', encoding='utf-8-sig') as f:
        for row in csv.reader(f, delimiter=';'):
            if len(row) >= 2 and row[1].strip():
                d[row[0].strip()] = row[1].strip()
    print(f"  {len(d)} libellés chargés depuis libelles_dict.csv")
    return d


# ─────────────────────────────────────────────────────────────────
# Génération des ventes depuis les BonDeCommande de J-1
# ─────────────────────────────────────────────────────────────────

def charger_gencods_r1():
    """
    Lit gencod_adresses.csv (format gencod;adresse) et retourne l'ensemble
    des gencods dont l'adresse commence par 'R1'.
    """
    chemin = os.path.join(WORK_DIR, "gencod_adresses.csv")
    if not os.path.exists(chemin):
        print(f"  AVERTISSEMENT : {chemin} introuvable — aucun filtre R1 appliqué.")
        return None  # None = pas de filtre
    gencods = set()
    with open(chemin, newline='', encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(';', 1)
            if len(parts) < 2:
                continue
            gencod, adresse = parts[0].strip(), parts[1].strip()
            if gencod.isdigit():
                gencod = gencod.lstrip('0').zfill(13)
            if adresse.startswith('R1'):
                gencods.add(gencod)
    print(f"  {len(gencods)} gencods R1 chargés depuis gencod_adresses.csv")
    return gencods


# Quantité en début de ligne + libellé (première ligne du bloc produit)
_RE_QTY    = re.compile(r'^\s{0,8}(\d{1,3})\s{10,}(.+)')
# Gencod EAN (≥5 chiffres) sur ligne fortement indentée
_RE_GENCOD = re.compile(r'^\s{8,}(\d{13})(?!\d)')


def extraire_ventes_pdf(texte, gencods_r1):
    """Parse le texte pdftotext d'un bon d'encaissement. Retourne ({gencod: qty}, {gencod: libelle})."""
    ventes   = {}
    libelles = {}
    pending_qty   = None
    pending_label = None
    for line in texte.splitlines():
        m_g = _RE_GENCOD.match(line)
        if m_g:
            gencod = m_g.group(1)
            if gencods_r1 is None or gencod in gencods_r1:
                ventes[gencod] = ventes.get(gencod, 0) + (pending_qty or 1)
                if pending_label and gencod not in libelles:
                    libelles[gencod] = pending_label
            pending_qty = pending_label = None
            continue
        m_q = _RE_QTY.match(line)
        if m_q:
            pending_qty   = int(m_q.group(1))
            label = m_q.group(2).strip()
            idx = label.lower().find('dont tva')
            pending_label = label[:idx].strip() if idx != -1 else label
    return ventes, libelles


def _charger_ventes_csv(chemin):
    """Charge un ventes_JJ_MM.csv pré-calculé. Retourne ({gencod: qty}, {gencod: libelle})."""
    ventes = {}
    libelles = {}
    with open(chemin, newline='', encoding='utf-8-sig') as f:
        for row in csv.reader(f, delimiter=';'):
            if len(row) >= 2 and row[0] not in ('gencod', ''):
                try:
                    ventes[row[0]] = int(float(row[1]))
                    if len(row) >= 3 and row[2].strip():
                        libelles[row[0]] = row[2].strip()
                except ValueError:
                    pass
    print(f"  → {len(ventes)} gencods, {sum(ventes.values())} produits total")
    return ventes, libelles


def _charger_theo_csv(chemin):
    """Charge un theo_JJ_MM.csv pré-calculé. Retourne ({gencod: (s_j1, v, s_theo)}, {gencod: libelle})."""
    theo = {}
    libelles = {}
    with open(chemin, newline='', encoding='utf-8-sig') as f:
        for row in csv.reader(f, delimiter=';'):
            if len(row) >= 5 and row[0] not in ('gencod', ''):
                try:
                    g = row[0]
                    lib = row[1].strip()
                    s_j1   = float(row[2])
                    v      = float(row[3])
                    s_theo = float(row[4])
                    theo[g] = (s_j1, v, s_theo)
                    if lib:
                        libelles[g] = lib
                except (ValueError, IndexError):
                    pass
    print(f"  → {len(theo)} gencods théoriques chargés")
    return theo, libelles


def generer_ventes(date_j1):
    """
    Extrait les ventes du jour date_j1 via pdftotext sur les BonDeCommande.
    Si ventes_JJ_MM.csv existe déjà dans WORK_DIR, le charge directement.
    Retourne ({gencod: qty}, {gencod: libelle}).
    """
    dossier    = date_j1.strftime("%d_%m")

    # Charger les ventes pré-calculées si disponibles (générées par generer_ventes.py)
    chemin_precompute = os.path.join(WORK_DIR, f"ventes_{dossier}.csv")
    if os.path.exists(chemin_precompute):
        print(f"  Ventes pré-calculées : {chemin_precompute}")
        return _charger_ventes_csv(chemin_precompute)

    bdc_subdir = os.path.join(BDC_DIR, dossier)

    synced = telecharger_bdc_depuis_drive(dossier)
    if synced:
        bdc_subdir = synced

    if not os.path.isdir(bdc_subdir):
        print("  Impossible de récupérer les BDC — ventes = 0 pour tous.")
        return {}, {}

    pdfs = sorted(f for f in os.listdir(bdc_subdir)
                  if f.startswith("BonDeCommande_") and f.endswith(".pdf"))
    if not pdfs:
        print(f"  Aucun BonDeCommande trouvé dans {bdc_subdir}.")
        return {}, {}

    print(f"  {len(pdfs)} BonDeCommande(s) …")
    gencods_r1 = charger_gencods_r1()

    ventes_totales   = {}
    libelles_totales = {}

    for pdf in pdfs:
        pdf_path = os.path.join(bdc_subdir, pdf)
        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            continue
        v, l = extraire_ventes_pdf(pt.stdout, gencods_r1)
        for gencod, qty in v.items():
            ventes_totales[gencod] = ventes_totales.get(gencod, 0) + qty
            if gencod not in libelles_totales and gencod in l:
                libelles_totales[gencod] = l[gencod]

    print(f"  → {len(ventes_totales)} gencods vendus, {sum(ventes_totales.values())} produits total")
    return ventes_totales, libelles_totales


# ─────────────────────────────────────────────────────────────────
# Téléchargement BDC depuis Drive (fallback)
# ─────────────────────────────────────────────────────────────────

def _get_drive_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        if not os.path.exists(TOKEN_FILE):
            return None
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(f"  Drive inaccessible : {e}")
        return None


def _get_gmail_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        if not os.path.exists(TOKEN_FILE):
            return None
        creds = Credentials.from_authorized_user_file(
            TOKEN_FILE, ["https://www.googleapis.com/auth/gmail.modify"])
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        print(f"  Gmail inaccessible : {e}")
        return None


def telecharger_bdc_depuis_drive(dossier_jj_mm):
    """Télécharge les PDFs BDC depuis Drive pour un sous-dossier JJ_MM."""
    if not DRIVE_BDC_FOLDER_ID:
        return None
    svc = _get_drive_service()
    if not svc:
        return None
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload

        # Trouver le sous-dossier JJ_MM dans Drive
        res = svc.files().list(
            q=(f"name='{dossier_jj_mm}' and '{DRIVE_BDC_FOLDER_ID}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        folders = res.get("files", [])
        if not folders:
            print(f"  Sous-dossier {dossier_jj_mm} introuvable dans Drive BDC.")
            return None
        subfolder_id = folders[0]["id"]

        # Lister les PDFs (pagination pour dépasser la limite de 100)
        files = []
        page_token = None
        while True:
            params = {
                'q': f"'{subfolder_id}' in parents and name contains 'BonDeCommande' and trashed=false",
                'fields': 'nextPageToken, files(id,name)',
                'pageSize': 1000,
            }
            if page_token:
                params['pageToken'] = page_token
            res = svc.files().list(**params).execute()
            files.extend(res.get('files', []))
            page_token = res.get('nextPageToken')
            if not page_token:
                break
        if not files:
            return None

        local_dir = os.path.join(BDC_DIR, dossier_jj_mm)
        os.makedirs(local_dir, exist_ok=True)

        print(f"  Téléchargement {len(files)} PDF(s) depuis Drive BDC/{dossier_jj_mm}/ …")
        for f in files:
            dest = os.path.join(local_dir, f["name"])
            if os.path.exists(dest):
                continue
            req = svc.files().get_media(fileId=f["id"])
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            with open(dest, "wb") as out:
                out.write(buf.getvalue())
        return local_dir
    except Exception as e:
        print(f"  Erreur téléchargement Drive BDC : {e}")
        return None


def telecharger_fichier_controle(nom, dest=None):
    """Télécharge le fichier 'nom' depuis DRIVE_CONTROLE_FOLDER_ID. Retourne le chemin local ou None."""
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload
        svc = _get_drive_service()
        if not svc:
            return None
        res = svc.files().list(
            q=f"name='{nom}' and '{DRIVE_CONTROLE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            print(f"  {nom} introuvable dans Drive contrôle.")
            return None
        req = svc.files().get_media(fileId=files[0]["id"])
        buf = io.BytesIO()
        dl  = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        chemin = dest or nom
        with open(chemin, "wb") as f:
            f.write(buf.getvalue())
        print(f"  → {chemin} téléchargé ({os.path.getsize(chemin):,} octets)")
        return chemin
    except Exception as e:
        print(f"  telecharger_fichier_controle({nom}) échoué : {e}")
        return None


def telecharger_config_depuis_drive():
    """Télécharge gencod_adresses.csv et libelles_dict.csv depuis MobUDrive_config si absents."""
    if all(os.path.exists(os.path.join(WORK_DIR, f)) for f in _CONFIG_FILES):
        return  # déjà présents (exécution locale)
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload
        svc = _get_drive_service()
        if not svc:
            return
        res = svc.files().list(
            q=f"'{DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
            fields="files(id,name)",
        ).execute()
        index = {f["name"]: f["id"] for f in res.get("files", [])}
        os.makedirs(WORK_DIR, exist_ok=True)
        for nom in _CONFIG_FILES:
            dest = os.path.join(WORK_DIR, nom)
            if os.path.exists(dest):
                continue
            if nom not in index:
                print(f"  {nom} absent de MobUDrive_config.")
                continue
            req = svc.files().get_media(fileId=index[nom])
            buf = io.BytesIO()
            dl  = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            with open(dest, "wb") as f:
                f.write(buf.getvalue())
            print(f"  Config : {nom} ({os.path.getsize(dest):,} octets)")
    except Exception as e:
        print(f"  telecharger_config_depuis_drive() échoué : {e}")


# ─────────────────────────────────────────────────────────────────
# Upload Drive (optionnel)
# ─────────────────────────────────────────────────────────────────

def upload_drive(local_path):
    if not DRIVE_CONTROLE_FOLDER_ID:
        print("  DRIVE_CONTROLE_FOLDER_ID non configuré — upload ignoré.")
        return False
    try:
        from googleapiclient.http import MediaFileUpload
        svc = _get_drive_service()
        if not svc:
            return False
        filename = os.path.basename(local_path)
        res = svc.files().list(
            q=f"name='{filename}' and '{DRIVE_CONTROLE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        media = MediaFileUpload(local_path, mimetype="text/plain", resumable=False)
        if existing:
            svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
        else:
            svc.files().create(
                body={"name": filename, "parents": [DRIVE_CONTROLE_FOLDER_ID]},
                media_body=media, fields="id",
            ).execute()
        print(f"  {filename} → Drive OK")
        return True
    except Exception as e:
        print(f"  Upload Drive échoué : {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# PDF des écarts + envoi email
# ─────────────────────────────────────────────────────────────────

def generer_pdf_ecarts(compares, date_j1):
    """Génère un PDF des lignes ECART (trié |écart| desc). Retourne le chemin ou None."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                        Paragraph, Spacer)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.graphics.barcode import createBarcodeDrawing
    except Exception as e:
        print(f"  PDF ignoré : {e}")
        return None

    def make_barcode(code):
        try:
            return createBarcodeDrawing('EAN13', value=code,
                                        width=100, height=30,
                                        humanReadable=False)
        except Exception:
            return None

    ecarts = [r for r in compares if r[6] == "ECART"]
    if not ecarts:
        return None

    nom_pdf = f"ecarts_{date_j1.strftime('%Y%m%d')}.pdf"
    doc = SimpleDocTemplate(nom_pdf, pagesize=A4,
                            topMargin=8*mm, bottomMargin=8*mm,
                            leftMargin=3*mm, rightMargin=3*mm)

    styles  = getSampleStyleSheet()
    small   = ParagraphStyle('small', fontSize=8, leading=10)
    header_s = ParagraphStyle('hdr', fontSize=8, leading=10, textColor=colors.white)

    elements = []
    elements.append(Paragraph(
        f"<b>Contrôle de stocks — {date_j1.strftime('%d/%m/%Y')}</b>"
        f"&nbsp;&nbsp;({len(ecarts)} écarts)", styles['Title']))
    elements.append(Spacer(1, 5*mm))

    col_widths = [108, 246, 33, 40, 33, 33, 34]  # ≈ 527 pt (marges 3mm, sans colonne gencod)
    hdr = [Paragraph(t, header_s) for t in
           ['Code-barres', 'Libellé', 'J-1', 'Ventes', 'Théo', 'J', 'Écart']]
    data = [hdr]

    tiny_c = ParagraphStyle('tiny_c', fontSize=7, leading=8, alignment=1)

    for r in ecarts:
        gencod, s_j1, v, s_theo, s_j, ecart, _, lib = r
        bc = make_barcode(gencod) if len(gencod) == 13 else None
        if bc:
            bc_cell = Table(
                [[bc], [Paragraph(gencod, tiny_c)]],
                colWidths=[108],
                style=TableStyle([
                    ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                    ('TOPPADDING',    (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                ]),
            )
        else:
            bc_cell = Paragraph(gencod, small)
        data.append([
            bc_cell,
            Paragraph(lib, small),
            Paragraph(str(int(s_j1)), small),
            Paragraph(str(int(v)),    small),
            Paragraph(str(int(s_theo)), small),
            Paragraph(str(int(s_j)),  small),
            Paragraph(f"{int(ecart):+d}", small),
        ])

    BLEU = colors.HexColor('#006797')
    style = TableStyle([
        ('BACKGROUND',     (0, 0), (-1, 0), BLEU),
        ('FONTNAME',       (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0), (-1, 0), 8),
        ('ALIGN',          (0, 0), (-1, 0), 'CENTER'),
        ('FONTSIZE',       (0, 1), (-1, -1), 8),
        ('ALIGN',          (2, 1), (-1, -1), 'CENTER'),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF6FB')]),
        ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING',     (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 12),
    ])
    for i, r in enumerate(ecarts, 1):
        c = colors.HexColor('#D32F2F') if float(r[5]) < 0 else colors.HexColor('#E65100')
        style.add('TEXTCOLOR', (6, i), (6, i), c)
        style.add('FONTNAME',  (6, i), (6, i), 'Helvetica-Bold')

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(style)
    elements.append(table)
    doc.build(elements)
    print(f"  → {nom_pdf} ({len(ecarts)} écarts)")
    return nom_pdf


def envoyer_email_pdf(pdf_path, date_j1, nb_ecart, manquant, surplus):
    """Envoie le PDF par email via Gmail API."""
    try:
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication

        svc = _get_gmail_service()
        if not svc:
            return

        msg = MIMEMultipart()
        msg['To']      = EMAIL_DESTINATAIRE
        msg['Subject'] = (f"Contrôle stocks {date_j1.strftime('%d/%m/%Y')} "
                          f"— {nb_ecart} écart{'s' if nb_ecart > 1 else ''}")
        corps = (f"Contrôle de stocks du {date_j1.strftime('%d/%m/%Y')}\n\n"
                 f"  Écarts   : {nb_ecart}\n"
                 f"  Manquant : {manquant:.0f} unités\n"
                 f"  Surplus  : +{surplus:.0f} unités\n\n"
                 f"Détail en pièce jointe.")
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))

        with open(pdf_path, 'rb') as f:
            part = MIMEApplication(f.read(), 'pdf')
            part.add_header('Content-Disposition', 'attachment',
                            filename=os.path.basename(pdf_path))
            msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email envoyé → {EMAIL_DESTINATAIRE}")
    except Exception as e:
        print(f"  Email échoué : {e}")


# ─────────────────────────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    args = [a for a in args if a != "--upload"]  # flag ignoré, upload toujours actif

    # --date JJ/MM/AAAA
    date_j1 = date.today() - timedelta(days=1)
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                date_j1 = date(int(a), int(m), int(j))
            except Exception:
                print(f"Format de date invalide : {args[i+1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)
            args.pop(i + 1)
            args.pop(i)

    if len(args) != 2:
        print(__doc__)
        sys.exit(1)

    fichier_j1, fichier_j = args

    # 1. Lire les stocks
    print(f"Lecture stock J-1 : {fichier_j1}")
    stock_j1, libelles_stock = lire_stock(fichier_j1)
    print(f"  → {len(stock_j1)} gencods, {len(libelles_stock)} libellés xlsx")

    print(f"Lecture stock J   : {fichier_j}")
    stock_j, libelles_stock_j = lire_stock(fichier_j)
    print(f"  → {len(stock_j)} gencods")
    for g, l in libelles_stock_j.items():
        if g not in libelles_stock:
            libelles_stock[g] = l

    # Télécharger la config depuis Drive si absente (GH Actions)
    telecharger_config_depuis_drive()

    # Charger le dictionnaire complet coursesu.com (priorité sur xlsx tronqué)
    print("\nChargement libellés coursesu ...")
    libelles_dict = charger_libelles_dict()

    # 2. Théorique pré-calculé (generer_ventes.py) ou recalcul depuis BDC
    dossier = date_j1.strftime("%d_%m")
    chemin_theo = os.path.join(WORK_DIR, f"theo_{dossier}.csv")
    if os.path.exists(chemin_theo):
        print(f"\nThéorique pré-calculé : {chemin_theo}")
        theo_data, libelles_theo = _charger_theo_csv(chemin_theo)
        libelles_extra = libelles_theo
    else:
        print(f"\nGénération ventes depuis BDC du {date_j1.strftime('%d/%m/%Y')} …")
        ventes, libelles_extra = generer_ventes(date_j1)
        theo_data = None

    # 3. Comparaison — uniquement les 1087 gencods R1
    gencods_r1 = charger_gencods_r1()
    tous = gencods_r1 if gencods_r1 is not None else (set(stock_j1) | set(stock_j))

    compares  = []
    orphelins = []

    for gencod in sorted(tous):
        if theo_data is not None:
            present_j1 = gencod in theo_data
            s_j1, v, s_theo = theo_data[gencod] if present_j1 else (0.0, 0.0, 0.0)
        else:
            present_j1 = gencod in stock_j1
            s_j1   = stock_j1.get(gencod, 0.0)
            v      = ventes.get(gencod, 0.0)
            s_theo = s_j1 - v
        present_j  = gencod in stock_j

        s_j   = stock_j.get(gencod, 0.0)
        ecart = s_j - s_theo
        # Priorité : dict coursesu > xlsx > théo/pdftotext
        lib = (libelles_dict.get(gencod)
               or libelles_stock.get(gencod)
               or libelles_extra.get(gencod, ''))

        absents = []
        if not present_j1: absents.append("J-1")
        if not present_j:  absents.append("J")

        if absents:
            statut = f"ABSENT_{'+'.join(absents)}"
        elif s_j1 == 0 and s_j == 0:
            statut = "OK"
        else:
            statut = "OK" if abs(ecart) < 0.001 else "ECART"
        # tuple : gencod, s_j1, v, s_theo, s_j, ecart, statut, libelle
        row = (gencod, s_j1, v, s_theo, s_j, ecart, statut, lib)
        (orphelins if absents else compares).append(row)

    compares.sort(key=lambda r: abs(r[5]), reverse=True)
    orphelins.sort(key=lambda r: r[0])

    # 4. Écriture CSV
    nom_sortie = f"controle_stocks_{date_j1.strftime('%Y%m%d')}.csv"
    ENTETE = ["gencod", "libelle", "stock_j1", "ventes", "stock_theo", "stock_j", "ecart", "statut"]

    def fmt(v):
        return f"{int(v)}" if v == int(v) else f"{v:.3f}"

    def row_csv(r):
        return [r[0], r[7], fmt(r[1]), fmt(r[2]), fmt(r[3]), fmt(r[4]), fmt(r[5]), r[6]]

    with open(nom_sortie, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(ENTETE)
        for r in compares:
            w.writerow(row_csv(r))
        if orphelins:
            w.writerow([])
            w.writerow(["# GENCODS ORPHELINS (absents de J-1 ou J)"])
            w.writerow(ENTETE)
            for r in orphelins:
                w.writerow(row_csv(r))

    # 5. Résumé
    nb_ok     = sum(1 for r in compares if r[6] == "OK")
    nb_ecart  = sum(1 for r in compares if r[6] == "ECART")
    manquant  = sum(r[5] for r in compares if r[5] < 0)
    surplus   = sum(r[5] for r in compares if r[5] > 0)

    print(f"\n── Résultats ──────────────────────────────────────")
    print(f"  Gencods appairés  : {len(compares)}")
    print(f"    Sans écart (OK) : {nb_ok}")
    print(f"    Avec écart      : {nb_ecart}")
    if orphelins:
        print(f"  Gencods orphelins : {len(orphelins)}")
    print(f"  Total manquant    : {manquant:.0f} unités")
    print(f"  Total surplus     : {+surplus:.0f} unités")

    if nb_ecart > 0:
        print(f"\n  Top 10 écarts (|écart| décroissant) :")
        for r in compares[:10]:
            if abs(r[5]) < 0.001:
                break
            sens = "surplus" if r[5] > 0 else "manquant"
            print(f"    {r[0]}  théo={r[3]:.0f}  réel={r[4]:.0f}  écart={r[5]:+.0f}  ({sens})")

    print(f"\n→ {nom_sortie} généré.")

    print("\nUpload Drive …")
    upload_drive(nom_sortie)

    if nb_ecart > 0:
        print("\nGénération PDF écarts …")
        nom_pdf = generer_pdf_ecarts(compares, date_j1)
        if nom_pdf:
            print("\nEnvoi email …")
            envoyer_email_pdf(nom_pdf, date_j1, nb_ecart, manquant, surplus)


if __name__ == "__main__":
    main()
