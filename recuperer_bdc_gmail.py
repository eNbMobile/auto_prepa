#!/usr/bin/env python3
"""
recuperer_bdc_gmail.py — Récupère les BDC depuis Gmail (label BDC_Traite).

Pour chaque mail du label :
  - Extrait la date et le numéro de commande du sujet
    Format : "Confirmation commande DD/MM/YYYY à HH:MM -- ... - N° cde:XXXXXXXX"
  - Télécharge la pièce jointe PDF
  - Uploade dans Drive BDC/DD_MM/BonDeCommande_XXXXXXXX.pdf

Usage :
  python3 recuperer_bdc_gmail.py
"""

import base64
import os
import re
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import controle_stocks
from controle_stocks import (
    TOKEN_FILE, WORK_DIR,
    _charger_config, _get_drive_service, _get_or_create_subfolder_drive,
    telecharger_config_depuis_drive,
)

GMAIL2_TOKEN_FILE   = os.path.expanduser("~/.auto_prepa_gmail2_token.json")
CREDENTIALS_FILE    = os.path.expanduser("~/.auto_prepa_credentials.json")
GMAIL_SCOPES        = ["https://www.googleapis.com/auth/gmail.readonly"]
LABEL_BDC           = "BDC_Traite"

_RE_DATE   = re.compile(r'(\d{2})/(\d{2})/\d{4}')
_RE_NUMCDE = re.compile(r'N°\s*cde[:\s]*(\d+)', re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────
# Auth Gmail (compte secondaire)
# ─────────────────────────────────────────────────────────────────

def _get_gmail2_service():
    """Retourne le service Gmail API pour le compte secondaire."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        if not os.path.exists(GMAIL2_TOKEN_FILE):
            print("ERREUR : token Gmail secondaire absent.")
            print(f"  → Lancez auth_gmail.py pour générer {GMAIL2_TOKEN_FILE}")
            return None

        creds = Credentials.from_authorized_user_file(GMAIL2_TOKEN_FILE, GMAIL_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(GMAIL2_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        if not creds.valid:
            print("ERREUR : token Gmail secondaire invalide.")
            return None
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        print(f"ERREUR Gmail : {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Helpers Gmail
# ─────────────────────────────────────────────────────────────────

def _lister_messages_label(gmail_svc):
    """Retourne tous les message IDs du label BDC_Traite."""
    labels_resp = gmail_svc.users().labels().list(userId="me").execute()
    label_id = None
    for lbl in labels_resp.get("labels", []):
        if lbl["name"] == LABEL_BDC:
            label_id = lbl["id"]
            break
    if not label_id:
        print(f"  Label '{LABEL_BDC}' introuvable dans ce compte Gmail.")
        return []

    messages = []
    page_token = None
    while True:
        params = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        resp = gmail_svc.users().messages().list(**params).execute()
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return messages


def _extraire_infos_sujet(sujet):
    """Retourne (num_commande, dossier_jj_mm) depuis le sujet du mail, ou (None, None)."""
    m_num  = _RE_NUMCDE.search(sujet)
    m_date = _RE_DATE.search(sujet)
    if not m_num or not m_date:
        return None, None
    return m_num.group(1), f"{m_date.group(1)}_{m_date.group(2)}"


def _collecter_pdf_parts(payload):
    """Retourne la liste des parts PDF (récursif)."""
    parts = []
    for part in payload.get("parts", []):
        mt = part.get("mimeType", "")
        if mt == "application/pdf" or part.get("filename", "").lower().endswith(".pdf"):
            parts.append(part)
        if "parts" in part:
            parts.extend(_collecter_pdf_parts(part))
    return parts


def _telecharger_attachment(gmail_svc, msg_id, part):
    """Retourne les bytes du PDF (inline ou attachmentId)."""
    attachment_id = part.get("body", {}).get("attachmentId")
    if attachment_id:
        att = gmail_svc.users().messages().attachments().get(
            userId="me", messageId=msg_id, id=attachment_id
        ).execute()
        return base64.urlsafe_b64decode(att["data"])
    data = part.get("body", {}).get("data", "")
    return base64.urlsafe_b64decode(data)


# ─────────────────────────────────────────────────────────────────
# Upload Drive BDC
# ─────────────────────────────────────────────────────────────────

def _upload_bdc(drive_svc, bdc_folder_id, dossier_jj_mm, nom_fichier, pdf_bytes):
    """Upload pdf_bytes dans Drive BDC/dossier_jj_mm/nom_fichier. Écrase si existant."""
    from googleapiclient.http import MediaFileUpload

    date_folder_id = _get_or_create_subfolder_drive(drive_svc, bdc_folder_id, dossier_jj_mm)
    if not date_folder_id:
        return False

    # Chercher un fichier existant pour écraser
    existing = drive_svc.files().list(
        q=(f"'{date_folder_id}' in parents and name='{nom_fichier}' and trashed=false"),
        fields="files(id)",
    ).execute().get("files", [])

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        media = MediaFileUpload(tmp_path, mimetype="application/pdf")
        if existing:
            drive_svc.files().update(
                fileId=existing[0]["id"],
                media_body=media,
            ).execute()
        else:
            drive_svc.files().create(
                body={"name": nom_fichier, "parents": [date_folder_id]},
                media_body=media,
                fields="id",
            ).execute()
        return True
    except Exception as e:
        print(f"    ERREUR upload Drive : {e}")
        return False
    finally:
        os.unlink(tmp_path)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    # Restaurer tokens depuis env (CI)
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

    gmail2_token_json = os.environ.get("GMAIL2_TOKEN_JSON", "").strip()
    if gmail2_token_json:
        with open(GMAIL2_TOKEN_FILE, "w") as f:
            f.write(gmail2_token_json)

    _charger_config()
    telecharger_config_depuis_drive()

    gmail_svc = _get_gmail2_service()
    if not gmail_svc:
        sys.exit(1)

    drive_svc = _get_drive_service()
    if not drive_svc:
        print("ERREUR : service Drive indisponible.")
        sys.exit(1)

    bdc_folder_id = controle_stocks.DRIVE_BDC_FOLDER_ID
    if not bdc_folder_id:
        print("ERREUR : DRIVE_BDC_FOLDER_ID non configuré.")
        sys.exit(1)

    print(f"Récupération des mails label '{LABEL_BDC}' …")
    messages = _lister_messages_label(gmail_svc)
    print(f"  {len(messages)} mail(s) trouvé(s)")

    nb_uploaded = 0
    nb_skipped  = 0
    nb_errors   = 0

    for msg_ref in messages:
        msg = gmail_svc.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers    = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        sujet      = headers.get("Subject", "")
        num_cde, dossier = _extraire_infos_sujet(sujet)

        if not num_cde:
            print(f"  SKIP sujet non reconnu : {sujet[:70]}")
            nb_skipped += 1
            continue

        nom_fichier = f"BonDeCommande_{num_cde}.pdf"

        # Vérifier doublon Drive
        date_folder_id = _get_or_create_subfolder_drive(drive_svc, bdc_folder_id, dossier)
        if date_folder_id:
            existing = drive_svc.files().list(
                q=(f"'{date_folder_id}' in parents and name='{nom_fichier}' and trashed=false"),
                fields="files(id)",
            ).execute().get("files", [])
            if existing:
                nb_skipped += 1
                continue

        pdf_parts = _collecter_pdf_parts(msg["payload"])
        if not pdf_parts:
            print(f"  SKIP pas de PDF : commande {num_cde}")
            nb_skipped += 1
            continue

        try:
            pdf_bytes = _telecharger_attachment(gmail_svc, msg_ref["id"], pdf_parts[0])
        except Exception as e:
            print(f"  ERREUR téléchargement {nom_fichier} : {e}")
            nb_errors += 1
            continue

        ok = _upload_bdc(drive_svc, bdc_folder_id, dossier, nom_fichier, pdf_bytes)
        if ok:
            print(f"  + {dossier}/{nom_fichier}")
            nb_uploaded += 1
        else:
            nb_errors += 1

    print(f"\nTerminé : {nb_uploaded} uploadé(s), {nb_skipped} ignoré(s), {nb_errors} erreur(s)")


if __name__ == "__main__":
    main()
