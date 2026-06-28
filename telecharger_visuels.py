#!/usr/bin/env python3
"""
Télécharge les visuels produits depuis coursesu.com et les uploade sur enbmobile.nl via FTP.

Les EAN à traiter sont lus depuis Drive (DRIVE_CONFIG_FOLDER_ID/visuels_ean_liste.json)
sous forme d'une liste simple de strings ["ean1", "ean2", ...].
Les EAN déjà présents sur le serveur FTP sont automatiquement ignorés.

Variables d'environnement requises :
    GOOGLE_TOKEN_JSON       Token OAuth Google (même secret que les autres scripts)
    DRIVE_CONFIG_FOLDER_ID  ID du dossier Drive contenant visuels_ean_liste.json
    FTP_HOST                Hôte FTP (ex: ftp.enbmobile.nl)
    FTP_USER                Identifiant FTP
    FTP_PASS                Mot de passe FTP

Variables optionnelles :
    FTP_DIR                 Répertoire distant (défaut: /mobUDrive/visuels)
    COURSESU_URL            URL de base coursesu (défaut: https://www.coursesu.com)
    BATCH_SIZE              Nombre d'EAN par exécution (défaut: 100)
    DELAY_DL                Délai entre téléchargements en secondes (défaut: 0.8)
"""

import ftplib
import io
import json
import os
import re
import sys
import time
import urllib.request

DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")
TOKEN_FILE = os.path.expanduser("~/.auto_prepa_token.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]

FTP_HOST = os.environ.get("FTP_HOST", "")
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
FTP_DIR  = os.environ.get("FTP_DIR", "/mobUDrive/visuels")

BASE_URL   = os.environ.get("COURSESU_URL", "https://www.coursesu.com")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))
DELAY      = float(os.environ.get("DELAY_DL", "0.8"))

_PATTERNS = [
    "/media/catalog/product/{e0}/{e1}/{ean}.jpg",
    "/media/catalog/product/{e0}/{e1}/{ean}.png",
    "/media/catalog/product/{e0}/{e1}/{ean}_1.jpg",
    "/img/produits/{ean}.jpg",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Auth Drive ────────────────────────────────────────────────────

def _get_drive_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

    if not os.path.exists(TOKEN_FILE):
        print("ERREUR : GOOGLE_TOKEN_JSON manquant.")
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── Lecture Drive ─────────────────────────────────────────────────

def _lire_json_drive(service, folder_id, filename):
    from googleapiclient.http import MediaIoBaseDownload
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    files = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if not files:
        return None
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, service.files().get_media(fileId=files[0]["id"]))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return json.loads(buf.getvalue())


def charger_eans(service):
    """Charge visuels_ean_liste.json depuis Drive → liste de strings EAN."""
    if not DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)
    data = _lire_json_drive(service, DRIVE_CONFIG_FOLDER_ID, "visuels_ean_liste.json")
    if data is None:
        print("ERREUR : visuels_ean_liste.json introuvable dans le dossier Drive.")
        sys.exit(1)
    if not isinstance(data, list):
        print("ERREUR : visuels_ean_liste.json doit être une liste de strings.")
        sys.exit(1)
    return data  # ["ean1", "ean2", ...]


# ── Téléchargement depuis coursesu.com ───────────────────────────

def telecharger_visuel(ean):
    """Retourne (data_bytes, extension) ou (None, None) si introuvable."""
    e0, e1 = ean[0], ean[1]
    for pattern in _PATTERNS:
        url = BASE_URL.rstrip("/") + pattern.format(ean=ean, e0=e0, e1=e1)
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) > 500:
                        ct = resp.headers.get("Content-Type", "")
                        ext = ".jpg" if "jpeg" in ct.lower() or url.endswith(".jpg") else ".png"
                        return data, ext
        except Exception:
            continue
    return None, None


# ── FTP ──────────────────────────────────────────────────────────

def _connect_ftp():
    if not FTP_HOST or not FTP_USER or not FTP_PASS:
        print("ERREUR : FTP_HOST / FTP_USER / FTP_PASS manquants.")
        sys.exit(1)
    ftp = ftplib.FTP(FTP_HOST, timeout=30)
    ftp.login(FTP_USER, FTP_PASS)
    ftp.set_pasv(True)
    try:
        ftp.cwd(FTP_DIR)
    except ftplib.error_perm:
        parts = [p for p in FTP_DIR.split("/") if p]
        ftp.cwd("/")
        for part in parts:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part)
                ftp.cwd(part)
    return ftp


def _lister_ftp(ftp):
    try:
        return set(ftp.nlst())
    except ftplib.error_temp:
        return set()


# ── Pipeline principal ────────────────────────────────────────────

def main():
    from datetime import datetime
    print(f"=== Téléchargement visuels ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

    # 1. Charger la liste EAN depuis Drive
    print("Connexion Drive …")
    service = _get_drive_service()
    tous_eans = charger_eans(service)
    print(f"  {len(tous_eans)} EAN chargés depuis visuels_ean_liste.json")

    # 2. Connexion FTP + liste des fichiers déjà présents
    print(f"Connexion FTP {FTP_HOST}{FTP_DIR} …")
    ftp = _connect_ftp()
    presents_ftp = _lister_ftp(ftp)
    print(f"  {len(presents_ftp)} fichiers déjà présents sur le serveur")

    eans_presents = {re.sub(r'\.[a-zA-Z0-9]+$', '', nom) for nom in presents_ftp}

    # 3. Filtrer les EAN manquants
    a_traiter = [ean for ean in tous_eans if ean not in eans_presents]
    if not a_traiter:
        print("Tous les visuels sont déjà présents sur le serveur.")
        ftp.quit()
        return

    batch = a_traiter[:BATCH_SIZE]
    print(f"\n{len(a_traiter)} EAN manquants — traitement de {len(batch)} (BATCH_SIZE={BATCH_SIZE})")

    # 4. Téléchargement + upload FTP
    ok = absent = erreur = 0

    for ean in batch:
        data, ext = telecharger_visuel(ean)
        if data is None:
            print(f"  ✗ {ean} → introuvable sur coursesu")
            absent += 1
            time.sleep(DELAY)
            continue

        nom_fichier = f"{ean}{ext}"
        try:
            ftp.storbinary(f"STOR {nom_fichier}", io.BytesIO(data))
            print(f"  ✓ {ean} → {nom_fichier} ({len(data):,} octets)")
            ok += 1
        except Exception as e:
            print(f"  ✗ {ean} → erreur FTP : {e}")
            erreur += 1

        time.sleep(DELAY)

    ftp.quit()

    print(f"\n── Résultat ──────────────────────────")
    print(f"  Téléchargés et uploadés : {ok}")
    print(f"  Introuvables sur coursesu : {absent}")
    if erreur:
        print(f"  Erreurs FTP : {erreur}")
    if len(a_traiter) > BATCH_SIZE:
        print(f"  Restants pour le prochain passage : {len(a_traiter) - BATCH_SIZE}")


if __name__ == "__main__":
    main()
