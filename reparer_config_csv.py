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
concernees). Une premiere reconversion manuelle (export Google Sheets vers
CSV depuis l'interface web) a laisse les fichiers en fins de ligne CRLF et
a fait planter (SIGSEGV) le binaire prepa_drive_degrade, qui attend du CSV
Unix classique (LF) - d'ou la normalisation des fins de ligne ci-dessous en
plus de la reconversion de mimeType.

Ce script, pour chaque fichier de CONFIG_FILES :
- s'il est encore un Google Sheet natif, l'exporte en CSV puis met l'ancien
  Sheet a la corbeille (jamais de suppression definitive) ;
- normalise le contenu en LF (CRLF/CR -> LF) et retire un eventuel BOM UTF-8,
  et ne reecrit sur Drive que si le contenu a effectivement change.
Idempotent : ignore les fichiers deja au format CSV plat en LF.
"""
import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

import auto_prepa as ap

MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
BOM_UTF8 = b"\xef\xbb\xbf"


def _normaliser(contenu: bytes) -> bytes:
    if contenu.startswith(BOM_UTF8):
        contenu = contenu[len(BOM_UTF8):]
    return contenu.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _televerser(drive_svc, contenu: bytes, *, file_id=None, filename=None, parent_id=None):
    media = MediaIoBaseUpload(io.BytesIO(contenu), mimetype="text/csv", resumable=True)
    if file_id:
        request = drive_svc.files().update(fileId=file_id, media_body=media)
    else:
        request = drive_svc.files().create(
            body={"name": filename, "parents": [parent_id]}, media_body=media, fields="id")
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response


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

    if mime_type == MIME_GOOGLE_SHEET:
        print(f"  {filename} : converti en Google Sheet, export CSV...")
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(
            buf, drive_svc.files().export_media(fileId=file_id, mimeType="text/csv"))
        done = False
        while not done:
            _, done = dl.next_chunk()
        contenu = _normaliser(buf.getvalue())
        _televerser(drive_svc, contenu, filename=filename, parent_id=ap.DRIVE_CONFIG_FOLDER_ID)
        drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
        print(f"  {filename} : reconverti en CSV plat LF ({len(contenu)} octets), ancien Sheet mis a la corbeille.")
        return

    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    contenu_orig = buf.getvalue()
    contenu = _normaliser(contenu_orig)
    if contenu == contenu_orig:
        print(f"  {filename} : deja au format CSV plat LF, rien a faire.")
        return

    _televerser(drive_svc, contenu, file_id=file_id)
    print(f"  {filename} : fins de ligne CRLF/BOM normalisees en LF "
          f"({len(contenu_orig)} -> {len(contenu)} octets).")


def main():
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    ap._charger_config(drive_svc)
    for filename in ap.CONFIG_FILES:
        _reparer_fichier(drive_svc, filename)


if __name__ == "__main__":
    main()
