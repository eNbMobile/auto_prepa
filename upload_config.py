#!/usr/bin/env python3
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from controle_stocks import _get_drive_service

def main():
    config_folder_id = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "").strip()
    if not config_folder_id:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID non défini.")
        print("  Usage : DRIVE_CONFIG_FOLDER_ID=<id> python3 upload_config.py <fichier>")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("ERREUR : chemin du fichier manquant.")
        print("  Usage : python3 upload_config.py <fichier>")
        sys.exit(1)

    local_path = sys.argv[1]
    if not os.path.exists(local_path):
        print(f"ERREUR : fichier introuvable : {local_path}")
        sys.exit(1)

    nom = os.path.basename(local_path)
    svc = _get_drive_service()
    if not svc:
        print("ERREUR : service Drive indisponible.")
        sys.exit(1)

    from googleapiclient.http import MediaFileUpload

    existing = svc.files().list(
        q=f"'{config_folder_id}' in parents and name='{nom}' and trashed=false",
        fields="files(id)",
    ).execute().get("files", [])

    ext = os.path.splitext(nom)[1].lower()
    mime = {
        ".csv":  "text/csv",
        ".json": "application/json",
        ".txt":  "text/plain",
    }.get(ext, "application/octet-stream")

    media = MediaFileUpload(local_path, mimetype=mime)
    if existing:
        svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
        print(f"Drive config/{nom} — mis à jour.")
    else:
        svc.files().create(
            body={"name": nom, "parents": [config_folder_id]},
            media_body=media,
            fields="id",
        ).execute()
        print(f"Drive config/{nom} — créé.")

if __name__ == "__main__":
    main()
