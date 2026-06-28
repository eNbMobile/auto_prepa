#!/usr/bin/env python3
"""
Télécharge les visuels produits depuis coursesu.com et les uploade sur enbmobile.nl via FTP.

Les EAN à traiter sont lus depuis Drive (DRIVE_CONFIG_FOLDER_ID/data/visuels_ean.json).
Les EAN déjà présents sur le serveur sont listés dans visuels_deja_presents.json.

Variables d'environnement requises :
    GOOGLE_TOKEN_JSON       Token OAuth Google (même secret que les autres scripts)
    DRIVE_CONFIG_FOLDER_ID  ID du dossier config Drive
    FTP_HOST                Hôte FTP (ex: ftp.enbmobile.nl)
    FTP_USER                Identifiant FTP
    FTP_PASS                Mot de passe FTP

Variables optionnelles :
    FTP_DIR                 Répertoire distant (défaut: /mobUDrive/visuels)
    COURSESU_URL            URL de base coursesu (défaut: https://www.coursesu.com)
    BATCH_SIZE              Nombre d'EAN par exécution (défaut: 50)
    DELAY_DL                Délai entre téléchargements en secondes (défaut: 1.0)
"""

import ftplib
import io
import json
import os
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
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))
DELAY      = float(os.environ.get("DELAY_DL", "1.0"))

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


# ── Lecture / écriture Drive ──────────────────────────────────────

def _trouver_dossier(service, parent_id, nom):
    q = (f"name='{nom}' and '{parent_id}' in parents"
         " and mimeType='application/vnd.google-apps.folder' and trashed=false")
    files = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    return files[0]["id"] if files else None


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


def _ecrire_json_drive(service, folder_id, filename, data):
    from googleapiclient.http import MediaIoBaseUpload
    contenu = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(contenu), mimetype="application/json")
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    existing = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if existing:
        service.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media, fields="id",
        ).execute()


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


# ── Upload FTP ───────────────────────────────────────────────────

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
        # Créer le répertoire s'il n'existe pas
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
    """Retourne l'ensemble des noms de fichiers présents sur le FTP."""
    try:
        return set(ftp.nlst())
    except ftplib.error_temp:
        return set()


def uploader_ftp(ftp, nom_fichier, data):
    ftp.storbinary(f"STOR {nom_fichier}", io.BytesIO(data))


# ── Pipeline principal ────────────────────────────────────────────

def main():
    from datetime import datetime
    print(f"=== Téléchargement visuels ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

    if not DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)

    # 1. Connexion Drive
    print("Connexion Drive …")
    service = _get_drive_service()
    data_folder_id = _trouver_dossier(service, DRIVE_CONFIG_FOLDER_ID, "data")
    if not data_folder_id:
        print("ERREUR : dossier data/ introuvable sur Drive.")
        sys.exit(1)

    # 2. Charger la liste des EAN à télécharger
    print("Lecture visuels_ean.json …")
    tous_eans = _lire_json_drive(service, data_folder_id, "visuels_ean.json")
    if not tous_eans:
        print("visuels_ean.json vide ou introuvable.")
        sys.exit(0)
    print(f"  {len(tous_eans)} EAN au total")

    # 3. Connexion FTP + liste des fichiers déjà présents
    print(f"Connexion FTP {FTP_HOST}{FTP_DIR} …")
    ftp = _connect_ftp()
    presents_ftp = _lister_ftp(ftp)
    print(f"  {len(presents_ftp)} fichiers déjà présents sur le serveur")

    # EAN déjà couverts = ceux dont un fichier .jpg ou .png existe sur le FTP
    eans_presents = {
        re.sub(r'\.[a-zA-Z0-9]+$', '', nom)
        for nom in presents_ftp
    }

    import re as _re

    def _ean_present(ean):
        return ean in eans_presents

    # 4. Filtrer les EAN à traiter
    a_traiter = [item for item in tous_eans if not _ean_present(item["ean"])]
    if not a_traiter:
        print("Tous les visuels sont déjà présents sur le serveur.")
        ftp.quit()
        return

    batch = a_traiter[:BATCH_SIZE]
    print(f"\n{len(a_traiter)} EAN manquants — traitement de {len(batch)} (BATCH_SIZE={BATCH_SIZE})")

    # 5. Téléchargement + upload
    ok = absent = erreur = 0
    nouveaux_eans = []

    for item in batch:
        ean = item["ean"]
        data, ext = telecharger_visuel(ean)
        if data is None:
            print(f"  ✗ {ean} → introuvable sur coursesu")
            absent += 1
            time.sleep(DELAY)
            continue

        nom_fichier = f"{ean}{ext}"
        try:
            uploader_ftp(ftp, nom_fichier, data)
            print(f"  ✓ {ean} → {FTP_DIR}/{nom_fichier} ({len(data):,} octets)")
            nouveaux_eans.append(ean)
            ok += 1
        except Exception as e:
            print(f"  ✗ {ean} → erreur FTP : {e}")
            erreur += 1

        time.sleep(DELAY)

    ftp.quit()

    # 6. Mettre à jour visuels_deja_presents.json sur Drive
    if nouveaux_eans:
        deja = _lire_json_drive(service, data_folder_id, "visuels_deja_presents.json") or []
        deja_set = set(deja) | set(nouveaux_eans)
        _ecrire_json_drive(service, data_folder_id, "visuels_deja_presents.json",
                           sorted(deja_set))
        print(f"\nvisuels_deja_presents.json mis à jour ({len(deja_set)} EAN)")

    print(f"\n── Résultat ──────────────────────────")
    print(f"  Téléchargés et uploadés : {ok}")
    print(f"  Introuvables sur coursesu : {absent}")
    if erreur:
        print(f"  Erreurs FTP : {erreur}")
    if len(a_traiter) > BATCH_SIZE:
        print(f"  Restants pour le prochain passage : {len(a_traiter) - BATCH_SIZE}")


if __name__ == "__main__":
    import re
    main()
