#!/usr/bin/env python3
"""
auto_prepa.py - Automatisation préparation Drive supermarché
Détecte les nouvelles commandes du jour dans le Google Sheets,
télécharge les PDFs correspondants, génère bon_prepa.txt
et le pousse sur le téléphone via USB.
"""

import os
import sys
import json
import shutil
import subprocess
import io
import tempfile
import fcntl
from datetime import date
import argparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION — à remplir une seule fois
# ─────────────────────────────────────────────────────────────────

# ID du Google Sheets (dans l'URL : /spreadsheets/d/CECI/edit)
SPREADSHEET_ID = "1COrHcrypy4Xkp0MpE5Mag80xf01ZLjpUdYe6jpuS8b8"

# Colonnes dans la plage "A:N" (index 0 = colonne A)
COL_DATE    = 4  # E : date au format JJ/MM/AAAA
COL_NUMERO  = 6  # G : numéro de commande
COL_MONTANT = 9  # J : montant de la commande

# ID du dossier Drive contenant les PDFs (dans l'URL : /folders/CECI)
DRIVE_FOLDER_ID = "14qLtxkSkoPkwJJCu3dsRL784TJ6o9Etn"

# Répertoire de base : dossier contenant ce script (fonctionne en local et en CI)
_BASE = os.path.dirname(os.path.abspath(__file__))

# Dossier de travail du programme C++
WORK_DIR  = os.environ.get("WORK_DIR",  os.path.join(_BASE, "v 3.0x", "v 3.7.4"))

# Dossier cache : PDFs téléchargés une fois, conservés ici
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(_BASE, "pdf_cache"))

# Archive des PDFs d'origine, un sous-dossier par jour (JJ_MM)
BDC_DIR   = os.environ.get("BDC_DIR",   os.path.join(_BASE, "BDC"))

# Fichiers internes
TOKEN_FILE = os.path.expanduser("~/.auto_prepa_token.json")
CREDS_FILE = os.path.expanduser("~/.auto_prepa_credentials.json")

# Nom du fichier d'état stocké dans DRIVE_BONS_FOLDER_ID
STATE_DRIVE_FILENAME = "auto_prepa_state.json"


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive",
]

# Dossier Drive où déposer les bons pour le téléphone.
# Créer un dossier "MobUDrive_Bons" dans Drive, copier son ID ici.
DRIVE_BONS_FOLDER_ID = "1yw_z0d90UxAix6RZ-fLpxKXuc897ghk_"


# ── Auth ───────────────────────────────────────────────────────────

def get_credentials():
    # En CI : variable d'environnement contenant le JSON du compte de service
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=SCOPES)

    # En local : flux OAuth classique
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                print(f"Fichier credentials manquant : {CREDS_FILE}")
                print("Voir README_SETUP.txt pour la procédure.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


# ── État (liste plate des bons traités, stockée dans Drive) ──────

def charger_traites(drive_svc):
    """Retourne l'ensemble des BonDeCommande_*.pdf déjà traités."""
    try:
        res = drive_svc.files().list(
            q=f"name='{STATE_DRIVE_FILENAME}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return set()
        req = drive_svc.files().get_media(fileId=files[0]["id"])
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        data = json.loads(buf.getvalue().decode())
        # Compatibilité ascendante : ancien format {"DD/MM/YYYY": [...]}
        if isinstance(data, dict):
            flat = set()
            for v in data.values():
                if isinstance(v, list):
                    flat.update(v)
            return flat
        if isinstance(data, list):
            return set(data)
        return set()
    except Exception as e:
        print(f"  Historique Drive non disponible ({e}), démarrage à zéro.")
        return set()


def sauvegarder_traites(drive_svc, traites):
    """Sauvegarde la liste des bons traités dans Drive."""
    try:
        res = drive_svc.files().list(
            q=f"name='{STATE_DRIVE_FILENAME}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as f:
            json.dump(sorted(traites), f, indent=2, ensure_ascii=False)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="application/json", resumable=False)
            if existing:
                drive_svc.files().update(
                    fileId=existing[0]["id"], media_body=media).execute()
            else:
                drive_svc.files().create(
                    body={"name": STATE_DRIVE_FILENAME, "parents": [DRIVE_BONS_FOLDER_ID]},
                    media_body=media, fields="id").execute()
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"  Sauvegarde historique Drive échouée : {e}")


# ── Google Sheets ─────────────────────────────────────────────────

def get_orders_a_venir(sheets_svc):
    """Retourne {filename: (montant, dossier_jj_mm)} pour les commandes d'aujourd'hui et du futur."""
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="A:N",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    rows = res.get("values", [])
    today = date.today()
    orders = {}
    for row in rows[1:]:
        if len(row) <= COL_DATE:
            continue
        try:
            j, m, a = row[COL_DATE].strip().split("/")
            d = date(int(a), int(m), int(j))
        except (ValueError, TypeError):
            continue
        if d < today:
            continue
        if len(row) <= COL_NUMERO:
            continue
        try:
            num = int(float(str(row[COL_NUMERO]).replace(",", ".")))
            montant = row[COL_MONTANT].strip() if len(row) > COL_MONTANT else ""
            dossier = d.strftime("%d_%m")
            orders[f"BonDeCommande_{num}.pdf"] = (montant, dossier)
        except (ValueError, TypeError):
            pass
    return orders


# ── Google Drive ───────────────────────────────────────────────────

def debug_list_folder(drive_svc):
    print(f"\n── DEBUG : contenu du dossier Drive ({DRIVE_FOLDER_ID}) ──")
    for corpora in ["user", "allDrives"]:
        params = dict(
            q=f"'{DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id, name, mimeType)",
            pageSize=20,
            corpora=corpora,
        )
        if corpora == "allDrives":
            params["includeItemsFromAllDrives"] = True
            params["supportsAllDrives"] = True
        try:
            res = drive_svc.files().list(**params).execute()
            files = res.get("files", [])
            print(f"  corpora={corpora} → {len(files)} fichier(s)")
            for f in files[:10]:
                print(f"    • {f['name']}  ({f['mimeType']})")
            if len(files) > 10:
                print(f"    … et {len(files)-10} autres")
        except Exception as e:
            print(f"  corpora={corpora} → erreur : {e}")

    print("\n── DEBUG : recherche sans contrainte de dossier ──")
    try:
        res = drive_svc.files().list(
            q="name contains 'BonDeCommande' and trashed=false",
            fields="files(id, name, parents)",
            pageSize=5,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        files = res.get("files", [])
        print(f"  {len(files)} fichier(s) 'BonDeCommande' accessibles :")
        for f in files:
            print(f"    • {f['name']}  parents={f.get('parents')}")
    except Exception as e:
        print(f"  Erreur : {e}")
    print()


def lister_bons_disponibles(drive_svc):
    """Retourne {filename_avec_pdf: drive_id} pour tous les BonDeCommande disponibles."""
    bons = {}
    page_token = None
    while True:
        params = dict(
            q="name contains 'BonDeCommande' and trashed=false",
            fields="nextPageToken,files(id,name)",
            pageSize=200,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        if page_token:
            params["pageToken"] = page_token
        res = drive_svc.files().list(**params).execute()
        for f in res.get("files", []):
            name = f["name"]
            local_name = name if name.endswith(".pdf") else name + ".pdf"
            if local_name.startswith("BonDeCommande_"):
                bons[local_name] = f["id"]
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return bons


def chercher_confirmation_commande(drive_svc, numero):
    """Cherche 'Confirmation commande ... cde : NUMERO' dans tout Drive.
    Retourne (drive_id, nom_original) ou (None, None) si introuvable."""
    try:
        res = drive_svc.files().list(
            q=f"name contains '{numero}' and mimeType='application/pdf' and trashed=false",
            fields="files(id, name)",
            pageSize=20,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        for f in res.get("files", []):
            name = f["name"]
            # Vérifie que c'est bien une confirmation de commande et non un autre PDF
            name_lower = name.lower()
            if "confirmation" in name_lower or ("commande" in name_lower and "cde" in name_lower):
                return f["id"], name
    except Exception as e:
        print(f"    Recherche confirmation {numero} : erreur {e}")
    return None, None


def download_pdf(drive_svc, file_id, dest_path):
    req = drive_svc.files().get_media(
        fileId=file_id,
        supportsAllDrives=True,
    )
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest_path, "wb") as f:
        f.write(buf.getvalue())


def upload_bon(drive_svc, local_path):
    """Dépose un fichier dans DRIVE_BONS_FOLDER_ID, écrase s'il existe déjà."""
    if not DRIVE_BONS_FOLDER_ID:
        return False
    filename = os.path.basename(local_path)

    # Vérifier que le dossier est accessible
    try:
        drive_svc.files().get(fileId=DRIVE_BONS_FOLDER_ID, fields="id").execute()
    except Exception as e:
        print(f"    Dossier Drive inaccessible (ID={DRIVE_BONS_FOLDER_ID}) : {e}")
        return False

    # Chercher si le fichier existe déjà (sans contrainte de space)
    try:
        res = drive_svc.files().list(
            q=f"name='{filename}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
    except Exception:
        existing = []

    media = MediaFileUpload(local_path, mimetype="text/plain", resumable=False)
    try:
        if existing:
            drive_svc.files().update(
                fileId=existing[0]["id"],
                media_body=media,
            ).execute()
        else:
            drive_svc.files().create(
                body={"name": filename, "parents": [DRIVE_BONS_FOLDER_ID]},
                media_body=media,
                fields="id",
            ).execute()
        print(f"    {filename} → Drive OK")
        return True
    except Exception as e:
        print(f"    {filename} → Drive ÉCHEC : {e}")
        return False


# ── Pipeline principal ────────────────────────────────────────────

LOCK_FILE = os.path.expanduser("~/.auto_prepa.lock")


def main():
    lock_f = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Une autre instance est déjà en cours d'exécution.")
        sys.exit(0)

    try:
        _main()
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true",
                        help="Lister les fichiers visibles dans le dossier Drive")
    args = parser.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)

    creds = get_credentials()
    sheets_svc = build("sheets", "v4", credentials=creds)
    drive_svc  = build("drive",  "v3", credentials=creds)

    if args.debug:
        debug_list_folder(drive_svc)
        return

    # Mettre à jour chemin_prepa_ramasse.csv sur Drive (pour le téléphone)
    chemin_csv = os.path.join(WORK_DIR, "chemin_prepa_ramasse.csv")
    if os.path.exists(chemin_csv):
        upload_bon(drive_svc, chemin_csv)

    # 1. Charger la liste des bons déjà traités
    traites = charger_traites(drive_svc)

    # 2. Commandes attendues aujourd'hui ou dans le futur (via Sheets)
    montants = get_orders_a_venir(sheets_svc)  # {filename: (montant, dossier_jj_mm)}
    attendus = set(montants.keys())

    # 3. Lister les BonDeCommande disponibles dans Drive et garder l'intersection
    disponibles = lister_bons_disponibles(drive_svc)  # {filename: drive_id}
    new_ones = {k: v for k, v in disponibles.items()
                if k in attendus and k not in traites}

    # Fallback : commandes attendues sans BonDeCommande → chercher "Confirmation commande"
    manquants = [f for f in attendus if f not in disponibles and f not in traites]
    for pdf in manquants:
        numero = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")
        fid, nom_original = chercher_confirmation_commande(drive_svc, numero)
        if fid:
            print(f"  → Confirmation trouvée pour {numero} : {nom_original}")
            new_ones[pdf] = fid
        else:
            print(f"  → Aucun PDF trouvé pour la commande {numero}")

    if not new_ones:
        print(f"Pas de nouvelle commande ({len(traites)} déjà traitée(s)).")
        return

    print(f"{len(new_ones)} nouvelle(s) commande(s) détectée(s) :")
    for pdf in sorted(new_ones):
        print(f"  • {pdf}")

    # 3. Télécharger les nouveaux PDFs dans le cache
    fetched = {}  # {filename: drive_id}
    for pdf, fid in sorted(new_ones.items()):
        cache_path = os.path.join(CACHE_DIR, pdf)
        if os.path.exists(cache_path):
            fetched[pdf] = fid
            continue
        print(f"  ↓ {pdf} ...", end="", flush=True)
        try:
            download_pdf(drive_svc, fid, cache_path)
            fetched[pdf] = fid
            print(" OK")
        except Exception as e:
            print(f" ÉCHEC : {e}")

    if not fetched:
        print("Aucun PDF récupéré avec succès.")
        return

    # 4. Traiter chaque nouveau PDF → bon_prepa_XXXXXXXX.txt
    os.makedirs(BDC_DIR, exist_ok=True)
    processed = set()

    for pdf in sorted(fetched):
        order_num = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")

        # Archiver le PDF d'origine dans BDC/JJ_MM/
        _, dossier_jj_mm = montants.get(pdf, ("", ""))
        bdc_subdir = os.path.join(BDC_DIR, dossier_jj_mm) if dossier_jj_mm else BDC_DIR
        os.makedirs(bdc_subdir, exist_ok=True)
        bdc_dst = os.path.join(bdc_subdir, pdf)
        if not os.path.exists(bdc_dst):
            shutil.copy2(os.path.join(CACHE_DIR, pdf), bdc_dst)

        # Nettoyer tous les fichiers temporaires du C++ avant génération
        for fname in [
            "bon_prepa.txt", "bon_anticipation.txt",
            "bon_prepa_NEW.txt", "bon_prepa_dlc.txt",
            "bon_encaissement.pdf", "bon_encaissement.csv", "bon_encaissement_NEW.csv",
            "base_client.txt", "tri_cde.txt", "tri_heures.txt",
            "tmp", "tmp2", "tmp_NEW", "temp", "gentemp.txt", "temp_lib.txt",
        ]:
            fpath = os.path.join(WORK_DIR, fname)
            if os.path.exists(fpath):
                os.remove(fpath)

        shutil.copy2(os.path.join(CACHE_DIR, pdf), os.path.join(WORK_DIR, pdf))

        # Vérifier que pdftotext arrive à lire le PDF
        pdf_path = os.path.join(WORK_DIR, pdf)
        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            print(f"  ÉCHEC pdftotext — PDF vide ou non lisible : {pdf}")
            os.remove(pdf_path)
            processed.add(pdf)
            continue

        print(f"  [{order_num}] Génération...", end="", flush=True)
        r = subprocess.run(["./prepa_drive_degrade"], cwd=WORK_DIR,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f" ERREUR (code {r.returncode})")
            if r.stdout: print(f"    stdout : {r.stdout[:300]}")
            if r.stderr: print(f"    stderr : {r.stderr[:300]}")
            p = os.path.join(WORK_DIR, pdf)
            if os.path.exists(p):
                os.remove(p)
            continue

        # Vérifier que le bon_prepa généré est non vide
        bon_prepa_path = os.path.join(WORK_DIR, "bon_prepa.txt")
        if not os.path.exists(bon_prepa_path) or os.path.getsize(bon_prepa_path) == 0:
            print(f" VIDE — bon_prepa.txt absent ou vide")
            if r.stdout: print(f"    sortie C++ : {r.stdout[:300]}")
            processed.add(pdf)
            continue
        print(" OK")

        # Injecter le montant dans l'en-tête du bon_prepa
        montant, _ = montants.get(pdf, ("", ""))
        if montant:
            with open(bon_prepa_path, 'r', encoding='utf-8') as f:
                lignes = f.readlines()
            if lignes:
                lignes[0] = lignes[0].rstrip('\n') + ',' + montant + '\n'
            with open(bon_prepa_path, 'w', encoding='utf-8') as f:
                f.writelines(lignes)

        # Renommer les sorties avec le numéro de commande
        for src_name, dst_name in [
            ("bon_prepa.txt",        f"bon_prepa_{order_num}.txt"),
            ("bon_anticipation.txt", f"bon_anticipation_{order_num}.txt"),
        ]:
            src_f = os.path.join(WORK_DIR, src_name)
            dst_f = os.path.join(WORK_DIR, dst_name)
            if os.path.exists(src_f):
                os.rename(src_f, dst_f)

        # Upload vers Drive puis suppression locale
        for fname in [f"bon_prepa_{order_num}.txt",
                      f"bon_anticipation_{order_num}.txt"]:
            fpath = os.path.join(WORK_DIR, fname)
            if os.path.exists(fpath):
                if upload_bon(drive_svc, fpath):
                    os.remove(fpath)

        # Nettoyer le PDF de travail (déjà dans le cache)
        pdf_work = os.path.join(WORK_DIR, pdf)
        if os.path.exists(pdf_work):
            os.remove(pdf_work)

        processed.add(pdf)

    # 5. Sauvegarder l'état dans Drive
    sauvegarder_traites(drive_svc, traites | processed)


if __name__ == "__main__":
    main()
