#!/usr/bin/env python3

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

def find_in_archive(access_token, controle_folder_id, subfolder, filename):
    """Cherche filename dans controle_folder_id/Archives/{subfolder}/. Retourne l'ID ou None."""
    try:
        def _find_folder(parent_id, name):
            params = urllib.parse.urlencode({
                "q": (f"name='{name}' and '{parent_id}' in parents "
                      f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
                "fields": "files(id)", "pageSize": "10",
            })
            url = f"https://www.googleapis.com/drive/v3/files?{params}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            files = json.loads(urllib.request.urlopen(req).read()).get("files", [])
            return files[0]["id"] if files else None

        archives_id = _find_folder(controle_folder_id, "Archives")
        if not archives_id:
            return None
        sub_id = _find_folder(archives_id, subfolder)
        if not sub_id:
            return None
        files = drive_list(access_token, sub_id)
        index = {f["name"]: f["id"] for f in files}
        return index.get(filename)
    except Exception:
        return None

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

    # Lundi : pas de capture dimanche → j1.xlsx absent est acceptable.
    # controle_stocks.py le requiert en argument mais n'utilise pas ses données
    # quand theo_JJMM.csv est disponible. On le remplace par j.xlsx.
    lundi_sans_j1 = date.today().weekday() == 0 and "j1.xlsx" not in index
    required = [n for n in EXPECTED if not (n == "j1.xlsx" and lundi_sans_j1)]

    missing = [n for n in required if n not in index]
    if missing:
        print(f"ERREUR : fichier(s) manquant(s) dans le dossier Drive : {missing}")
        print(f"Fichiers présents : {list(index.keys())}")
        sys.exit(1)

    for name in required:
        print(f"Téléchargement {name} …", flush=True)
        drive_download(access, index[name], name)
        size = os.path.getsize(name)
        print(f"  → {name} ({size:,} octets)")

    if lundi_sans_j1:
        import shutil
        shutil.copy("j.xlsx", "j1.xlsx")
        print("Lundi : j1.xlsx absent → j.xlsx copié comme j1.xlsx (données non utilisées).")

    print("Stocks téléchargés.")

    work_dir = os.environ.get("WORK_DIR", "v 4.0.0")
    # Lundi : pas de stock théo/ventes du dimanche → on remonte au samedi (J-2)
    delta = timedelta(days=2) if date.today().weekday() == 0 else timedelta(days=1)
    dossier_j1 = (date.today() - delta).strftime("%d_%m")
    os.makedirs(work_dir, exist_ok=True)

    for nom, subfolder in [(f"theo_{dossier_j1}.csv", "théo"),
                            (f"ventes_{dossier_j1}.csv", "ventes")]:
        file_id = index.get(nom) or find_in_archive(access, folder_id, subfolder, nom)
        if file_id:
            dest = os.path.join(work_dir, nom)
            print(f"Téléchargement {nom} …", flush=True)
            drive_download(access, file_id, dest)
            print(f"  → {dest} ({os.path.getsize(dest):,} octets)")
        elif nom.startswith("theo_"):
            print(f"  {nom} absent — le théorique sera recalculé depuis les BDC.")

if __name__ == "__main__":
    main()
