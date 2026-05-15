#!/usr/bin/env python3
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from controle_stocks import _get_drive_service

LOCAL_FILE = os.path.join(_HERE, "gmail_filters_local.json")

def main():
    if not os.path.exists(LOCAL_FILE):
        print(f"ERREUR : {LOCAL_FILE} introuvable.")
        print("  Créez ce fichier avec le contenu des filtres Gmail (voir gmail_filters_local.json.example).")
        sys.exit(1)

    with open(LOCAL_FILE, encoding="utf-8") as f:
        filters = json.load(f)

    config_folder_id = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "").strip()
    if not config_folder_id:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID non défini.")
        print("  Usage : DRIVE_CONFIG_FOLDER_ID=<id> python3 setup_gmail_filters.py")
        sys.exit(1)

    svc = _get_drive_service()
    if not svc:
        print("ERREUR : service Drive indisponible.")
        sys.exit(1)

    from googleapiclient.http import MediaFileUpload
    import tempfile

    content = json.dumps(filters, ensure_ascii=False, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        existing = svc.files().list(
            q=f"'{config_folder_id}' in parents and name='gmail_filters.json' and trashed=false",
            fields="files(id)",
        ).execute().get("files", [])

        media = MediaFileUpload(tmp_path, mimetype="application/json")
        if existing:
            svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            print("gmail_filters.json mis à jour sur Drive.")
        else:
            svc.files().create(
                body={"name": "gmail_filters.json", "parents": [config_folder_id]},
                media_body=media, fields="id",
            ).execute()
            print("gmail_filters.json créé sur Drive.")
    finally:
        os.unlink(tmp_path)

if __name__ == "__main__":
    main()
