#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

_HERE          = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR   = "scripts"
_TOKEN_FILE    = os.path.expanduser("~/.auto_prepa_token.json")

def _access_token():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if not token_json:
        print("ERREUR : GOOGLE_TOKEN_JSON manquant.")
        sys.exit(1)
    token = json.loads(token_json)
    data = urllib.parse.urlencode({
        "client_id":     token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    ).read())
    token["access_token"] = resp["access_token"]
    with open(_TOKEN_FILE, "w") as f:
        json.dump(token, f)
    return resp["access_token"]


def _drive_get(access, url):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
    ).read())


def _drive_download(access, file_id):
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
    ).read()


def main():
    if len(sys.argv) < 2:
        print("Usage : python3 bootstrap.py <script.py> [args...]")
        sys.exit(1)

    target = sys.argv[1]
    args   = sys.argv[2:]

    config_folder_id = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "").strip()
    if not config_folder_id:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)

    access = _access_token()

    q = urllib.parse.quote(
        f"name='{_SCRIPTS_DIR}' and '{config_folder_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    folders = _drive_get(access,
        f"https://www.googleapis.com/drive/v3/files?q={q}&fields=files(id)")["files"]
    if not folders:
        print(f"ERREUR : dossier '{_SCRIPTS_DIR}/' introuvable sur Drive.")
        sys.exit(1)
    scripts_id = folders[0]["id"]

    q2 = urllib.parse.quote(f"'{scripts_id}' in parents and trashed=false")
    order = urllib.parse.quote("modifiedTime desc")
    all_files = _drive_get(access,
        f"https://www.googleapis.com/drive/v3/files?q={q2}"
        f"&fields=files(id,name,modifiedTime)&pageSize=50&orderBy={order}")["files"]

    # Keep only the newest version of each script name
    seen, files = set(), []
    for f in all_files:
        if f["name"] not in seen:
            seen.add(f["name"])
            files.append(f)

    print(f"Bootstrap : {len(files)} script(s) depuis Drive {_SCRIPTS_DIR}/ ({len(all_files)} fichier(s) total)")
    for f in files:
        content = _drive_download(access, f["id"])
        dest = os.path.join(_HERE, f["name"])
        with open(dest, "wb") as fp:
            fp.write(content)
        print(f"  ✓ {f['name']} ({f.get('modifiedTime', '?')})")

    target_path = os.path.join(_HERE, target)
    if not os.path.exists(target_path):
        print(f"ERREUR : {target} absent du dossier scripts/ sur Drive.")
        sys.exit(1)

    result = subprocess.run([sys.executable, target_path] + args)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
