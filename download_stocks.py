#!/usr/bin/env python3
"""
download_stocks.py — Télécharge stock_j1.xlsx et stock_j.xlsx depuis le dossier Drive contrôle.

Utilisé par le workflow GitHub Actions controle_stocks.yml.
Variable d'environnement requise :
  GOOGLE_TOKEN_JSON — JSON du token OAuth2 (même secret que auto_prepa)

Attend deux fichiers nommés exactement dans le dossier DRIVE_CONTROLE_FOLDER_ID :
  stock_j1.xlsx   (stock J-1)
  stock_j.xlsx    (stock J)

Télécharge les fichiers dans le répertoire courant.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import date, timedelta

DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")
EXPECTED = ["j1.xlsx", "j.xlsx"]


def get_access_token(token):
    data = urllib.parse.urlencode({
        "client_id":     token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    ).read())
    return resp["access_token"]


def drive_list(access_token, folder_id):
    params = urllib.parse.urlencode({
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name)",
        "pageSize": "50",
    })
    url = f"https://www.googleapis.com/drive/v3/files?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    return json.loads(urllib.request.urlopen(req).read()).get("files", [])


def drive_download(access_token, file_id, dest):
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def charger_config(access_token):
    """Charge config.json depuis DRIVE_CONFIG_FOLDER_ID via l'API Drive REST."""
    if not DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : secret DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)
    files = drive_list(access_token, DRIVE_CONFIG_FOLDER_ID)
    index = {f["name"]: f["id"] for f in files}
    if "config.json" not in index:
        print("ERREUR : config.json introuvable dans le dossier Drive config.")
        sys.exit(1)
    url = f"https://www.googleapis.com/drive/v3/files/{index['config.json']}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    return json.loads(urllib.request.urlopen(req).read())


def main():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()

    if not token_json:
        print("ERREUR : variable GOOGLE_TOKEN_JSON manquante.")
        sys.exit(1)

    token  = json.loads(token_json)
    access = get_access_token(token)

    cfg       = charger_config(access)
    folder_id = cfg["drive_controle_folder_id"]

    files = drive_list(access, folder_id)
    index = {f["name"]: f["id"] for f in files}

    missing = [n for n in EXPECTED if n not in index]
    if missing:
        print(f"ERREUR : fichier(s) manquant(s) dans le dossier Drive : {missing}")
        print(f"Fichiers présents : {list(index.keys())}")
        sys.exit(1)

    for name in EXPECTED:
        print(f"Téléchargement {name} …", flush=True)
        drive_download(access, index[name], name)
        size = os.path.getsize(name)
        print(f"  → {name} ({size:,} octets)")

    print("Stocks téléchargés.")

    # Télécharger les fichiers pré-calculés de J-1 si disponibles
    work_dir   = os.environ.get("WORK_DIR", "v 4.0.0")
    dossier_j1 = (date.today() - timedelta(days=1)).strftime("%d_%m")
    os.makedirs(work_dir, exist_ok=True)

    theo_nom = f"theo_{dossier_j1}.csv"
    if theo_nom in index:
        dest = os.path.join(work_dir, theo_nom)
        print(f"Téléchargement {theo_nom} …", flush=True)
        drive_download(access, index[theo_nom], dest)
        print(f"  → {dest} ({os.path.getsize(dest):,} octets)")
    else:
        print(f"  {theo_nom} absent de Drive — le théorique sera recalculé depuis les BDC.")

    ventes_nom = f"ventes_{dossier_j1}.csv"
    if ventes_nom in index:
        dest = os.path.join(work_dir, ventes_nom)
        print(f"Téléchargement {ventes_nom} …", flush=True)
        drive_download(access, index[ventes_nom], dest)
        print(f"  → {dest} ({os.path.getsize(dest):,} octets)")


if __name__ == "__main__":
    main()
