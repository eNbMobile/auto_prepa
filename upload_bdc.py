#!/usr/bin/env python3
"""Upload les fichiers BDC traités vers Google Drive : GITHUB/BDC/MM_AAAA/JJ_MM/"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

_TOKEN_FILE = os.path.expanduser("~/.auto_prepa_token.json")
_BDC_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BDC")


def _access_token():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if not token_json and os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            token_json = f.read()
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


def _drive_post(access, url, body, content_type="application/json"):
    data = body if isinstance(body, bytes) else body.encode()
    req  = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access}", "Content-Type": content_type},
        method="POST",
        data=data,
    )
    return json.loads(urllib.request.urlopen(req).read())


def _find_or_create_folder(access, name, parent_id):
    q = urllib.parse.quote(
        f"name='{name}' and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    files = _drive_get(access,
        f"https://www.googleapis.com/drive/v3/files?q={q}&fields=files(id)")["files"]
    if files:
        return files[0]["id"]
    resp = _drive_post(access,
        "https://www.googleapis.com/drive/v3/files",
        json.dumps({"name": name, "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id]}))
    print(f"  Dossier créé : {name}")
    return resp["id"]


def _find_root_folder(access, name):
    q = urllib.parse.quote(
        f"name='{name}' and 'root' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    files = _drive_get(access,
        f"https://www.googleapis.com/drive/v3/files?q={q}&fields=files(id)")["files"]
    if not files:
        print(f"ERREUR : dossier '{name}' introuvable à la racine de Drive.")
        sys.exit(1)
    return files[0]["id"]


def _file_exists(access, name, parent_id):
    q = urllib.parse.quote(
        f"name='{name}' and '{parent_id}' in parents and trashed=false"
    )
    return bool(_drive_get(access,
        f"https://www.googleapis.com/drive/v3/files?q={q}&fields=files(id)")["files"])


def _mime(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "pdf":  "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls":  "application/vnd.ms-excel",
        "csv":  "text/csv",
        "txt":  "text/plain",
    }.get(ext, "application/octet-stream")


def _upload_file(access, file_path, parent_id):
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        content = f.read()
    boundary = "bdc_upload_boundary"
    metadata = json.dumps({"name": filename, "parents": [parent_id]})
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata}\r\n"
        f"--{boundary}\r\nContent-Type: {_mime(filename)}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--".encode()
    _drive_post(access,
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=multipart&fields=id",
        body,
        content_type=f"multipart/related; boundary={boundary}")


def main():
    args = sys.argv[1:]
    date_str = args[args.index("--date") + 1] if "--date" in args else None

    if date_str:
        try:
            date = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            print(f"Format de date invalide : {date_str}  →  attendu JJ/MM/AAAA")
            sys.exit(1)
    else:
        date = datetime.today()

    mm_aaaa = date.strftime("%m_%Y")
    jj_mm   = date.strftime("%d_%m")

    if not os.path.isdir(_BDC_DIR):
        print(f"Dossier BDC introuvable ({_BDC_DIR}) — rien à uploader.")
        sys.exit(0)

    bdc_files = sorted(
        f for f in os.listdir(_BDC_DIR)
        if os.path.isfile(os.path.join(_BDC_DIR, f))
    )
    if not bdc_files:
        print("Aucun fichier BDC à uploader.")
        sys.exit(0)

    print(f"Upload BDC → GITHUB/BDC/{mm_aaaa}/{jj_mm}/  ({len(bdc_files)} fichier(s))")

    access   = _access_token()
    github_id = _find_root_folder(access, "GITHUB")
    bdc_id    = _find_or_create_folder(access, "BDC",   github_id)
    month_id  = _find_or_create_folder(access, mm_aaaa, bdc_id)
    day_id    = _find_or_create_folder(access, jj_mm,   month_id)

    uploaded = skipped = 0
    for filename in bdc_files:
        if _file_exists(access, filename, day_id):
            print(f"  → {filename} (déjà présent, ignoré)")
            skipped += 1
        else:
            _upload_file(access, os.path.join(_BDC_DIR, filename), day_id)
            print(f"  ✓ {filename}")
            uploaded += 1

    print(f"Terminé : {uploaded} uploadé(s), {skipped} ignoré(s).")


if __name__ == "__main__":
    main()
