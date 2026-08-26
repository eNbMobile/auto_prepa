#!/usr/bin/env python3

import sys
import os
import csv
import io
import json
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

_BASE    = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.environ.get("WORK_DIR", os.path.join(_BASE, "v 4.0.0"))
BDC_DIR  = os.environ.get("BDC_DIR",  os.path.join(_BASE, "BDC"))

TEMP_FILES = [
    "bon_prepa.txt", "bon_anticipation.txt", "bon_prepa_NEW.txt", "bon_prepa_dlc.txt",
    "bon_encaissement.pdf", "bon_encaissement.csv", "bon_encaissement_NEW.csv",
    "base_client.txt", "tri_cde.txt", "tri_heures.txt",
    "tmp", "tmp2", "tmp_NEW", "temp", "gentemp.txt", "temp_lib.txt",
]
_SORTIE_CANDIDATS = [
    ("bon_encaissement.csv", 1, 4),  # gencod;libellé;prix;remise;qty
    ("bon_prepa.txt",        1, 4),  # gencod;libellé;prix;remise;qty (toujours généré)
]

SEUIL_STOCK_BAS = 2  # stock J <= ce seuil → alerte "stock insuffisant Drive"

CLASSEUR_DELOTAGE = "DRIVE DELOTAGE"  # comparé normalisé (majuscules, sans accents)
CLASSEUR_LGV       = "DRIVE LGV"      # idem, pour l'alerte "LGV à commander"


def _normaliser_classeur(texte):
    """Majuscules sans accents ni astérisques, pour comparer un classeur
    insensiblement à la casse/accents (les classeurs sensibles sont notés
    "**DRIVE XXX**" dans l'export)."""
    import unicodedata
    d = unicodedata.normalize('NFD', (texte or '').strip().upper())
    sans_accents = ''.join(c for c in d if unicodedata.category(c) != 'Mn')
    return sans_accents.replace('*', '').strip()

DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")

DRIVE_CONTROLE_FOLDER_ID = ""
DRIVE_BDC_FOLDER_ID      = ""

_config_drive_index = None   # {nom: file_id}
_config_drive_cache = {}     # {nom: contenu texte}

TOKEN_FILE         = os.path.expanduser("~/.auto_prepa_token.json")
SCOPES             = ["https://www.googleapis.com/auth/drive"]
EMAIL_DESTINATAIRE = ""  # chargé depuis config.json
EMAIL_COPIE_STOCK  = ""  # chargé depuis config.json (email_destinataire_2)

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

        shared = []
        if 'xl/sharedStrings.xml' in names:
            with zf.open('xl/sharedStrings.xml') as f:
                for si in ET.parse(f).findall(f'.//{{{NS}}}si'):
                    shared.append(''.join(e.text or '' for e in si.iter(f'{{{NS}}}t')))

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
    Cherche les colonnes "Gencod", "Stock UC" et optionnellement "Libellé"
    et "Classeur" (classement du produit, ex. "DRIVE DÉLOTAGE" — absente des
    exports actuels, ajoutée au besoin par les équipes).
    Retourne ({gencod: stock_uc}, {gencod: libelle}, {gencod: classeur}).
    """
    ext = os.path.splitext(chemin)[1].lower()
    rows = _rows_depuis_xlsx(chemin) if ext in ('.xlsx', '.xls') else _rows_depuis_csv(chemin)

    data      = {}
    libelles  = {}
    classeurs = {}
    idx_gencod = idx_stock = idx_libelle = idx_classeur = None

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
                    if h == 'classeur':
                        idx_classeur = i
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
        if idx_classeur is not None and len(row) > idx_classeur:
            classeur = row[idx_classeur].strip()
            if classeur:
                classeurs[gencod] = classeur

    if idx_gencod is None:
        raise ValueError(f"Colonne 'Gencod' introuvable dans {chemin}.")
    return data, libelles, classeurs

def _lire_config_drive(nom):
    """Retourne le contenu texte d'un fichier config Drive (cache mémoire par session)."""
    global _config_drive_index
    if nom in _config_drive_cache:
        return _config_drive_cache[nom]
    if not DRIVE_CONFIG_FOLDER_ID:
        return None
    try:
        from googleapiclient.http import MediaIoBaseDownload
        svc = _get_drive_service()
        if not svc:
            return None
        if _config_drive_index is None:
            res = svc.files().list(
                q=f"'{DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
                fields="files(id,name)",
            ).execute()
            _config_drive_index = {f["name"]: f["id"] for f in res.get("files", [])}
        if nom not in _config_drive_index:
            print(f"  {nom} absent du dossier config Drive.")
            return None
        req = svc.files().get_media(fileId=_config_drive_index[nom])
        buf = io.BytesIO()
        dl  = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        contenu = buf.getvalue().decode("utf-8-sig")
        _config_drive_cache[nom] = contenu
        return contenu
    except Exception as e:
        print(f"  _lire_config_drive({nom}) échoué : {e}")
        return None

def charger_libelles_dict():
    """Charge libelles_dict.csv depuis Drive (mémoire) ou disque. Retourne {gencod: libelle}."""
    contenu = _lire_config_drive("libelles_dict.csv")
    if contenu is None:
        chemin = os.path.join(WORK_DIR, "libelles_dict.csv")
        if not os.path.exists(chemin):
            return {}
        with open(chemin, encoding='utf-8-sig') as f:
            contenu = f.read()
    d = {}
    for row in csv.reader(io.StringIO(contenu), delimiter=';'):
        if len(row) >= 2 and row[1].strip():
            g = row[0].strip()
            if g.isdigit():
                g = g.lstrip('0').zfill(13)
            d[g] = row[1].strip()
    print(f"  {len(d)} libellés chargés depuis libelles_dict.csv")
    return d

def charger_gencods_r1():
    """
    Lit gencod_adresses.csv depuis Drive (mémoire) ou disque.
    Retourne l'ensemble des gencods dont l'adresse commence par 'R1'.
    """
    contenu = _lire_config_drive("gencod_adresses.csv")
    if contenu is None:
        chemin = os.path.join(WORK_DIR, "gencod_adresses.csv")
        if not os.path.exists(chemin):
            print("  AVERTISSEMENT : gencod_adresses.csv introuvable — aucun filtre R1 appliqué.")
            return None
        with open(chemin, encoding='utf-8-sig', errors='replace') as f:
            contenu = f.read()
    gencods = set()
    for line in contenu.splitlines():
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


_RE_QTY    = re.compile(r'^\s{0,8}(\d{1,3})\s{10,}(.+)')
_RE_GENCOD = re.compile(r'^\s{8,}(\d{8,13})(?!\d)')


def extraire_ventes_pdf(texte, gencods_r1):
    """Parse le texte pdftotext d'un bon d'encaissement. Retourne ({gencod: qty}, {gencod: libelle})."""
    ventes   = {}
    libelles = {}
    pending_qty   = None
    pending_label = None
    for line in texte.splitlines():
        m_g = _RE_GENCOD.match(line)
        if m_g:
            gencod = m_g.group(1).zfill(13)
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

    synced = telecharger_bdc_depuis_drive(date_j1)
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


def calculer_vms(gencods, date_reference, nb_semaines=5):
    """Calcule la Vente Moyenne Semaine (VMS) pour les gencods fournis.

    Cumule les cumuls hebdomadaires (ventes_SXX.csv, générés par
    cumul_ventes_semaine.py et archivés dans Drive MobuDrive_Config_archives
    (DRIVE_CONFIG_FOLDER_ID) / Archives/VMS/) des nb_semaines dernières
    semaines complètes précédant la semaine de date_reference, puis divise
    par nb_semaines. Retourne {gencod: vms}.

    Une semaine dont le fichier n'est pas trouvé (pas encore généré, Drive
    inaccessible, …) est ignorée dans le cumul.
    """
    lundi_courant = date_reference - timedelta(days=date_reference.weekday())

    numeros_semaine = [(lundi_courant - timedelta(weeks=i)).isocalendar()[1]
                       for i in range(1, nb_semaines + 1)]
    print(f"\nCalcul VMS ({nb_semaines} dernières semaines : "
          f"{', '.join(f'S{n:02d}' for n in reversed(numeros_semaine))}) …")

    cumul = {}
    for numero in numeros_semaine:
        nom_csv = f"ventes_S{numero:02d}.csv"
        chemin_local = os.path.join(WORK_DIR, nom_csv)
        if not os.path.exists(chemin_local):
            telecharger_fichier_archive("VMS", nom_csv, chemin_local, root_id=DRIVE_CONFIG_FOLDER_ID)
        if not os.path.exists(chemin_local):
            print(f"  {nom_csv} introuvable — semaine ignorée dans le calcul VMS.")
            continue
        v_semaine, _ = _charger_ventes_csv(chemin_local)
        for gencod, qty in v_semaine.items():
            cumul[gencod] = cumul.get(gencod, 0) + qty

    return {g: cumul.get(g, 0) / nb_semaines for g in gencods}


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


def telecharger_bdc_depuis_drive(date_j1):
    """Télécharge les PDFs BDC depuis Drive : BDC/MM_AAAA/JJ_MM."""
    if not DRIVE_BDC_FOLDER_ID:
        return None
    svc = _get_drive_service()
    if not svc:
        return None
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload

        dossier_mm_aaaa = date_j1.strftime("%m_%Y")  # ex. "06_2026"
        dossier_jj_mm   = date_j1.strftime("%d_%m")  # ex. "09_06"

        # Trouver le sous-dossier MM_AAAA dans Drive BDC
        res = svc.files().list(
            q=(f"name='{dossier_mm_aaaa}' and '{DRIVE_BDC_FOLDER_ID}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        mois_folders = res.get("files", [])
        if not mois_folders:
            print(f"  Sous-dossier {dossier_mm_aaaa} introuvable dans Drive BDC.")
            return None
        mois_id = mois_folders[0]["id"]

        # Trouver le sous-dossier JJ_MM dans MM_AAAA
        res = svc.files().list(
            q=(f"name='{dossier_jj_mm}' and '{mois_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        folders = res.get("files", [])
        if not folders:
            print(f"  Sous-dossier {dossier_jj_mm} introuvable dans Drive BDC/{dossier_mm_aaaa}/.")
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

        print(f"  Téléchargement {len(files)} PDF(s) depuis Drive BDC/{dossier_mm_aaaa}/{dossier_jj_mm}/ …")
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


def telecharger_fichier_archive(subfolder, nom, dest=None, root_id=None):
    """Télécharge 'nom' depuis {root_id}/Archives/{subfolder}/.

    root_id  : dossier Drive racine (défaut : DRIVE_CONTROLE_FOLDER_ID).
    Retourne le chemin local ou None (dossier/fichier absent, Drive inaccessible).
    """
    root_id = root_id or DRIVE_CONTROLE_FOLDER_ID
    if not root_id:
        return None
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload
        svc = _get_drive_service()
        if not svc:
            return None
        archives_id = _trouver_dossier_drive(svc, root_id, "Archives")
        if not archives_id:
            return None
        sub_id = _trouver_dossier_drive(svc, archives_id, subfolder)
        if not sub_id:
            return None
        res = svc.files().list(
            q=f"name='{nom}' and '{sub_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
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
        print(f"  → {chemin} téléchargé depuis Archives/{subfolder}/ ({os.path.getsize(chemin):,} octets)")
        return chemin
    except Exception as e:
        print(f"  telecharger_fichier_archive({subfolder}/{nom}) échoué : {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Upload Drive (optionnel)
# ─────────────────────────────────────────────────────────────────

def _get_or_create_subfolder_drive(svc, parent_id, name):
    """Retourne l'ID d'un sous-dossier Drive, le crée si absent."""
    try:
        res = svc.files().list(
            q=(f"name='{name}' and '{parent_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        folder = svc.files().create(
            body={"name": name,
                  "mimeType": "application/vnd.google-apps.folder",
                  "parents": [parent_id]},
            fields="id",
        ).execute()
        return folder["id"]
    except Exception as e:
        print(f"  Création dossier Drive '{name}' échouée : {e}")
        return None


def upload_to_archive(local_path, subfolder, filename=None, root_id=None):
    """Upload dans {root_id}/Archives/{subfolder}/ (écrase si existant).

    root_id  : dossier Drive racine (défaut : DRIVE_CONTROLE_FOLDER_ID).
    filename : nom cible sur Drive (défaut : basename de local_path).
    """
    root_id = root_id or DRIVE_CONTROLE_FOLDER_ID
    if not root_id:
        return False
    try:
        from googleapiclient.http import MediaFileUpload
        svc = _get_drive_service()
        if not svc:
            return False
        archives_id = _get_or_create_subfolder_drive(svc, root_id, "Archives")
        if not archives_id:
            return False
        sub_id = _get_or_create_subfolder_drive(svc, archives_id, subfolder)
        if not sub_id:
            return False
        if filename is None:
            filename = os.path.basename(local_path)
        ext = os.path.splitext(local_path)[1].lower()
        if ext in (".xlsx", ".xls"):
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            mime = "text/plain"
        res = svc.files().list(
            q=f"name='{filename}' and '{sub_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        media = MediaFileUpload(local_path, mimetype=mime, resumable=False)
        if existing:
            svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
        else:
            svc.files().create(
                body={"name": filename, "parents": [sub_id]},
                media_body=media, fields="id",
            ).execute()
        print(f"  {filename} → Drive Archives/{subfolder}/ OK")
        return True
    except Exception as e:
        print(f"  Upload Archives/{subfolder}/ échoué : {e}")
        return False


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

def _construire_pdf_tableau(rows, titre_html, nom_pdf, complet=True, vms_map=None):
    """Génère un PDF tableau pour la liste de lignes fournie. Retourne le chemin ou None.

    complet=True  : code-barres, libellé, J-1, ventes, théo, J, écart.
    complet=False : code-barres, libellé, stock du jour (+ VMS si vms_map fourni).
    """
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

    if not rows:
        return None

    doc = SimpleDocTemplate(nom_pdf, pagesize=A4,
                            topMargin=8*mm, bottomMargin=8*mm,
                            leftMargin=3*mm, rightMargin=3*mm)

    styles  = getSampleStyleSheet()
    small   = ParagraphStyle('small', fontSize=8, leading=10)
    header_s = ParagraphStyle('hdr', fontSize=8, leading=10, textColor=colors.white)

    elements = []
    elements.append(Paragraph(titre_html, styles['Title']))
    elements.append(Spacer(1, 5*mm))

    if complet:
        col_widths = [108, 246, 33, 40, 33, 33, 34]  # ≈ 527 pt (marges 3mm, sans colonne gencod)
        hdr_txts = ['Code-barres', 'Libellé', 'J-1', 'Ventes', 'Théo', 'J', 'Écart']
    elif vms_map is not None:
        col_widths = [108, 296, 53, 70]  # ≈ 527 pt
        hdr_txts = ['Code-barres', 'Libellé', 'Stock du jour', 'VMS']
    else:
        col_widths = [108, 366, 53]  # ≈ 527 pt
        hdr_txts = ['Code-barres', 'Libellé', 'Stock du jour']
    hdr = [Paragraph(t, header_s) for t in hdr_txts]
    data = [hdr]

    tiny_c = ParagraphStyle('tiny_c', fontSize=7, leading=8, alignment=1)

    for r in rows:
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
        if complet:
            data.append([
                bc_cell,
                Paragraph(lib, small),
                Paragraph(str(int(s_j1)), small),
                Paragraph(str(int(v)),    small),
                Paragraph(str(int(s_theo)), small),
                Paragraph(str(int(s_j)),  small),
                Paragraph(f"{int(ecart):+d}", small),
            ])
        else:
            ligne = [bc_cell, Paragraph(lib, small), Paragraph(str(int(s_j)), small)]
            if vms_map is not None:
                vms_txt = f"{vms_map.get(gencod, 0.0):.1f}".replace('.', ',')
                ligne.append(Paragraph(vms_txt, small))
            data.append(ligne)

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
    if complet:
        for i, r in enumerate(rows, 1):
            c = colors.HexColor('#D32F2F') if float(r[5]) < 0 else colors.HexColor('#E65100')
            style.add('TEXTCOLOR', (6, i), (6, i), c)
            style.add('FONTNAME',  (6, i), (6, i), 'Helvetica-Bold')

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(style)
    elements.append(table)
    doc.build(elements)
    print(f"  → {nom_pdf} ({len(rows)} ligne(s))")
    return nom_pdf


def generer_pdf_ecarts(compares, date_j1, date_debut=None):
    """Génère un PDF des lignes ECART (trié |écart| desc). Retourne le chemin ou None."""
    ecarts = [r for r in compares if r[6] == "ECART"]
    if not ecarts:
        return None

    nom_pdf = f"ecarts_{date_j1.strftime('%Y%m%d')}.pdf"
    label_dates = (f"{date_debut.strftime('%d/%m/%Y')} &amp; {date_j1.strftime('%d/%m/%Y')}"
                   if date_debut and date_debut < date_j1
                   else date_j1.strftime('%d/%m/%Y'))
    titre_html = (f"<b>Contrôle de stocks — {label_dates}</b>"
                  f"&nbsp;&nbsp;({len(ecarts)} écarts)")
    return _construire_pdf_tableau(ecarts, titre_html, nom_pdf)


def generer_pdf_stock_insuffisant(stock_bas, date_courante, vms_map=None):
    """Génère un PDF listant tous les produits dont le stock J est <= SEUIL_STOCK_BAS.
    Retourne le chemin ou None."""
    if not stock_bas:
        return None

    nom_pdf = f"stock_insuffisant_{date_courante.strftime('%Y%m%d')}.pdf"
    titre_html = (f"<b>Stocks insuffisant Drive - {date_courante.strftime('%d/%m/%Y')}</b>"
                  f"&nbsp;&nbsp;({len(stock_bas)} produit{'s' if len(stock_bas) > 1 else ''})")
    return _construire_pdf_tableau(stock_bas, titre_html, nom_pdf, complet=False, vms_map=vms_map)


def generer_pdf_a_deloter(a_deloter, date_courante, vms_map=None):
    """Génère un PDF listant les produits en stock insuffisant (stock J <=
    SEUIL_STOCK_BAS) mais rattachés au classeur "DRIVE DÉLOTAGE" — exclus du
    PDF stock insuffisant, à traiter via le délotage plutôt qu'un
    réapprovisionnement. Retourne le chemin ou None."""
    if not a_deloter:
        return None

    nom_pdf = f"articles_a_deloter_{date_courante.strftime('%Y%m%d')}.pdf"
    titre_html = (f"<b>Articles à deloter - {date_courante.strftime('%d/%m/%Y')}</b>"
                  f"&nbsp;&nbsp;({len(a_deloter)} produit{'s' if len(a_deloter) > 1 else ''})")
    return _construire_pdf_tableau(a_deloter, titre_html, nom_pdf, complet=False, vms_map=vms_map)


def generer_pdf_lgv(a_commander, date_courante, vms_map, semaine_suivante):
    """Génère un PDF listant les produits du classeur DRIVE LGV dont le stock
    est insuffisant au regard de leurs ventes (Stock UC < 2×VMS). Retourne le
    chemin ou None."""
    if not a_commander:
        return None

    nom_pdf = f"lgv_a_commander_{date_courante.strftime('%Y%m%d')}.pdf"
    titre_html = (f"<b>LGV à commander S{semaine_suivante:02d}</b>"
                  f"&nbsp;&nbsp;({len(a_commander)} produit{'s' if len(a_commander) > 1 else ''})")
    return _construire_pdf_tableau(a_commander, titre_html, nom_pdf, complet=False, vms_map=vms_map)


def envoyer_email_pdf(pdf_ecarts, pdf_stock_bas, pdf_a_deloter, date_j1, nb_ecart, manquant, surplus,
                      nb_stock_bas, nb_a_deloter, date_debut=None, date_courante=None):
    """Envoie par email les PDF d'écarts, de stocks insuffisants et/ou
    d'articles à déloter (Gmail API)."""
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
        msg['Cc']      = EMAIL_COPIE_STOCK
        label_dates = (f"{date_debut.strftime('%d/%m/%Y')} & {date_j1.strftime('%d/%m/%Y')}"
                       if date_debut and date_debut < date_j1
                       else date_j1.strftime('%d/%m/%Y'))

        parties_sujet = []
        if nb_ecart > 0:
            parties_sujet.append(f"{nb_ecart} écart{'s' if nb_ecart > 1 else ''}")
        if nb_stock_bas > 0:
            parties_sujet.append(f"{nb_stock_bas} stock{'s' if nb_stock_bas > 1 else ''} bas")
        if nb_a_deloter > 0:
            parties_sujet.append(f"{nb_a_deloter} à déloter")
        msg['Subject'] = f"Contrôle stocks {label_dates}"
        if parties_sujet:
            msg['Subject'] += " — " + ", ".join(parties_sujet)

        corps = f"Contrôle de stocks du {label_dates}\n\n"
        if pdf_ecarts:
            corps += (f"  Écarts   : {nb_ecart}\n"
                      f"  Manquant : {manquant:.0f} unités\n"
                      f"  Surplus  : +{surplus:.0f} unités\n\n")
        if pdf_stock_bas:
            date_label = (date_courante or date_j1).strftime('%d/%m/%Y')
            corps += (f"  Stocks insuffisant Drive - {date_label} "
                      f"(stock J ≤ {SEUIL_STOCK_BAS}) : {nb_stock_bas} produit"
                      f"{'s' if nb_stock_bas > 1 else ''}\n\n")
        if pdf_a_deloter:
            date_label = (date_courante or date_j1).strftime('%d/%m/%Y')
            corps += (f"  Articles à deloter - {date_label} : {nb_a_deloter} produit"
                      f"{'s' if nb_a_deloter > 1 else ''}\n\n")
        corps += "Détail en pièce(s) jointe(s)."
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))

        for pdf_path in (pdf_ecarts, pdf_stock_bas, pdf_a_deloter):
            if not pdf_path:
                continue
            with open(pdf_path, 'rb') as f:
                part = MIMEApplication(f.read(), 'pdf')
                part.add_header('Content-Disposition', 'attachment',
                                filename=os.path.basename(pdf_path))
                msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email envoyé → {EMAIL_DESTINATAIRE} (cc: {EMAIL_COPIE_STOCK})")
    except Exception as e:
        print(f"  Email échoué : {e}")


def envoyer_email_lgv(pdf_lgv, nb, semaine_suivante):
    """Envoie par email (au destinataire principal uniquement, sans copie) le
    PDF des produits du classeur DRIVE LGV à commander (Stock UC < 2×VMS)."""
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
        msg['Subject'] = f"LGV à commander S{semaine_suivante:02d}"

        corps = (f"LGV à commander pour la semaine S{semaine_suivante:02d}\n\n"
                 f"  {nb} produit{'s' if nb > 1 else ''} (classeur {CLASSEUR_LGV}, "
                 f"Stock UC < 2×VMS)\n\n"
                 f"Détail en pièce jointe.")
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))

        with open(pdf_lgv, 'rb') as f:
            part = MIMEApplication(f.read(), 'pdf')
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_lgv))
        msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email LGV à commander envoyé → {EMAIL_DESTINATAIRE}")
    except Exception as e:
        print(f"  Email LGV échoué : {e}")


# ─────────────────────────────────────────────────────────────────
# Config Drive
# ─────────────────────────────────────────────────────────────────

def _charger_config():
    """Charge config.json depuis DRIVE_CONFIG_FOLDER_ID et initialise les globals."""
    global DRIVE_CONTROLE_FOLDER_ID, DRIVE_BDC_FOLDER_ID, EMAIL_DESTINATAIRE, EMAIL_COPIE_STOCK
    if not DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : secret DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)
    import io as _io
    from googleapiclient.http import MediaIoBaseDownload
    svc = _get_drive_service()
    if not svc:
        print("ERREUR : Drive inaccessible pour charger la config.")
        sys.exit(1)
    try:
        res = svc.files().list(
            q=f"name='config.json' and '{DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            print("ERREUR : config.json introuvable dans le dossier Drive config.")
            sys.exit(1)
        buf = _io.BytesIO()
        dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        cfg = json.loads(buf.getvalue().decode())
        DRIVE_CONTROLE_FOLDER_ID = cfg["drive_controle_folder_id"]
        DRIVE_BDC_FOLDER_ID      = cfg["drive_bdc_folder_id"]
        EMAIL_DESTINATAIRE       = cfg["email_destinataire"]
        EMAIL_COPIE_STOCK        = cfg["email_destinataire_2"]
    except Exception as e:
        print(f"ERREUR chargement config Drive : {e}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    args = [a for a in args if a != "--upload"]  # flag ignoré, upload toujours actif

    # --date JJ/MM/AAAA (dernier jour de ventes)
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

    # --jours N (nombre de jours de ventes à cumuler, défaut 1)
    nb_jours = 1
    if "--jours" in args:
        i = args.index("--jours")
        if i + 1 < len(args):
            try:
                nb_jours = max(1, int(args[i + 1]))
            except ValueError:
                print(f"Valeur invalide pour --jours : {args[i + 1]}")
                sys.exit(1)
            args.pop(i + 1)
            args.pop(i)

    if len(args) not in (1, 2):
        print(__doc__)
        sys.exit(1)

    if len(args) == 2:
        fichier_j1, fichier_j = args
    else:
        fichier_j1, fichier_j = None, args[0]

    _charger_config()

    # 1. Lire les stocks
    if fichier_j1 and os.path.exists(fichier_j1):
        print(f"Lecture stock J-{nb_jours} : {fichier_j1}")
        stock_j1, libelles_stock, classeurs_stock = lire_stock(fichier_j1)
        print(f"  → {len(stock_j1)} gencods, {len(libelles_stock)} libellés xlsx")
    else:
        if fichier_j1:
            print(f"  {fichier_j1} absent — stock de départ vide.")
        stock_j1, libelles_stock, classeurs_stock = {}, {}, {}

    print(f"Lecture stock J   : {fichier_j}")
    stock_j, libelles_stock_j, classeurs_stock_j = lire_stock(fichier_j)
    print(f"  → {len(stock_j)} gencods")
    upload_to_archive(fichier_j, "stocks", f"stock_{date.today().strftime('%d_%m_%Y')}_j.xlsx",
                       root_id=DRIVE_CONFIG_FOLDER_ID)
    for g, l in libelles_stock_j.items():
        if g not in libelles_stock:
            libelles_stock[g] = l
    for g, c in classeurs_stock_j.items():
        classeurs_stock[g] = c  # classeur du jour prioritaire (le plus à jour)

    # Charger le dictionnaire complet coursesu.com (priorité sur xlsx tronqué)
    print("\nChargement libellés coursesu ...")
    libelles_dict = charger_libelles_dict()

    # 2. Ventes de la période pour calculer le stock théorique (stock_j1 - cumul ventes)
    date_debut = date_j1 - timedelta(days=nb_jours - 1)
    if nb_jours > 1:
        print(f"\nChargement ventes du {date_debut.strftime('%d/%m/%Y')} au {date_j1.strftime('%d/%m/%Y')} ({nb_jours} jours) …")
    else:
        print(f"\nChargement ventes du {date_j1.strftime('%d/%m/%Y')} …")

    ventes = {}
    libelles_extra = {}
    for i in range(nb_jours):
        d = date_debut + timedelta(days=i)
        v_day, l_day = generer_ventes(d)
        for gencod, qty in v_day.items():
            ventes[gencod] = ventes.get(gencod, 0) + qty
            if gencod not in libelles_extra and gencod in l_day:
                libelles_extra[gencod] = l_day[gencod]

    # 3. Comparaison — uniquement les 1087 gencods R1
    gencods_r1 = charger_gencods_r1()
    tous = gencods_r1 if gencods_r1 is not None else (set(stock_j1) | set(stock_j))

    compares   = []
    orphelins  = []
    stock_bas  = []
    a_deloter  = []

    for gencod in sorted(tous):
        present_j1 = gencod in stock_j1
        s_j1   = stock_j1.get(gencod, 0.0)
        v      = ventes.get(gencod, 0.0)
        # Le stock Drive ne descend jamais sous 0 : un théorique négatif
        # (ventes > stock J-1) est normal et ne doit pas générer un faux écart.
        s_theo = max(0.0, s_j1 - v)
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
        else:
            statut = "OK" if abs(ecart) < 0.001 else "ECART"
        # tuple : gencod, s_j1, v, s_theo, s_j, ecart, statut, libelle
        row = (gencod, s_j1, v, s_theo, s_j, ecart, statut, lib)

        if present_j and s_j <= SEUIL_STOCK_BAS:
            classeur = classeurs_stock.get(gencod, '')
            if _normaliser_classeur(classeur) == _normaliser_classeur(CLASSEUR_DELOTAGE):
                a_deloter.append(row)
            else:
                stock_bas.append(row)

        # Stock à 0 deux jours de suite : écart non significatif, on ne le
        # remonte pas dans le rapport d'écarts (mais il reste dans stock_bas
        # ci-dessus, car c'est justement le cas de rupture le plus critique).
        if s_j1 == 0 and s_j == 0:
            continue

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

    stock_bas.sort(key=lambda r: (r[4], r[0]))
    a_deloter.sort(key=lambda r: (r[4], r[0]))

    print(f"\n── Résultats ──────────────────────────────────────")
    print(f"  Gencods appairés  : {len(compares)}")
    print(f"    Sans écart (OK) : {nb_ok}")
    print(f"    Avec écart      : {nb_ecart}")
    if orphelins:
        print(f"  Gencods orphelins : {len(orphelins)}")
    print(f"  Total manquant    : {manquant:.0f} unités")
    print(f"  Total surplus     : {+surplus:.0f} unités")
    print(f"  Stocks ≤ {SEUIL_STOCK_BAS}       : {len(stock_bas)} produit(s)")
    print(f"  Dont à déloter    : {len(a_deloter)} produit(s)")

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
    upload_to_archive(nom_sortie, "écarts", root_id=DRIVE_CONFIG_FOLDER_ID)

    nom_pdf_ecarts = None
    if nb_ecart > 0:
        print("\nGénération PDF écarts …")
        nom_pdf_ecarts = generer_pdf_ecarts(compares, date_j1, date_debut)

    date_courante = date.today()
    nom_pdf_stock_bas = None
    nom_pdf_a_deloter = None
    if stock_bas or a_deloter:
        vms_map = calculer_vms([r[0] for r in stock_bas] + [r[0] for r in a_deloter], date_courante)
        if stock_bas:
            print("\nGénération PDF stocks insuffisants …")
            nom_pdf_stock_bas = generer_pdf_stock_insuffisant(stock_bas, date_courante, vms_map)
        if a_deloter:
            print("\nGénération PDF articles à déloter …")
            nom_pdf_a_deloter = generer_pdf_a_deloter(a_deloter, date_courante, vms_map)

    # LGV à commander : tous les produits du classeur DRIVE LGV (pas
    # seulement ceux sous SEUIL_STOCK_BAS) dont le Stock UC est inférieur à
    # 2× leur VMS (moyenne des 3 dernières semaines de ventes cumulées).
    # Email séparé, au destinataire principal uniquement.
    gencods_lgv = sorted(g for g, c in classeurs_stock.items()
                        if g in stock_j and _normaliser_classeur(c) == _normaliser_classeur(CLASSEUR_LGV))
    if gencods_lgv:
        vms_lgv = calculer_vms(gencods_lgv, date_courante, nb_semaines=3)
        a_commander_lgv = []
        for gencod in gencods_lgv:
            stock_uc = stock_j.get(gencod, 0.0)
            if stock_uc < 2 * vms_lgv.get(gencod, 0.0):
                lib = (libelles_dict.get(gencod)
                      or libelles_stock.get(gencod)
                      or libelles_extra.get(gencod, ''))
                a_commander_lgv.append((gencod, 0, 0, 0, stock_uc, 0, '', lib))
        a_commander_lgv.sort(key=lambda r: r[0])
        if a_commander_lgv:
            lundi_prochain = (date_courante - timedelta(days=date_courante.weekday())
                              + timedelta(weeks=1))
            semaine_suivante = lundi_prochain.isocalendar()[1]
            print(f"\nLGV à commander : {len(a_commander_lgv)} produit(s) "
                  f"(classeur {CLASSEUR_LGV}, Stock UC < 2×VMS)")
            nom_pdf_lgv = generer_pdf_lgv(a_commander_lgv, date_courante, vms_lgv, semaine_suivante)
            if nom_pdf_lgv:
                print("Envoi email LGV …")
                envoyer_email_lgv(nom_pdf_lgv, len(a_commander_lgv), semaine_suivante)

    if nom_pdf_ecarts or nom_pdf_stock_bas or nom_pdf_a_deloter:
        print("\nEnvoi email …")
        envoyer_email_pdf(nom_pdf_ecarts, nom_pdf_stock_bas, nom_pdf_a_deloter, date_j1, nb_ecart,
                          manquant, surplus, len(stock_bas), len(a_deloter), date_debut, date_courante)


# ─────────────────────────────────────────────────────────────────
# Correction des anomalies de point-virgules dans les bons de prépa
# ─────────────────────────────────────────────────────────────────

def corriger_bon_prepa(chemin, nb_sep=4):
    """Corrige les lignes avec trop de point-virgules dans un bon de préparation.

    Format attendu : gencod;libellé;prix;remise;qty  (nb_sep=4 séparateurs).
    Quand une ligne contient plus de séparateurs, les champs excédentaires
    (issus du libellé) sont refusionnés.  Les lignes trop courtes sont
    conservées telles quelles (on ne peut pas les corriger automatiquement).

    Retourne (nb_corrections, [messages]).
    """
    try:
        try:
            with open(chemin, encoding='utf-8') as f:
                lignes = f.readlines()
        except UnicodeDecodeError:
            with open(chemin, encoding='latin-1') as f:
                lignes = f.readlines()
    except Exception as e:
        print(f"  Impossible de lire {chemin} : {e}")
        return 0, []

    lignes_corrigees = []
    corrections = []

    for i, ligne in enumerate(lignes, 1):
        stripped = ligne.rstrip('\n\r')
        if not stripped.strip():
            lignes_corrigees.append(ligne)
            continue
        parts = stripped.split(';')
        if len(parts) == nb_sep + 1:
            lignes_corrigees.append(ligne)
        elif len(parts) > nb_sep + 1:
            gencod  = parts[0]
            qty     = parts[-1]
            remise  = parts[-2]
            prix    = parts[-3]
            libelle = ';'.join(parts[1:-3])
            eol = '\n' if ligne.endswith('\n') else ''
            lignes_corrigees.append(f"{gencod};{libelle};{prix};{remise};{qty}{eol}")
            avant = ';'.join(parts[1:-3]) if len(parts) > 4 else parts[1]
            corrections.append(
                f"L{i}: {len(parts)-1}→{nb_sep} sep  "
                f"gencod={gencod}  libellé={avant!r}"
            )
        else:
            lignes_corrigees.append(ligne)

    if corrections:
        try:
            with open(chemin, 'w', encoding='utf-8') as f:
                f.writelines(lignes_corrigees)
            print(f"  {os.path.basename(chemin)} : {len(corrections)} ligne(s) corrigée(s)")
        except Exception as e:
            print(f"  Impossible d'écrire {chemin} : {e}")
            return 0, []

    return len(corrections), corrections


def _trouver_dossier_drive(svc, parent_id, name):
    """Retourne l'ID d'un sous-dossier Drive (None si absent, sans créer)."""
    try:
        res = svc.files().list(
            q=(f"name='{name}' and '{parent_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None
    except Exception:
        return None


def corriger_bons_prepa_drive():
    """Cherche les bon_prepa*.txt sur Drive, corrige les anomalies et re-uploade.

    Cherche dans DRIVE_CONTROLE_FOLDER_ID (racine) et dans le sous-dossier
    Archives/bons/ s'il existe.

    Retourne [(nom_fichier, nb_corrections, [messages]), ...] pour les
    fichiers effectivement modifiés.
    """
    resultats = []
    if not DRIVE_CONTROLE_FOLDER_ID:
        print("  DRIVE_CONTROLE_FOLDER_ID non configuré — correction Drive ignorée.")
        return resultats

    svc = _get_drive_service()
    if not svc:
        print("  Drive inaccessible — correction ignorée.")
        return resultats

    try:
        import io as _io
        from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

        def _lister(folder_id):
            res = svc.files().list(
                q=(f"'{folder_id}' in parents and trashed=false "
                   f"and name contains 'bon_prepa'"),
                fields="files(id,name,mimeType)",
            ).execute()
            return [(f, folder_id) for f in res.get("files", [])
                    if not f.get("mimeType", "").endswith(".folder")]

        def _telecharger(file_id, dest):
            req = svc.files().get_media(fileId=file_id)
            buf = _io.BytesIO()
            dl  = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            with open(dest, "wb") as f:
                f.write(buf.getvalue())

        def _uploader(file_id, local_path, folder_id, filename):
            media = MediaFileUpload(local_path, mimetype="text/plain", resumable=False)
            if file_id:
                svc.files().update(fileId=file_id, media_body=media).execute()
            else:
                svc.files().create(
                    body={"name": filename, "parents": [folder_id]},
                    media_body=media, fields="id",
                ).execute()
            print(f"  {filename} re-uploadé → Drive OK")

        # Racine + Archives/bons/ (si existant)
        entrees = _lister(DRIVE_CONTROLE_FOLDER_ID)
        archives_id = _trouver_dossier_drive(svc, DRIVE_CONTROLE_FOLDER_ID, "Archives")
        if archives_id:
            bons_id = _trouver_dossier_drive(svc, archives_id, "bons")
            if bons_id:
                entrees += _lister(bons_id)

        if not entrees:
            print("  Aucun fichier bon_prepa trouvé sur Drive.")
            return resultats

        for fichier, folder_id in entrees:
            nom   = fichier["name"]
            fid   = fichier["id"]
            local = f"_tmp_{nom}"
            print(f"\nAnalyse {nom} …")
            try:
                _telecharger(fid, local)
                nb, corrections = corriger_bon_prepa(local)
                if nb > 0:
                    _uploader(fid, local, folder_id, nom)
                    resultats.append((nom, nb, corrections))
                else:
                    print(f"  {nom} : aucune anomalie de point-virgule.")
            except Exception as e:
                print(f"  Erreur traitement {nom} : {e}")
            finally:
                if os.path.exists(local):
                    os.remove(local)

    except Exception as e:
        print(f"  corriger_bons_prepa_drive échoué : {e}")

    return resultats


def envoyer_email_corrections_bon_prepa(resultats, date_str=None):
    """Envoie un email récapitulatif des corrections de point-virgules appliquées."""
    if not resultats:
        return
    try:
        import base64
        from datetime import date as _date
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        svc = _get_gmail_service()
        if not svc:
            return

        date_label = date_str or _date.today().strftime('%d/%m/%Y')
        nb_total   = sum(r[1] for r in resultats)

        msg = MIMEMultipart()
        msg['To']      = EMAIL_DESTINATAIRE
        msg['Subject'] = (
            f"[Auto-correction] Bons de prépa — "
            f"{nb_total} point-virgule(s) corrigé(s) — {date_label}"
        )

        corps  = f"Correction automatique des bons de préparation — {date_label}\n"
        corps += "=" * 60 + "\n\n"
        for nom, nb, corrections in resultats:
            corps += f"Fichier : {nom}  ({nb} correction(s))\n"
            for c in corrections:
                corps += f"  {c}\n"
            corps += "\n"
        corps += "Les fichiers ont été corrigés et re-sauvegardés sur Drive.\n"

        msg.attach(MIMEText(corps, 'plain', 'utf-8'))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email de correction envoyé → {EMAIL_DESTINATAIRE}")
    except Exception as e:
        print(f"  Email de correction échoué : {e}")


if __name__ == "__main__":
    main()
