#!/usr/bin/env python3

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import date, timedelta

DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")

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
    args = sys.argv[1:]

    nb_jours = 1
    if "--jours" in args:
        i = args.index("--jours")
        if i + 1 < len(args):
            nb_jours = max(1, int(args[i + 1]))

    # Dernier jour de ventes : hier par défaut, samedi si lundi, ou --date override
    delta = timedelta(days=2) if date.today().weekday() == 0 else timedelta(days=1)
    date_j1 = date.today() - delta
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                date_j1 = date(int(a), int(m), int(j))
            except Exception:
                pass

    date_debut = date_j1 - timedelta(days=nb_jours - 1)

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

    if "j.xlsx" not in index:
        print(f"ERREUR : j.xlsx manquant dans le dossier Drive.")
        print(f"Fichiers présents : {list(index.keys())}")
        sys.exit(1)

    print("Téléchargement j.xlsx …", flush=True)
    drive_download(access, index["j.xlsx"], "j.xlsx")
    print(f"  → j.xlsx ({os.path.getsize('j.xlsx'):,} octets)")

    # Stock de départ : j1.xlsx déposé manuellement sur Drive, ou archive en fallback
    if "j1.xlsx" in index:
        print("Téléchargement j1.xlsx …", flush=True)
        drive_download(access, index["j1.xlsx"], "j1.xlsx")
        print(f"  → j1.xlsx ({os.path.getsize('j1.xlsx'):,} octets)")
    else:
        nom_j1 = f"stock_{date_debut.strftime('%d_%m_%Y')}_j.xlsx"
        file_id_j1 = find_in_archive(access, folder_id, "stocks", nom_j1)
        if file_id_j1:
            print(f"Téléchargement {nom_j1} (archive) → j1.xlsx …", flush=True)
            drive_download(access, file_id_j1, "j1.xlsx")
            print(f"  → j1.xlsx ({os.path.getsize('j1.xlsx'):,} octets)")
        else:
            print("  j1.xlsx absent du dossier Drive — stock de départ non disponible.")

    work_dir = os.environ.get("WORK_DIR", "v 4.0.0")
    os.makedirs(work_dir, exist_ok=True)

    # Ventes pour chaque jour de la période
    for i in range(nb_jours):
        d = date_debut + timedelta(days=i)
        nom_v = f"ventes_{d.strftime('%d_%m')}.csv"
        dest = os.path.join(work_dir, nom_v)
        if os.path.exists(dest):
            print(f"  {nom_v} (existant)", flush=True)
            continue
        file_id = index.get(nom_v) or find_in_archive(access, folder_id, "ventes", nom_v)
        if file_id:
            print(f"Téléchargement {nom_v} …", flush=True)
            drive_download(access, file_id, dest)
            print(f"  → {dest} ({os.path.getsize(dest):,} octets)")
        else:
            print(f"  {nom_v} absent — ventes du {d.strftime('%d/%m/%Y')} non trouvées.")

if __name__ == "__main__":
    main()
