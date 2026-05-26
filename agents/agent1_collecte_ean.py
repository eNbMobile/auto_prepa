#!/usr/bin/env python3
"""
Agent 1 - Collecte des EAN depuis Google Drive (dossier BDC)
Structure attendue sur Drive : BDC/MM_AAAA/JJ_MM/BonDeCommande_XXXXXXX.pdf
Stockage : SQLite ~/visuels_ean.db
"""

import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

CREDENTIALS_FILE = os.path.expanduser("~/.credentials_drive.json")
TOKEN_FILE = os.path.expanduser("~/.drive_token.pkl")
DB_PATH = os.path.expanduser("~/visuels_ean.db")

BDC_FOLDER_ID = os.environ.get("BDC_FOLDER_ID", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))  # secondes entre chaque scan


# ──────────────────────────────────────────────────────────────────
# Auth Google Drive
# ──────────────────────────────────────────────────────────────────

def _build_drive_service():
    import pickle
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    # cache_discovery=False évite le warning "file_cache is unavailable"
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ──────────────────────────────────────────────────────────────────
# SQLite
# ──────────────────────────────────────────────────────────────────

def _init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS visuels_ean (
            id           INTEGER PRIMARY KEY,
            ean          TEXT NOT NULL,
            bdc_numero   TEXT,
            date_bdc     TEXT,
            drive_file_id TEXT,
            date_ajout   TEXT DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ean_fichier
            ON visuels_ean(ean, drive_file_id);
        CREATE TABLE IF NOT EXISTS fichiers_traites (
            drive_file_id TEXT PRIMARY KEY,
            traite_le     TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _deja_traite(conn, file_id):
    row = conn.execute(
        "SELECT 1 FROM fichiers_traites WHERE drive_file_id=?", (file_id,)
    ).fetchone()
    return row is not None


def _marquer_traite(conn, file_id):
    conn.execute(
        "INSERT OR IGNORE INTO fichiers_traites(drive_file_id) VALUES(?)", (file_id,)
    )
    conn.commit()


def _inserer_eans(conn, eans, bdc_numero, date_bdc, file_id):
    for ean in eans:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO visuels_ean(ean, bdc_numero, date_bdc, drive_file_id)"
                " VALUES(?,?,?,?)",
                (ean, bdc_numero, date_bdc, file_id),
            )
        except sqlite3.IntegrityError:
            pass
    conn.commit()


# ──────────────────────────────────────────────────────────────────
# Découverte du dossier BDC racine
# ──────────────────────────────────────────────────────────────────

def trouver_dossier_bdc(service, parent_id=None):
    """Recherche le dossier nommé 'BDC' sur Drive (ou dans parent_id)."""
    if parent_id:
        q = f"name='BDC' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    else:
        q = "name='BDC' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    result = service.files().list(
        q=q, fields="files(id,name,parents)", pageSize=10
    ).execute()
    files = result.get("files", [])
    if not files:
        return None
    if len(files) > 1:
        print(f"  Plusieurs dossiers BDC trouvés, utilisation du premier : {files[0]['id']}")
    return files[0]["id"]


def lister_sous_dossiers(service, parent_id):
    """Liste tous les sous-dossiers d'un dossier Drive."""
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    result = service.files().list(
        q=q, fields="files(id,name)", pageSize=200, orderBy="name"
    ).execute()
    return result.get("files", [])


def lister_pdfs_bdc(service, dossier_id):
    """Liste les PDFs nommés BonDeCommande_*.pdf dans un dossier."""
    q = (
        f"'{dossier_id}' in parents"
        " and mimeType='application/pdf'"
        " and name contains 'BonDeCommande'"
        " and trashed=false"
    )
    result = service.files().list(
        q=q, fields="files(id,name,createdTime)", pageSize=200
    ).execute()
    return result.get("files", [])


# ──────────────────────────────────────────────────────────────────
# Extraction EAN depuis PDF
# ──────────────────────────────────────────────────────────────────

def _extraire_numero_bdc(nom_fichier):
    m = re.search(r"BonDeCommande_(\w+)\.pdf", nom_fichier, re.IGNORECASE)
    return m.group(1) if m else nom_fichier


def _valider_ean13(code):
    """Vérifie la clé de contrôle EAN-13."""
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(
        int(d) * (1 if i % 2 == 0 else 3)
        for i, d in enumerate(code[:12])
    )
    checksum = (10 - (total % 10)) % 10
    return checksum == int(code[12])


def extraire_eans_pdf(chemin_pdf):
    """Extrait les codes EAN-13 valides depuis un fichier PDF."""
    try:
        import pdfplumber
    except ImportError:
        print("  pdfplumber non installé : pip install pdfplumber")
        return []

    eans = set()
    try:
        with pdfplumber.open(chemin_pdf) as pdf:
            for page in pdf.pages:
                texte = page.extract_text() or ""
                # EAN-13 : séquences de 13 chiffres (avec ou sans séparateurs)
                candidats = re.findall(r"\b\d{13}\b", texte)
                candidats += [
                    re.sub(r"[\s\-]", "", c)
                    for c in re.findall(r"\b\d{3}[\s\-]\d{4}[\s\-]\d{6}\b", texte)
                ]
                for c in candidats:
                    if _valider_ean13(c):
                        eans.add(c)
    except Exception as e:
        print(f"  Erreur lecture PDF : {e}")
    return list(eans)


# ──────────────────────────────────────────────────────────────────
# Téléchargement depuis Drive
# ──────────────────────────────────────────────────────────────────

def telecharger_fichier(service, file_id, dest):
    import io
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = dl.next_chunk()


# ──────────────────────────────────────────────────────────────────
# Scan principal
# ──────────────────────────────────────────────────────────────────

def scanner_bdc(service, conn, bdc_root_id):
    """Parcourt BDC/MM_AAAA/JJ_MM et traite chaque PDF BonDeCommande."""
    mois_dossiers = lister_sous_dossiers(service, bdc_root_id)
    total_eans = 0

    for mois in mois_dossiers:
        jours_dossiers = lister_sous_dossiers(service, mois["id"])
        for jour in jours_dossiers:
            pdfs = lister_pdfs_bdc(service, jour["id"])
            for pdf in pdfs:
                if _deja_traite(conn, pdf["id"]):
                    continue

                print(f"  Traitement : {mois['name']}/{jour['name']}/{pdf['name']}")
                bdc_numero = _extraire_numero_bdc(pdf["name"])
                date_bdc = f"{jour['name']}/{mois['name']}"

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    telecharger_fichier(service, pdf["id"], tmp_path)
                    eans = extraire_eans_pdf(tmp_path)
                    if eans:
                        _inserer_eans(conn, eans, bdc_numero, date_bdc, pdf["id"])
                        print(f"    → {len(eans)} EAN enregistré(s) : {', '.join(eans)}")
                        total_eans += len(eans)
                    else:
                        print(f"    → Aucun EAN trouvé")
                    _marquer_traite(conn, pdf["id"])
                except Exception as e:
                    print(f"    Erreur : {e}")
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    return total_eans


# ──────────────────────────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────────────────────────

def main():
    print(f"=== Agent 1 - Collecte EAN  ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

    service = _build_drive_service()

    bdc_root_id = BDC_FOLDER_ID
    if not bdc_root_id:
        print("BDC_FOLDER_ID non défini, recherche automatique du dossier BDC…")
        bdc_root_id = trouver_dossier_bdc(service)
        if not bdc_root_id:
            print("ERREUR : dossier BDC introuvable sur Drive.")
            print("Lancez le script avec : BDC_FOLDER_ID=<id> python3 agent1_collecte_ean.py")
            print("\nPour trouver l'ID, listez vos dossiers racine :")
            result = service.files().list(
                q="mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false",
                fields="files(id,name)",
                pageSize=50,
            ).execute()
            for f in result.get("files", []):
                print(f"  {f['name']:30s}  id={f['id']}")
            sys.exit(1)
        print(f"  Dossier BDC trouvé : {bdc_root_id}")

    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)

    try:
        while True:
            debut = time.time()
            try:
                n = scanner_bdc(service, conn, bdc_root_id)
                print(f"  Scan terminé : {n} nouveaux EAN  (prochain dans {POLL_INTERVAL}s)")
            except Exception as e:
                print(f"  Erreur scan : {e}")
            elapsed = time.time() - debut
            time.sleep(max(0, POLL_INTERVAL - elapsed))
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
