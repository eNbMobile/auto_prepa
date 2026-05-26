#!/usr/bin/env python3
"""
Script d'initialisation (à exécuter UNE FOIS).
Récupère tous les EAN déjà téléchargés depuis enbmobile.nl/mobUDrive/visuels/
et les injecte dans DRIVE_CONFIG_FOLDER_ID/data/visuels_ean.json.

Usage :
    DRIVE_CONFIG_FOLDER_ID=<id> python3 agents/init_visuels_existants.py
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

VISUELS_URL = os.environ.get("VISUELS_URL", "http://enbmobile.nl/mobUDrive/visuels/")
DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")
CREDENTIALS_FILE = os.path.expanduser("~/.credentials_drive.json")
TOKEN_FILE = os.path.expanduser("~/.drive_token.pkl")


# ── EAN-13 validation ─────────────────────────────────────────────

def _valider_ean13(code):
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


# ── Récupération des EAN depuis le listing web ────────────────────

def scraper_eans(url):
    print(f"Chargement de {url} …")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")

    # Extraire tous les noms de fichiers depuis les liens <a href="...">
    noms = re.findall(r'href="([^"?#/]+)"', html)

    eans = []
    for nom in noms:
        # Supprimer l'extension
        base = re.sub(r'\.[a-zA-Z0-9]+$', '', nom).strip()
        if _valider_ean13(base):
            eans.append(base)

    # Dédoublonner en conservant l'ordre
    vu = set()
    uniques = []
    for e in eans:
        if e not in vu:
            vu.add(e)
            uniques.append(e)

    return uniques


# ── Auth Drive ────────────────────────────────────────────────────

def _build_service():
    import pickle
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if Path(TOKEN_FILE).exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE,
                ["https://www.googleapis.com/auth/drive"],
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── Lecture / écriture Drive ──────────────────────────────────────

def _trouver_ou_creer_dossier(service, parent_id, nom):
    q = (f"name='{nom}' and '{parent_id}' in parents"
         " and mimeType='application/vnd.google-apps.folder' and trashed=false")
    res = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if res:
        return res[0]["id"]
    f = service.files().create(body={
        "name": nom,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }, fields="id").execute()
    return f["id"]


def _lire_json_drive(service, folder_id, filename):
    import io
    from googleapiclient.http import MediaIoBaseDownload
    q = (f"name='{filename}' and '{folder_id}' in parents"
         " and trashed=false")
    files = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if not files:
        return None
    fh = io.BytesIO()
    dl = MediaIoBaseDownload(fh, service.files().get_media(fileId=files[0]["id"]))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return json.loads(fh.getvalue())


def _ecrire_json_drive(service, folder_id, filename, data):
    import io
    from googleapiclient.http import MediaIoBaseUpload
    contenu = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(contenu), mimetype="application/json")
    # Chercher fichier existant
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    existing = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if existing:
        service.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media, fields="id",
        ).execute()


# ── Point d'entrée ────────────────────────────────────────────────

def main():
    if not DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID non défini.")
        print("Usage : DRIVE_CONFIG_FOLDER_ID=<id> python3 agents/init_visuels_existants.py")
        sys.exit(1)

    # 1. Scraper les EAN existants
    eans = scraper_eans(VISUELS_URL)
    print(f"  {len(eans)} EAN valides trouvés sur le serveur")

    if not eans:
        print("Aucun EAN trouvé — vérifiez l'URL.")
        sys.exit(1)

    # 2. Connexion Drive
    service = _build_service()
    data_folder_id = _trouver_ou_creer_dossier(service, DRIVE_CONFIG_FOLDER_ID, "data")

    # 3. Charger l'état existant pour ne pas écraser les métadonnées BDC
    existant = _lire_json_drive(service, data_folder_id, "visuels_ean.json") or []
    eans_avec_meta = {e["ean"]: e for e in existant}

    # 4. Ajouter les EAN du serveur (sans métadonnées BDC — déjà téléchargés)
    for ean in eans:
        if ean not in eans_avec_meta:
            eans_avec_meta[ean] = {"ean": ean, "bdc_numero": None, "date_bdc": None, "drive_file_id": None}

    resultat = list(eans_avec_meta.values())
    _ecrire_json_drive(service, data_folder_id, "visuels_ean.json", resultat)
    print(f"  visuels_ean.json mis à jour : {len(resultat)} EAN au total")

    # 5. Marquer tous ces EAN comme déjà traités dans fichiers_traites pour agent2
    #    (on crée un fichier dédié visuels_deja_presents.json pour ne pas polluer
    #     le suivi des PDFs Drive)
    _ecrire_json_drive(service, data_folder_id, "visuels_deja_presents.json",
                       list(eans_avec_meta.keys()))
    print(f"  visuels_deja_presents.json créé ({len(eans_avec_meta)} entrées)")
    print("\nInitialisation terminée. L'agent 2 ignorera les EAN déjà présents.")


if __name__ == "__main__":
    main()
