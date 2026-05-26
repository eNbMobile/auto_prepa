#!/usr/bin/env python3
"""Upload les fichiers BDC traités vers Google Drive : GITHUB/BDC/MM_AAAA/JJ_MM/

auto_prepa.py stocke les fichiers dans BDC/JJ_MM/ (sous-répertoires nommés DD_MM)
et en archive la majorité directement via archiver_pdf_drive.  Ce script sert de
filet de sécurité : il remonte TOUS les fichiers présents (à plat ou en sous-dossier)
vers Drive, en ignorant ceux qui y sont déjà.
"""

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


def _collect_bdc_files(bdc_dir, default_date):
    """Retourne [(file_path, jj_mm, mm_aaaa)] en parcourant BDC/ et BDC/JJ_MM/.

    auto_prepa.py crée BDC/JJ_MM/BonDeCommande_X.pdf quand la date est trouvée
    dans le sujet de l'email, et BDC/BonDeCommande_X.pdf sinon.
    Les sous-dossiers nommés JJ_MM (ex. 26_05) fournissent directement la date.
    """
    default_jj_mm   = default_date.strftime("%d_%m")
    default_mm_aaaa = default_date.strftime("%m_%Y")
    results = []

    if not os.path.isdir(bdc_dir):
        return results

    for entry in sorted(os.listdir(bdc_dir)):
        full_path = os.path.join(bdc_dir, entry)

        if os.path.isfile(full_path):
            results.append((full_path, default_jj_mm, default_mm_aaaa))

        elif os.path.isdir(full_path):
            jj_mm = entry
            try:
                dd, mm = jj_mm.split("_")
                mm_aaaa = f"{int(mm):02d}_{default_date.year}"
            except (ValueError, AttributeError):
                mm_aaaa = default_mm_aaaa

            for fname in sorted(os.listdir(full_path)):
                fpath = os.path.join(full_path, fname)
                if os.path.isfile(fpath):
                    results.append((fpath, jj_mm, mm_aaaa))

    return results


def main():
    args = sys.argv[1:]
    date_str = args[args.index("--date") + 1] if "--date" in args else None

    if date_str:
        try:
            default_date = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            print(f"Format de date invalide : {date_str}  →  attendu JJ/MM/AAAA")
            sys.exit(1)
    else:
        default_date = datetime.today()

    items = _collect_bdc_files(_BDC_DIR, default_date)
    if not items:
        print("Aucun fichier BDC à uploader.")
        sys.exit(0)

    print(f"Upload BDC : {len(items)} fichier(s) trouvé(s) dans {_BDC_DIR}")

    access    = _access_token()
    github_id = _find_root_folder(access, "GITHUB")
    bdc_id    = _find_or_create_folder(access, "BDC", github_id)

    folder_cache = {}
    uploaded = skipped = 0

    for file_path, jj_mm, mm_aaaa in items:
        key = (mm_aaaa, jj_mm)
        if key not in folder_cache:
            month_id = _find_or_create_folder(access, mm_aaaa, bdc_id)
            day_id   = _find_or_create_folder(access, jj_mm,   month_id)
            folder_cache[key] = day_id
        day_id   = folder_cache[key]
        filename = os.path.basename(file_path)

        if _file_exists(access, filename, day_id):
            print(f"  → BDC/{mm_aaaa}/{jj_mm}/{filename} (déjà présent, ignoré)")
            skipped += 1
        else:
            _upload_file(access, file_path, day_id)
            print(f"  ✓ BDC/{mm_aaaa}/{jj_mm}/{filename}")
            uploaded += 1

    print(f"Terminé : {uploaded} uploadé(s), {skipped} ignoré(s).")


if __name__ == "__main__":
    main()
