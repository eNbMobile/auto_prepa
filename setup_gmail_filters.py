#!/usr/bin/env python3
"""
setup_gmail_filters.py — Upload gmail_filters.json vers le dossier config Drive.

Crée ou écrase le fichier gmail_filters.json dans le dossier de config Drive.
À lancer UNE SEULE FOIS après avoir adapté les filtres ci-dessous.

Usage :
  python3 setup_gmail_filters.py
"""

import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from controle_stocks import (
    TOKEN_FILE, WORK_DIR,
    _charger_config, _get_drive_service,
    telecharger_config_depuis_drive,
)
import controle_stocks

# ── Adaptez ces filtres Gmail à votre convenance ────────────────────────────
FILTERS = [
    'from:no-reply@systeme-u.fr subject:"Confirmation commande" -label:BDC_Conf_Traites',
    'subject:"Modification par le client de la commande" -label:BDC_Modif_Traites',
    'subject:"Alerte annulation" -label:BDC_Modif_Traites',
]
# ────────────────────────────────────────────────────────────────────────────


def main():
    _charger_config()

    svc = _get_drive_service()
    if not svc:
        print("ERREUR : service Drive indisponible.")
        sys.exit(1)

    config_folder_id = controle_stocks.DRIVE_CONFIG_FOLDER_ID
    if not config_folder_id:
        print("ERREUR : DRIVE_CONFIG_FOLDER_ID non configuré.")
        sys.exit(1)

    from googleapiclient.http import MediaFileUpload

    content = json.dumps(FILTERS, ensure_ascii=False, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        existing = svc.files().list(
            q=(f"'{config_folder_id}' in parents and name='gmail_filters.json' and trashed=false"),
            fields="files(id)",
        ).execute().get("files", [])

        media = MediaFileUpload(tmp_path, mimetype="application/json")
        if existing:
            svc.files().update(
                fileId=existing[0]["id"],
                media_body=media,
            ).execute()
            print("gmail_filters.json mis à jour sur Drive.")
        else:
            svc.files().create(
                body={"name": "gmail_filters.json", "parents": [config_folder_id]},
                media_body=media,
                fields="id",
            ).execute()
            print("gmail_filters.json créé sur Drive.")
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
