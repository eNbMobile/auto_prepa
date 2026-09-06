#!/usr/bin/env python3
"""
Script de securite/rattrapage a usage unique (et reutilisable en cas de
recidive) : les fichiers de config CSV du dossier Drive config (CONFIG_FILES)
peuvent se retrouver convertis en Google Sheets natifs (par exemple apres une
edition directe dans l'interface Sheets), ce qui casse leur telechargement
binaire (files.get_media renvoie une erreur 403 "Only files with binary
content can be downloaded") et bloque tout le pipeline auto_prepa.

Incident du 05/09/2026 : gencod_adresses.csv et gencod_nomenclatures.csv ont
ete convertis en Google Sheets vers 13h46, et plus aucune commande n'a ete
generee pendant ~20h alors que les emails de confirmation continuaient
d'arriver (cf. rattraper_commandes.py pour le rattrapage des commandes
concernees).

Ce script detecte ce cas pour chaque fichier de CONFIG_FILES et le
reconvertit en CSV plat : export du contenu au format CSV, upload d'un
nouveau fichier CSV du meme nom au meme endroit, et mise a la corbeille de
l'ancien Google Sheet (jamais de suppression definitive). Idempotent :
ignore les fichiers deja au format CSV.
"""
import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

import auto_prepa as ap

MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"


def _reparer_fichier(drive_svc, filename):
    res = drive_svc.files().list(
        q=f"name='{filename}' and '{ap.DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
        fields="files(id,mimeType)",
    ).execute()
    files = res.get("files", [])
    if not files:
        print(f"  {filename} : introuvable sur Drive, ignore.")
        return
    file_id, mime_type = files[0]["id"], files[0]["mimeType"]
    if mime_type != MIME_GOOGLE_SHEET:
        print(f"  {filename} : deja au format CSV ({mime_type}), rien a faire.")
        return

    print(f"  {filename} : converti en Google Sheet, reparation...")
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(
        buf, drive_svc.files().export_media(fileId=file_id, mimeType="text/csv"))
    done = False
    while not done:
        _, done = dl.next_chunk()
    contenu = buf.getvalue()

    media = MediaIoBaseUpload(io.BytesIO(contenu), mimetype="text/csv", resumable=False)
    drive_svc.files().create(
        body={"name": filename, "parents": [ap.DRIVE_CONFIG_FOLDER_ID]},
        media_body=media, fields="id",
    ).execute()
    drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
    print(f"  {filename} : reconverti en CSV plat ({len(contenu)} octets), ancien Sheet mis a la corbeille.")


def main():
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    ap._charger_config(drive_svc)
    for filename in ap.CONFIG_FILES:
        _reparer_fichier(drive_svc, filename)


if __name__ == "__main__":
    main()
