#!/usr/bin/env python3

import os
import sys
import json
import re
import shutil
import subprocess
import io
import base64
import csv
import tempfile
import fcntl
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
_TZ = ZoneInfo("Europe/Paris")

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

import livraison_drive

_BASE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR  = os.environ.get("WORK_DIR",  os.path.join(_BASE, "v 4.0.0"))
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(_BASE, "pdf_cache"))
BDC_DIR   = os.environ.get("BDC_DIR",   os.path.join(_BASE, "BDC"))
TOKEN_FILE = os.path.expanduser("~/.auto_prepa_token.json")
CREDS_FILE = os.path.expanduser("~/.auto_prepa_credentials.json")
STATE_DRIVE_FILENAME = "auto_prepa_state.json"
LOG_CONTROLE_FILENAME = "controle_articles.log"


SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.modify",
]

GMAIL_CONF_FROM      = ""
GMAIL_CONF_SUBJECT   = ""
GMAIL_LABEL_CONF     = ""
GMAIL_MODIF_SUBJECTS = []
GMAIL_LABEL_NOM      = ""

DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")

DRIVE_BONS_FOLDER_ID = ""
DRIVE_BDC_FOLDER_ID  = ""
EMAIL_ANTICIPATION   = ""
LIVRAISON_SPREADSHEET_ID = ""

CONFIG_FILES = [
    "chemin_prepa_mono.csv",
    "chemin_prepa_ramasse.csv",
    "gencod_adresses.csv",
    "gencod_nomenclatures.csv",
]

def get_credentials():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        try:
            json.loads(token_json)
        except json.JSONDecodeError as e:
            print(f"ERREUR : GOOGLE_TOKEN_JSON n'est pas un JSON valide ({e})")
            raise
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                print(f"Fichier credentials manquant : {CREDS_FILE}")
                print("Voir README_SETUP.txt pour la procedure.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds

def charger_traites(drive_svc):
    """Retourne l'ensemble des BonDeCommande_*.pdf deja traites."""
    try:
        res = drive_svc.files().list(
            q=f"name='{STATE_DRIVE_FILENAME}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return set()
        req = drive_svc.files().get_media(fileId=files[0]["id"])
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        data = json.loads(buf.getvalue().decode())
        if isinstance(data, dict):
            flat = set()
            for v in data.values():
                if isinstance(v, list):
                    flat.update(v)
            return flat
        if isinstance(data, list):
            return set(data)
        return set()
    except Exception as e:
        print(f"  Historique Drive non disponible ({e}), demarrage a zero.")
        return set()


def sauvegarder_traites(drive_svc, traites):
    """Sauvegarde la liste des bons traites dans Drive."""
    try:
        res = drive_svc.files().list(
            q=f"name='{STATE_DRIVE_FILENAME}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as f:
            json.dump(sorted(traites), f, indent=2, ensure_ascii=False)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="application/json", resumable=False)
            if existing:
                drive_svc.files().update(
                    fileId=existing[0]["id"], media_body=media).execute()
            else:
                drive_svc.files().create(
                    body={"name": STATE_DRIVE_FILENAME, "parents": [DRIVE_BONS_FOLDER_ID]},
                    media_body=media, fields="id").execute()
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"  Sauvegarde historique Drive echouee : {e}")

def _get_or_create_gmail_label(gmail_svc, nom):
    try:
        labels = gmail_svc.users().labels().list(userId='me').execute().get('labels', [])
        for label in labels:
            if label['name'] == nom:
                return label['id']
        new_label = gmail_svc.users().labels().create(
            userId='me',
            body={'name': nom, 'labelListVisibility': 'labelShow',
                  'messageListVisibility': 'show'},
        ).execute()
        return new_label['id']
    except Exception as e:
        print(f"    Label Gmail '{nom}' : {e}")
        return None


def _iter_parts(payload):
    """Parcourt recursivement les parties MIME d'un message Gmail."""
    if 'parts' in payload:
        for part in payload['parts']:
            yield from _iter_parts(part)
    else:
        yield payload


def _marquer_email(gmail_svc, msg_id, label_id):
    """Ajoute un label et retire UNREAD/INBOX."""
    try:
        body = {'removeLabelIds': ['UNREAD', 'INBOX']}
        if label_id:
            body['addLabelIds'] = [label_id]
        gmail_svc.users().messages().modify(userId='me', id=msg_id, body=body).execute()
    except Exception as e:
        print(f"    Marquage email echoue : {e}")

def telecharger_bons_email(gmail_svc, cache_dir, traites):
    """
    Lit les emails de confirmation (no-reply@systeme-u.fr),
    telecharge bon_encaissement.pdf => BonDeCommande_XXX.pdf dans cache_dir.
    Retourne {filename: (dossier_jj_mm, dossier_mm_aaaa)} pour les nouveaux PDFs telecharges.
    """
    label_id = _get_or_create_gmail_label(gmail_svc, GMAIL_LABEL_CONF)
    q = f'from:{GMAIL_CONF_FROM} subject:"{GMAIL_CONF_SUBJECT}" -label:{GMAIL_LABEL_CONF}'

    try:
        res = gmail_svc.users().messages().list(userId='me', q=q, maxResults=50).execute()
        messages = res.get('messages', [])
    except Exception as e:
        print(f"  Gmail inaccessible pour les confirmations ({e})")
        return {}

    if not messages:
        return {}

    print(f"  {len(messages)} email(s) de confirmation a traiter.")
    nouveaux = {}  # {filename: (dossier_jj_mm, dossier_mm_aaaa)}

    for m in messages:
        try:
            msg = gmail_svc.users().messages().get(
                userId='me', id=m['id'], format='full'
            ).execute()

            headers = {h['name']: h['value']
                       for h in msg['payload'].get('headers', [])}
            subject = headers.get('Subject', '')

            match_num = re.search(r'N°\s*cde\s*[:\s]+(\d+)', subject)
            if not match_num:
                print(f"    Sujet non reconnu : {subject[:80]}")
                continue
            numero = match_num.group(1)
            filename = f"BonDeCommande_{numero}.pdf"

            match_date = re.search(r'(\d{2}/\d{2}/\d{4})', subject)
            dossier_jj_mm = ""
            dossier_mm_aaaa = ""
            if match_date:
                dossier_jj_mm   = match_date.group(1)[:5].replace('/', '_')   # DD_MM
                dossier_mm_aaaa = match_date.group(1)[3:].replace('/', '_')   # MM_AAAA

            if filename in traites:
                _marquer_email(gmail_svc, m['id'], label_id)
                continue

            attachment_id = None
            for part in _iter_parts(msg['payload']):
                if part.get('filename', '').lower() == 'bon_encaissement.pdf':
                    attachment_id = part['body'].get('attachmentId')
                    break

            if not attachment_id:
                print(f"    Aucun bon_encaissement.pdf dans l'email pour cde {numero}")
                continue

            cache_path = os.path.join(cache_dir, filename)
            if not os.path.exists(cache_path):
                att = gmail_svc.users().messages().attachments().get(
                    userId='me', messageId=m['id'], id=attachment_id
                ).execute()
                pdf_bytes = base64.urlsafe_b64decode(att['data'] + '==')
                with open(cache_path, 'wb') as f:
                    f.write(pdf_bytes)
                print(f"    => {filename} OK")

            nouveaux[filename] = (dossier_jj_mm, dossier_mm_aaaa)
            _marquer_email(gmail_svc, m['id'], label_id)

        except Exception as e:
            print(f"    Erreur traitement email : {e}")

    return nouveaux

def _telecharger_bdc_archive_drive(drive_svc, numero):
    """Telecharge le BonDeCommande_NUMERO.pdf archive dans Drive BDC (avant sa
    suppression par _supprimer_bdc_drive), pour en extraire nom/prenom/date.
    Retourne le chemin local ou None si introuvable."""
    nom = f"BonDeCommande_{numero}.pdf"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return None
        dest = os.path.join(tempfile.gettempdir(), nom)
        download_pdf(drive_svc, files[0]["id"], dest)
        return dest
    except Exception as e:
        print(f"    Telechargement archive BDC {nom} echoue : {e}")
        return None


def _traiter_annulation_livraison(drive_svc, sheets_svc, numero):
    """Si la commande annulee etait une LIVRAISON, supprime sa ligne dans
    LIVRAISON DRIVE 2026. Nom/prenom/date sont extraits de l'archive BDC
    Drive, seule source encore disponible a ce stade (le mail d'annulation
    ne contient que le numero de commande)."""
    pdf_path = _telecharger_bdc_archive_drive(drive_svc, numero)
    if not pdf_path:
        return
    try:
        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            print(f"    ECHEC pdftotext sur l'archive BDC {numero}, annulation livraison ignoree.")
            return
        civilite, nom, prenom, date_cde, creneau = extraire_client_creneau_pdf(pt.stdout)
        livraison_drive.annuler_commande_livraison(
            sheets_svc, LIVRAISON_SPREADSHEET_ID, nom, prenom, date_cde, numero_commande=numero)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


def traiter_modifications_clients(drive_svc, gmail_svc, sheets_svc, traites):
    """Lit les mails de modification de commande, supprime les anciens bons, archive les mails."""
    try:
        label_id = _get_or_create_gmail_label(gmail_svc, GMAIL_LABEL_NOM)
        messages = []
        for subj in GMAIL_MODIF_SUBJECTS:
            q = f'subject:"{subj}" -label:{GMAIL_LABEL_NOM}'
            res = gmail_svc.users().messages().list(
                userId='me', q=q, maxResults=50).execute()
            messages += res.get('messages', [])
    except Exception as e:
        print(f"  Gmail inaccessible ({e}) - modifications/annulations ignorees.")
        return

    if not messages:
        return

    print(f"  {len(messages)} mail(s) de modification/annulation a traiter.")
    for m in messages:
        try:
            msg = gmail_svc.users().messages().get(
                userId='me', id=m['id'],
                format='metadata', metadataHeaders=['Subject'],
            ).execute()
            subject = next(
                (h['value'] for h in msg['payload']['headers'] if h['name'] == 'Subject'), '')

            match_modif = re.search(r'N°\s*cde:(\d+).*?N°\s*cde:(\d+)', subject)
            match_annul = re.search(r'N°\s*:\s*(\d+)', subject)

            if match_modif:
                num_ancien, num_nouveau = match_modif.group(1), match_modif.group(2)
                print(f"  Modification : cde {num_ancien} => remplacee par {num_nouveau}")
                now = datetime.now(_TZ)
                seuil = 5 if now.weekday() == 5 else (None if now.weekday() == 6 else 6)
                if seuil is not None and now.hour >= seuil:
                    dt_orig = _get_heure_email_original(gmail_svc, num_ancien)
                    if dt_orig:
                        hier = (now - timedelta(days=1)).date()
                        original_concerne = (
                            dt_orig.date() == hier
                            or (dt_orig.date() == now.date() and dt_orig.hour < seuil)
                        )
                        if original_concerne:
                            contenu_antici = _telecharger_anticipation_drive(drive_svc, num_ancien)
                            if contenu_antici:
                                _envoyer_email_anticipation(gmail_svc, num_ancien, contenu_antici)
                _alerter_si_commande_anticipee_annulee(drive_svc, gmail_svc, num_ancien, num_nouveau)
                _supprimer_bons_drive(drive_svc, num_ancien)
                _supprimer_anticipation_archive_drive(drive_svc, num_ancien)
                _supprimer_bdc_drive(drive_svc, num_ancien)
                _uploader_annulation_drive(drive_svc, num_ancien)
                supprimer_commande_avoir_drive(drive_svc, num_ancien)
                traites.add(f"BonDeCommande_{num_ancien}.pdf")
            elif match_annul:
                num_annule = match_annul.group(1)
                print(f"  Annulation : cde {num_annule} supprimee")
                _traiter_annulation_livraison(drive_svc, sheets_svc, num_annule)
                _supprimer_bons_drive(drive_svc, num_annule)
                _supprimer_anticipation_archive_drive(drive_svc, num_annule)
                _supprimer_bdc_drive(drive_svc, num_annule)
                _uploader_annulation_drive(drive_svc, num_annule)
                supprimer_commande_avoir_drive(drive_svc, num_annule)
                traites.add(f"BonDeCommande_{num_annule}.pdf")
            else:
                print(f"    Sujet non reconnu : {subject[:80]}")
                continue

            modify_body = {'removeLabelIds': ['UNREAD', 'INBOX']}
            if label_id:
                modify_body['addLabelIds'] = [label_id]
            gmail_svc.users().messages().modify(
                userId='me', id=m['id'], body=modify_body).execute()
        except Exception as e:
            print(f"    Erreur traitement mail : {e}")

def download_pdf(drive_svc, file_id, dest_path):
    req = drive_svc.files().get_media(
        fileId=file_id,
        supportsAllDrives=True,
    )
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest_path, "wb") as f:
        f.write(buf.getvalue())


def upload_bon(drive_svc, local_path):
    """Depose un fichier dans DRIVE_BONS_FOLDER_ID, ecrase s'il existe deja."""
    if not DRIVE_BONS_FOLDER_ID:
        return False
    filename = os.path.basename(local_path)

    try:
        drive_svc.files().get(fileId=DRIVE_BONS_FOLDER_ID, fields="id").execute()
    except Exception as e:
        print(f"    Dossier Drive inaccessible (ID={DRIVE_BONS_FOLDER_ID}) : {e}")
        return False

    try:
        res = drive_svc.files().list(
            q=f"name='{filename}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
    except Exception:
        existing = []

    mimetype = "application/pdf" if filename.lower().endswith(".pdf") else "text/plain"
    media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)
    try:
        if existing:
            drive_svc.files().update(
                fileId=existing[0]["id"],
                media_body=media,
            ).execute()
        else:
            drive_svc.files().create(
                body={"name": filename, "parents": [DRIVE_BONS_FOLDER_ID]},
                media_body=media,
                fields="id",
            ).execute()
        print(f"    {filename} => Drive OK")
        return True
    except Exception as e:
        print(f"    {filename} => Drive ECHEC : {e}")
        return False


def telecharger_config_drive(drive_svc):
    """Telecharge les CSV de config et le binaire depuis Drive vers WORK_DIR."""
    for filename in CONFIG_FILES + ["prepa_drive_degrade"]:
        dest = os.path.join(WORK_DIR, filename)
        try:
            res = drive_svc.files().list(
                q=f"name='{filename}' and '{DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
                fields="files(id)",
            ).execute()
            files = res.get("files", [])
            if not files:
                print(f"  ERREUR config : {filename} introuvable sur Drive")
                continue
            download_pdf(drive_svc, files[0]["id"], dest)
            if filename == "prepa_drive_degrade":
                os.chmod(dest, 0o755)
        except Exception as e:
            print(f"  ERREUR config {filename} : {e}")

def _get_or_create_subfolder(drive_svc, parent_id, name):
    """Retourne l'ID d'un sous-dossier, le cree si necessaire."""
    try:
        res = drive_svc.files().list(
            q=(f"name='{name}' and '{parent_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        folder = drive_svc.files().create(
            body={"name": name,
                  "mimeType": "application/vnd.google-apps.folder",
                  "parents": [parent_id]},
            fields="id",
        ).execute()
        return folder["id"]
    except Exception as e:
        print(f"    Creation dossier Drive '{name}' echouee : {e}")
        return None

def archiver_pdf_drive(drive_svc, pdf_path, dossier_jj_mm, dossier_mm_aaaa=""):
    """Archive un PDF dans DRIVE_BDC_FOLDER_ID/MM_AAAA/JJ_MM/ sur Drive."""
    if not DRIVE_BDC_FOLDER_ID:
        return
    filename = os.path.basename(pdf_path)
    try:
        if dossier_mm_aaaa:
            mois_id = _get_or_create_subfolder(drive_svc, DRIVE_BDC_FOLDER_ID, dossier_mm_aaaa)
            if not mois_id:
                return
            subfolder_id = _get_or_create_subfolder(drive_svc, mois_id, dossier_jj_mm)
        else:
            subfolder_id = _get_or_create_subfolder(drive_svc, DRIVE_BDC_FOLDER_ID, dossier_jj_mm)
        if not subfolder_id:
            return
        res = drive_svc.files().list(
            q=f"name='{filename}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        if res.get("files"):
            return
        media = MediaFileUpload(pdf_path, mimetype="application/pdf", resumable=False)
        drive_svc.files().create(
            body={"name": filename, "parents": [subfolder_id]},
            media_body=media,
            fields="id",
        ).execute()
        path = f"BDC/{dossier_mm_aaaa}/{dossier_jj_mm}" if dossier_mm_aaaa else f"BDC/{dossier_jj_mm}"
        print(f"    {filename} => Drive {path}/ OK")
    except Exception as e:
        path = f"BDC/{dossier_mm_aaaa}/{dossier_jj_mm}" if dossier_mm_aaaa else f"BDC/{dossier_jj_mm}"
        print(f"    Archivage Drive {path}/ echoue : {e}")

def archiver_anticipation_drive(drive_svc, anticipation_path, dossier_jj_mm, dossier_mm_aaaa):
    """Copie bon_anticipation_NUMERO.txt dans Drive GITHUB/Anticipation/MM_AAAA/JJ_MM/."""
    if not dossier_jj_mm or not dossier_mm_aaaa:
        return
    filename = os.path.basename(anticipation_path)
    path = f"GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}"
    try:
        github_id = _get_or_create_subfolder(drive_svc, "root", "GITHUB")
        if not github_id:
            return
        anticipation_id = _get_or_create_subfolder(drive_svc, github_id, "Anticipation")
        if not anticipation_id:
            return
        mois_id = _get_or_create_subfolder(drive_svc, anticipation_id, dossier_mm_aaaa)
        if not mois_id:
            return
        subfolder_id = _get_or_create_subfolder(drive_svc, mois_id, dossier_jj_mm)
        if not subfolder_id:
            return
        res = drive_svc.files().list(
            q=f"name='{filename}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        if res.get("files"):
            return
        media = MediaFileUpload(anticipation_path, mimetype="text/plain", resumable=False)
        drive_svc.files().create(
            body={"name": filename, "parents": [subfolder_id]},
            media_body=media,
            fields="id",
        ).execute()
        print(f"    {filename} => Drive {path}/ OK")
    except Exception as e:
        print(f"    Archivage Drive {path}/ echoue : {e}")

def archiver_resultat_anticipation_drive(drive_svc, local_path, dossier_mm_aaaa, dossier_jj_mm):
    """Depose le resultat final de l'anticipation du jour (anticipation_JJ_MM.txt/.pdf)
    dans Drive GITHUB/Anticipation/archives/MM_AAAA/JJ_MM/, ecrase s'il existe deja."""
    filename = os.path.basename(local_path)
    path = f"GITHUB/Anticipation/archives/{dossier_mm_aaaa}/{dossier_jj_mm}"
    try:
        github_id = _get_or_create_subfolder(drive_svc, "root", "GITHUB")
        if not github_id:
            return False
        anticipation_id = _get_or_create_subfolder(drive_svc, github_id, "Anticipation")
        if not anticipation_id:
            return False
        archives_id = _get_or_create_subfolder(drive_svc, anticipation_id, "archives")
        if not archives_id:
            return False
        mois_id = _get_or_create_subfolder(drive_svc, archives_id, dossier_mm_aaaa)
        if not mois_id:
            return False
        subfolder_id = _get_or_create_subfolder(drive_svc, mois_id, dossier_jj_mm)
        if not subfolder_id:
            return False

        res = drive_svc.files().list(
            q=f"name='{filename}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])

        mimetype = "application/pdf" if filename.lower().endswith(".pdf") else "text/plain"
        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)
        if existing:
            drive_svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
        else:
            drive_svc.files().create(
                body={"name": filename, "parents": [subfolder_id]},
                media_body=media,
                fields="id",
            ).execute()
        print(f"    {filename} => Drive {path}/ OK")
        return True
    except Exception as e:
        print(f"    Archivage Drive {path}/ echoue : {e}")
        return False

def _supprimer_anticipation_archive_drive(drive_svc, numero):
    """Supprime la copie de bon_anticipation_NUMERO.txt archivee sous GITHUB/Anticipation/."""
    nom = f"bon_anticipation_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and trashed=false",
            fields="files(id,parents)",
        ).execute()
        for f in res.get("files", []):
            if DRIVE_BONS_FOLDER_ID and DRIVE_BONS_FOLDER_ID in (f.get("parents") or []):
                continue
            drive_svc.files().delete(fileId=f["id"]).execute()
            print(f"    Supprime Drive GITHUB/Anticipation : {nom}")
    except Exception as e:
        print(f"    Suppression archive GITHUB/Anticipation {nom} echouee : {e}")

def _supprimer_bdc_drive(drive_svc, numero):
    """Supprime BonDeCommande_NUMERO.pdf du dossier Drive BDC (tous sous-dossiers)."""
    if not DRIVE_BDC_FOLDER_ID or not drive_svc:
        return
    nom = f"BonDeCommande_{numero}.pdf"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and trashed=false",
            fields="files(id,name)",
        ).execute()
        for f in res.get("files", []):
            drive_svc.files().delete(fileId=f["id"]).execute()
            print(f"    Supprime Drive BDC : {nom}")
    except Exception as e:
        print(f"    Suppression Drive BDC {nom} echouee : {e}")

def _supprimer_bons_drive(drive_svc, numero):
    """Supprime bon_prepa_ et bon_anticipation_ d'un numero donne dans DRIVE_BONS_FOLDER_ID."""
    for nom_fichier in [f"bon_prepa_{numero}.txt", f"bon_anticipation_{numero}.txt"]:
        try:
            res = drive_svc.files().list(
                q=f"name='{nom_fichier}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
                fields="files(id)",
            ).execute()
            for f in res.get("files", []):
                drive_svc.files().delete(fileId=f["id"]).execute()
                print(f"    Supprime Drive : {nom_fichier}")
        except Exception as e:
            print(f"    Suppression {nom_fichier} echouee : {e}")

def _uploader_annulation_drive(drive_svc, numero):
    """Depose annuler_NUMERO.txt dans DRIVE_BONS_FOLDER_ID pour declencher la suppression sur le telephone."""
    nom_fichier = f"annuler_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom_fichier}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        if res.get("files"):
            print(f"    Annulation deja presente sur Drive : {nom_fichier}")
            return
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False, encoding="utf-8") as f:
            f.write(numero)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="text/plain", resumable=False)
            drive_svc.files().create(
                body={"name": nom_fichier, "parents": [DRIVE_BONS_FOLDER_ID]},
                media_body=media, fields="id",
            ).execute()
            print(f"    Annulation deposee sur Drive : {nom_fichier}")
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"    Upload annulation {nom_fichier} echoue : {e}")
        raise


def _get_heure_email_original(gmail_svc, numero):
    """Retourne le datetime (Paris) de reception de l'email de confirmation original."""
    q = f'label:{GMAIL_LABEL_CONF} "{numero}"'
    try:
        res = gmail_svc.users().messages().list(userId='me', q=q, maxResults=1).execute()
        messages = res.get('messages', [])
        if not messages:
            return None
        msg = gmail_svc.users().messages().get(
            userId='me', id=messages[0]['id'], format='minimal').execute()
        return datetime.fromtimestamp(int(msg['internalDate']) / 1000, tz=_TZ)
    except Exception as e:
        print(f"    Horodatage email original {numero} introuvable : {e}")
        return None

def _telecharger_anticipation_drive(drive_svc, numero):
    """Telecharge et retourne le contenu de bon_anticipation_NUMERO.txt depuis Drive."""
    if not DRIVE_BONS_FOLDER_ID:
        return ""
    nom = f"bon_anticipation_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return ""
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    Telechargement anticipation {numero} echoue : {e}")
        return ""

_CIVILITES_LONGUES = {"M.": "Monsieur", "Mme": "Madame"}


def _telecharger_commandes_anticipees_archivees(drive_svc, dossier_mm_aaaa, dossier_jj_mm):
    """Telecharge et parse GITHUB/Anticipation/archives/MM_AAAA/JJ_MM/commandes_anticipées_JJ_MM.txt
    (deja archive par anticipation_commandes.py). Retourne l'ensemble des numeros de
    commande deja anticipes ce jour-la (vide si le fichier ou un dossier parent
    n'existe pas encore)."""
    def _sous_dossier(parent_id, nom):
        if not parent_id:
            return None
        res = drive_svc.files().list(
            q=(f"name='{nom}' and '{parent_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    nom_fichier = f"commandes_anticipées_{dossier_jj_mm}.txt"
    try:
        github_id = _sous_dossier("root", "GITHUB")
        anticipation_id = _sous_dossier(github_id, "Anticipation")
        archives_id = _sous_dossier(anticipation_id, "archives")
        mois_id = _sous_dossier(archives_id, dossier_mm_aaaa)
        subfolder_id = _sous_dossier(mois_id, dossier_jj_mm)
        if not subfolder_id:
            return set()

        res = drive_svc.files().list(
            q=f"name='{nom_fichier}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return set()
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        contenu = buf.getvalue().decode("utf-8", errors="replace")
        return {c.strip() for c in contenu.strip().split(',') if c.strip()}
    except Exception as e:
        print(f"    Lecture {nom_fichier} echouee : {e}")
        return set()


def _envoyer_email_anticipation_annulee(gmail_svc, civilite, nom, prenom, num_ancien, num_nouveau):
    """Alerte : la commande annulee/remplacee faisait deja partie d'une anticipation archivee."""
    from email.mime.text import MIMEText
    destinataire = EMAIL_ANTICIPATION
    if not destinataire:
        return
    civilite_txt = _CIVILITES_LONGUES.get(civilite, "Monsieur/Madame")
    client = " ".join(p for p in (civilite_txt, nom, prenom) if p)
    corps = (
        f"Bonjour,\n\n"
        f"La commande de {client}, n°{num_ancien} a été annulée et remplacée "
        f"par la commande n°{num_nouveau} et faisait partie de l'anticipation.\n\n"
        f"Merci d'être vigilant sur les produits de cette commande.\n\n"
        f"Cordialement,\nErwan"
    )
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = "Attention commande anticipée et annulée"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email alerte anticipation annulee envoye pour cde {num_ancien} => {destinataire}")
    except Exception as e:
        print(f"    Envoi email alerte anticipation annulee {num_ancien} echoue : {e}")


def _alerter_si_commande_anticipee_annulee(drive_svc, gmail_svc, num_ancien, num_nouveau):
    """Si la commande annulee/remplacee (num_ancien) faisait deja partie d'une
    anticipation archivee aujourd'hui (commandes_anticipées_JJ_MM.txt), alerte
    par email avec le nom du client (extrait de l'archive BDC, encore presente
    sur Drive a ce stade, avant sa suppression par _supprimer_bdc_drive)."""
    now = datetime.now(_TZ)
    dossier_mm_aaaa = now.strftime("%m_%Y")
    dossier_jj_mm = now.strftime("%d_%m")
    commandes_anticipees = _telecharger_commandes_anticipees_archivees(
        drive_svc, dossier_mm_aaaa, dossier_jj_mm)
    if num_ancien not in commandes_anticipees:
        return

    print(f"    ATTENTION : commande {num_ancien} annulee faisait partie de "
          f"l'anticipation du {dossier_jj_mm} !")

    civilite = nom = prenom = ""
    pdf_path = _telecharger_bdc_archive_drive(drive_svc, num_ancien)
    if pdf_path:
        try:
            pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                                capture_output=True, text=True)
            if pt.stdout.strip():
                civilite, nom, prenom, _, _ = extraire_client_creneau_pdf(pt.stdout)
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    _envoyer_email_anticipation_annulee(gmail_svc, civilite, nom, prenom, num_ancien, num_nouveau)


def _envoyer_email_anticipation(gmail_svc, numero, contenu):
    """Envoie le contenu du bon d'anticipation supprime par email."""
    from email.mime.text import MIMEText
    destinataire = EMAIL_ANTICIPATION
    sujet = f"Commande {numero} - anticipation renouvelee"
    try:
        msg = MIMEText(contenu, "plain", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = sujet
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email anticipation envoye pour cde {numero} => {destinataire}")
    except Exception as e:
        print(f"    Envoi email anticipation {numero} echoue : {e}")

def _envoyer_email_adresses_manquantes(gmail_svc, numero, avertissements_nomenclature, avertissements_inconnues):
    """Alerte par email sur les anomalies d'adressage remontees par prepa_drive_degrade.

    Deux cas distincts :
    - adresse absente de chemin_prepa_mono mais nomenclature trouvee : le produit
      est replace au bon endroit via gencod_nomenclatures.csv (chemin_prepa_ramasse
      ou chemin_prepa_mono selon le cas) ;
    - ni adresse ni nomenclature : le produit est insere avec la mention
      'ADRESSE INCONNUE' et positionne en fin de chemin (zone 'W').
    """
    from email.mime.text import MIMEText
    destinataire = EMAIL_ANTICIPATION
    if not destinataire:
        return
    total = len(avertissements_nomenclature) + len(avertissements_inconnues)
    sections = [
        f"Bonjour,\n\n"
        f"Lors du traitement de la commande {numero}, {total} anomalie(s) d'adressage "
        f"ont ete detectee(s) :\n"
    ]
    if avertissements_nomenclature:
        detail = '\n'.join(f"  {a}" for a in avertissements_nomenclature)
        sections.append(
            f"\n{len(avertissements_nomenclature)} produit(s) dont l'adresse ne fait pas "
            f"partie du chemin de preparation ont ete replaces au bon endroit via leur "
            f"nomenclature (gencod_nomenclatures.csv) dans chemin_prepa_ramasse ou "
            f"chemin_prepa_mono :\n\n"
            f"{detail}\n"
        )
    if avertissements_inconnues:
        detail = '\n'.join(f"  {a}" for a in avertissements_inconnues)
        sections.append(
            f"\n{len(avertissements_inconnues)} produit(s) sans adresse ni nomenclature "
            f"connue(s) ont ete inseres avec la mention 'ADRESSE INCONNUE' et positionnes "
            f"en fin de chemin (zone 'W') :\n\n"
            f"{detail}\n"
        )
    sections.append(
        f"\nMerci de mettre a jour chemin_prepa_mono.csv"
        f"{' et gencod_nomenclatures.csv' if avertissements_inconnues else ''} sur Drive.\n"
    )
    corps = ''.join(sections)
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = f"Commande {numero} - anomalie(s) d'adressage dans chemin_prepa_mono"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email anomalie(s) d'adressage envoye pour cde {numero} => {destinataire}")
    except Exception as e:
        print(f"    Envoi email anomalie(s) d'adressage {numero} echoue : {e}")

def _envoyer_email_anomalie_bon(gmail_svc, numero, lignes_invalides):
    """Alerte par email quand un bon de prepa contient des lignes mal formees."""
    from email.mime.text import MIMEText
    destinataire = EMAIL_ANTICIPATION
    if not destinataire:
        return
    details = '\n'.join(
        f"  ligne {i} ({nb} sep.) : {l[:150]}"
        for i, nb, l in lignes_invalides
    )
    corps = (
        f"Bonjour,\n\n"
        f"Le bon de preparation de la commande {numero} contient "
        f"{len(lignes_invalides)} ligne(s) avec un nombre de separateurs incorrect "
        f"(attendu : 14).\n\n"
        f"Detail :\n{details}\n\n"
        f"Le fichier a quand meme ete uploade mais pourrait faire planter l'appli.\n"
    )
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = f"Commande {numero} - bon de prepa invalide"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email anomalie envoye pour cde {numero} => {destinataire}")
    except Exception as e:
        print(f"    Envoi email anomalie {numero} echoue : {e}")

def _envoyer_email_km_manquant(gmail_svc, numero, nom, prenom, date_cde_str):
    """Alerte par email quand la distance (colonne km) n'a pas pu etre
    recuperee sur Shopopop pour une commande LIVRAISON (identifiants/site
    Shopopop indisponibles, ou destinataire introuvable dans les livraisons
    programmees) — a completer a la main dans LIVRAISON DRIVE 2026."""
    from email.mime.text import MIMEText
    destinataire = EMAIL_ANTICIPATION
    if not destinataire:
        return
    corps = (
        f"Bonjour,\n\n"
        f"Le nombre de km n'a pas pu etre recupere sur Shopopop pour la commande "
        f"{numero} ({nom} {prenom}, livraison du {date_cde_str}).\n\n"
        f"Merci de completer la colonne km a la main dans LIVRAISON DRIVE 2026.\n"
    )
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = f"Commande {numero} - km Shopopop non renseigne"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email km manquant envoye pour cde {numero} => {destinataire}")
    except Exception as e:
        print(f"    Envoi email km manquant {numero} echoue : {e}")

def extraire_articles_produits_pdf(texte):
    """Extrait (nb_articles, nb_produits) depuis les premieres lignes du PDF."""
    articles = produits = None
    for ligne in texte.splitlines()[:40]:
        if articles is None:
            m = re.search(r'(\d+)\s+articles?', ligne, re.IGNORECASE)
            if m:
                articles = int(m.group(1))
        if produits is None:
            m = re.search(r'(\d+)\s+produits?', ligne, re.IGNORECASE)
            if m:
                produits = int(m.group(1))
        if articles is not None and produits is not None:
            break
    return articles, produits

_RE_CLIENT = re.compile(r'\b(M\.|Mme)\s+([A-Za-zÀ-ÿ\'\-]+(?: [A-Za-zÀ-ÿ\'\-]+){0,3})')
_RE_DATE = re.compile(
    r'\b(?:LUNDI|MARDI|MERCREDI|JEUDI|VENDREDI|SAMEDI|DIMANCHE)\s+(\d{2}/\d{2}/\d{4})')
_RE_CRENEAU = re.compile(r'\b(\d{1,2}h\d{2}\s*-\s*\d{1,2}h\d{2})\b')

def extraire_client_creneau_pdf(texte):
    """Extrait (civilite, nom, prenom, date, creneau) depuis le bon d'encaissement
    (pdftotext -layout) : civilite/nom/prenom sur la ligne client (ex. 'M. DOMMEE
    FABRICE' ou 'Mme PEYROT SEILLIER ELOANE' - dernier mot = prenom, le reste =
    nom) ; date et creneau dans l'encadre jour de retrait/livraison (ex. 'VENDREDI
    14/08/2026' et '10h30 - 11h00'), sur des lignes distinctes du fait de la mise
    en colonnes (recherches independantes)."""
    civilite = nom = prenom = date_cde = creneau = ""
    m_client = _RE_CLIENT.search(texte)
    if m_client:
        civilite = m_client.group(1)
        mots = m_client.group(2).split(' ')
        prenom = mots[-1]
        nom = ' '.join(mots[:-1])
    m_date = _RE_DATE.search(texte)
    if m_date:
        date_cde = m_date.group(1)
    m_creneau = _RE_CRENEAU.search(texte)
    if m_creneau:
        creneau = re.sub(r'\s+', ' ', m_creneau.group(1))
    return civilite, nom, prenom, date_cde, creneau

def log_ecart_drive(drive_svc, numero, articles_pdf, produits_pdf, articles_gen, produits_gen):
    ligne = (f"{datetime.now(_TZ).strftime('%Y-%m-%d %H:%M')} | cde {numero} | "
             f"PDF : {articles_pdf} art. / {produits_pdf} pdt. | "
             f"genere : {articles_gen} art. / {produits_gen} pdt.\n")
    print(f"  ECART articles/produits : {ligne.strip()}")
    try:
        res = drive_svc.files().list(
            q=f"name='{LOG_CONTROLE_FILENAME}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        contenu = ""
        if existing:
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=existing[0]["id"]))
            done = False
            while not done:
                _, done = dl.next_chunk()
            contenu = buf.getvalue().decode("utf-8", errors="replace")
        contenu += ligne
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                         delete=False, encoding="utf-8") as f:
            f.write(contenu)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="text/plain", resumable=False)
            if existing:
                drive_svc.files().update(
                    fileId=existing[0]["id"], media_body=media).execute()
            else:
                drive_svc.files().create(
                    body={"name": LOG_CONTROLE_FILENAME, "parents": [DRIVE_BONS_FOLDER_ID]},
                    media_body=media, fields="id",
                ).execute()
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"    Log ecart Drive echoue : {e}")

AVOIR_SHEET_FILENAME = "Commandes en cours"
AVOIR_ENTETE = ["Civilité", "N° commande", "Nom", "Prénom", "Date", "Créneau"]

def inscrire_commande_avoir_drive(drive_svc, civilite, numero, nom, prenom, date_cde, creneau):
    """Ajoute une ligne (civilite, numero, nom, prenom, date, creneau) au Google Sheet
    Drive GITHUB/Avoir/Commandes en cours, pour chaque commande geree. Le numero de
    commande en deuxieme colonne permet de retrouver/supprimer la ligne en cas
    d'annulation ou de remplacement."""
    if not (nom or prenom):
        print("    Civilite/nom/prenom introuvables dans le PDF, ligne Avoir ignoree.")
        return
    try:
        github_id = _get_or_create_subfolder(drive_svc, "root", "GITHUB")
        if not github_id:
            return
        avoir_id = _get_or_create_subfolder(drive_svc, github_id, "Avoir")
        if not avoir_id:
            return

        res = drive_svc.files().list(
            q=(f"name='{AVOIR_SHEET_FILENAME}' and '{avoir_id}' in parents "
               f"and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"),
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])

        lignes = [AVOIR_ENTETE]
        if existing:
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(
                buf, drive_svc.files().export_media(fileId=existing[0]["id"], mimeType="text/csv"))
            done = False
            while not done:
                _, done = dl.next_chunk()
            contenu = buf.getvalue().decode("utf-8-sig", errors="replace")
            lues = [l for l in csv.reader(io.StringIO(contenu)) if l]
            if lues:
                lignes = lues
                lignes[0] = AVOIR_ENTETE

        lignes.append([civilite, numero, nom, prenom, date_cde, creneau])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(lignes)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="text/csv", resumable=False)
            if existing:
                drive_svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            else:
                drive_svc.files().create(
                    body={"name": AVOIR_SHEET_FILENAME, "parents": [avoir_id],
                          "mimeType": "application/vnd.google-apps.spreadsheet"},
                    media_body=media, fields="id",
                ).execute()
            print(f"    Avoir/{AVOIR_SHEET_FILENAME} : {civilite} {numero} {nom} {prenom} | "
                  f"{date_cde} | {creneau}")
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"    Ecriture Drive GITHUB/Avoir/{AVOIR_SHEET_FILENAME} echouee : {e}")

def supprimer_commande_avoir_drive(drive_svc, numero):
    """Supprime, dans Drive GITHUB/Avoir/Commandes en cours, la ligne dont le
    numero de commande (2e colonne) correspond a numero, suite a une
    annulation ou un remplacement de commande."""
    try:
        github_id = _get_or_create_subfolder(drive_svc, "root", "GITHUB")
        if not github_id:
            return
        avoir_id = _get_or_create_subfolder(drive_svc, github_id, "Avoir")
        if not avoir_id:
            return

        res = drive_svc.files().list(
            q=(f"name='{AVOIR_SHEET_FILENAME}' and '{avoir_id}' in parents "
               f"and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"),
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        if not existing:
            return

        buf = io.BytesIO()
        dl = MediaIoBaseDownload(
            buf, drive_svc.files().export_media(fileId=existing[0]["id"], mimeType="text/csv"))
        done = False
        while not done:
            _, done = dl.next_chunk()
        contenu = buf.getvalue().decode("utf-8-sig", errors="replace")
        lignes = [l for l in csv.reader(io.StringIO(contenu)) if l]
        if not lignes:
            return

        entete, corps = lignes[0], lignes[1:]
        nouveau_corps = [l for l in corps if len(l) < 2 or l[1] != numero]
        if len(nouveau_corps) == len(corps):
            return

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8", newline="") as f:
            csv.writer(f).writerows([entete] + nouveau_corps)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="text/csv", resumable=False)
            drive_svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            print(f"    Avoir/{AVOIR_SHEET_FILENAME} : ligne commande {numero} supprimee")
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"    Suppression Drive GITHUB/Avoir/{AVOIR_SHEET_FILENAME} echouee : {e}")

LOCK_FILE = os.path.expanduser("~/.auto_prepa.lock")

def main():
    lock_f = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Une autre instance est deja en cours d'execution.")
        sys.exit(0)

    try:
        _main()
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

def _charger_config(drive_svc):
    """Charge config.json depuis DRIVE_CONFIG_FOLDER_ID et initialise les globals."""
    global DRIVE_BONS_FOLDER_ID, DRIVE_BDC_FOLDER_ID, EMAIL_ANTICIPATION, LIVRAISON_SPREADSHEET_ID
    if not DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : secret DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)
    try:
        res = drive_svc.files().list(
            q=f"name='config.json' and '{DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            print("ERREUR : config.json introuvable dans le dossier Drive config.")
            sys.exit(1)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        cfg = json.loads(buf.getvalue().decode())
        DRIVE_BONS_FOLDER_ID = cfg["drive_bons_folder_id"]
        DRIVE_BDC_FOLDER_ID  = cfg["drive_bdc_folder_id"]
        EMAIL_ANTICIPATION   = cfg.get("email_destinataire", "")
        LIVRAISON_SPREADSHEET_ID = (cfg.get("livraison_spreadsheet_id", "").strip()
                                     or livraison_drive.LIVRAISON_SPREADSHEET_ID_DEFAUT)
    except Exception as e:
        print(f"ERREUR chargement config Drive : {e}")
        sys.exit(1)

def _charger_gmail_filters(drive_svc):
    """Charge gmail_filters.json depuis Drive et initialise les globals Gmail."""
    global GMAIL_CONF_FROM, GMAIL_CONF_SUBJECT, GMAIL_LABEL_CONF
    global GMAIL_MODIF_SUBJECTS, GMAIL_LABEL_NOM
    try:
        res = drive_svc.files().list(
            q=f"name='gmail_filters.json' and '{DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            print("ERREUR : gmail_filters.json introuvable dans le dossier Drive config.")
            sys.exit(1)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        cfg = json.loads(buf.getvalue().decode("utf-8"))
        GMAIL_CONF_FROM      = cfg["conf_from"]
        GMAIL_CONF_SUBJECT   = cfg["conf_subject"]
        GMAIL_LABEL_CONF     = cfg["conf_label"]
        GMAIL_MODIF_SUBJECTS = cfg["modif_subjects"]
        GMAIL_LABEL_NOM      = cfg["modif_label"]
    except Exception as e:
        print(f"ERREUR chargement gmail_filters.json : {e}")
        sys.exit(1)

def _main():
    heure_cron = datetime.now(_TZ).strftime("%Hh%M")

    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    creds = get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)
    sheets_svc = build("sheets", "v4", credentials=creds)

    _charger_config(drive_svc)
    _charger_gmail_filters(drive_svc)
    telecharger_config_drive(drive_svc)
    chemin_csv = os.path.join(WORK_DIR, "chemin_prepa_ramasse.csv")
    if os.path.exists(chemin_csv):
        upload_bon(drive_svc, chemin_csv)

    traites = charger_traites(drive_svc)
    traiter_modifications_clients(drive_svc, gmail_svc, sheets_svc, traites)
    nouveaux = telecharger_bons_email(gmail_svc, CACHE_DIR, traites)

    if not nouveaux:
        print(f"Pas de nouvelle commande ({len(traites)} deja traitee(s)).")
        return

    print(f"{len(nouveaux)} nouvelle(s) commande(s) detectee(s) :")
    for pdf in sorted(nouveaux):
        print(f"  - {pdf}")

    # Connexion Shopopop differee : uniquement quand une commande LIVRAISON
    # est effectivement rencontree ci-dessous (5 a 10 fois/jour), pas a
    # chaque run avec de nouvelles commandes (qui peuvent etre en Drive).
    shopopop_token, shopopop_drive_id, shopopop_connecte = None, None, False

    os.makedirs(BDC_DIR, exist_ok=True)
    processed = set()

    for pdf, (dossier_jj_mm, dossier_mm_aaaa) in sorted(nouveaux.items()):
        order_num = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")

        bdc_subdir = os.path.join(BDC_DIR, dossier_jj_mm) if dossier_jj_mm else BDC_DIR
        os.makedirs(bdc_subdir, exist_ok=True)
        bdc_dst = os.path.join(bdc_subdir, pdf)
        cache_path = os.path.join(CACHE_DIR, pdf)
        if not os.path.exists(bdc_dst):
            shutil.copy2(cache_path, bdc_dst)
        if dossier_jj_mm:
            archiver_pdf_drive(drive_svc, cache_path, dossier_jj_mm, dossier_mm_aaaa)

        for fname in [
            "bon_prepa.txt", "bon_anticipation.txt",
            "bon_prepa_NEW.txt", "bon_prepa_dlc.txt",
            "bon_encaissement.pdf", "bon_encaissement.csv", "bon_encaissement_NEW.csv",
            "base_client.txt", "tri_cde.txt", "tri_heures.txt",
            "tmp", "tmp2", "tmp_NEW", "temp", "gentemp.txt", "temp_lib.txt",
        ]:
            fpath = os.path.join(WORK_DIR, fname)
            if os.path.exists(fpath):
                os.remove(fpath)

        shutil.copy2(cache_path, os.path.join(WORK_DIR, pdf))

        _bases_ok = True
        for csv_requis in ["gencod_adresses.csv", "gencod_nomenclatures.csv"]:
            fpath = os.path.join(WORK_DIR, csv_requis)
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                print(f"  ERREUR CRITIQUE : {csv_requis} absent ou vide dans {WORK_DIR}")
                _bases_ok = False
                break
        if not _bases_ok:
            break

        pdf_path = os.path.join(WORK_DIR, pdf)
        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            print(f"  ECHEC pdftotext - PDF vide ou non lisible : {pdf}")
            os.remove(pdf_path)
            processed.add(pdf)
            continue

        articles_pdf, produits_pdf = extraire_articles_produits_pdf(pt.stdout)

        montant_pdf = ""
        for _ligne in pt.stdout.splitlines():
            if "Montant initial" in _ligne:
                _m = re.search(r'(\d+[.,]\d+)', _ligne)
                if _m:
                    montant_pdf = _m.group(1).replace(',', '.')
                break

        heure_pdf = heure_cron
        for _ligne in pt.stdout.splitlines():
            _m = re.search(r'[Gg]énéré le \d{2}/\d{2}/\d{4} à (\d{1,2}):(\d{2})', _ligne)
            if _m:
                heure_pdf = f"{int(_m.group(1)):02d}h{_m.group(2)}"
                break

        print(f"  [{order_num}] Generation...", end="", flush=True)
        r = subprocess.run(["./prepa_drive_degrade"], cwd=WORK_DIR,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f" ERREUR (code {r.returncode})")
            if r.stdout: print(f"    stdout : {r.stdout[:300]}")
            if r.stderr: print(f"    stderr : {r.stderr[:300]}")
            p = os.path.join(WORK_DIR, pdf)
            if os.path.exists(p):
                os.remove(p)
            continue

        bon_prepa_path = os.path.join(WORK_DIR, "bon_prepa.txt")
        if not os.path.exists(bon_prepa_path) or os.path.getsize(bon_prepa_path) == 0:
            print(f" VIDE - bon_prepa.txt absent ou vide")
            if r.stdout: print(f"    sortie C++ : {r.stdout[:300]}")
            processed.add(pdf)
            continue
        print(" OK")

        civilite, nom, prenom, date_cde, creneau = extraire_client_creneau_pdf(pt.stdout)
        inscrire_commande_avoir_drive(drive_svc, civilite, order_num, nom, prenom, date_cde, creneau)

        avertissements_nomenclature = [
            ligne.rstrip('\n')
            for ligne in r.stdout.splitlines()
            if "ne fait pas partie du chemin de" in ligne
        ]
        avertissements_inconnues = [
            ligne.rstrip('\n')
            for ligne in r.stdout.splitlines()
            if "Aucune adresse ni aucune nomenclature" in ligne
        ]
        if avertissements_nomenclature or avertissements_inconnues:
            total = len(avertissements_nomenclature) + len(avertissements_inconnues)
            print(f"    {total} anomalie(s) d'adressage detectee(s) dans chemin_prepa_mono "
                  f"({len(avertissements_nomenclature)} replacee(s) via nomenclature, "
                  f"{len(avertissements_inconnues)} adresse inconnue)")
            _envoyer_email_adresses_manquantes(
                gmail_svc, order_num, avertissements_nomenclature, avertissements_inconnues)

        with open(bon_prepa_path, 'r', encoding='utf-8') as f:
            lignes = f.readlines()

        if len(lignes) > 1 and ',Livraison,' in lignes[1]:
            if not shopopop_connecte:
                shopopop_token, shopopop_drive_id = livraison_drive.connecter_shopopop(drive_svc)
                shopopop_connecte = True
            km_manquant = livraison_drive.traiter_commande_livraison(
                sheets_svc, LIVRAISON_SPREADSHEET_ID, nom, prenom, date_cde, numero_commande=order_num,
                shopopop_token=shopopop_token, shopopop_drive_id=shopopop_drive_id)
            if km_manquant:
                _envoyer_email_km_manquant(gmail_svc, order_num, nom, prenom, date_cde)

        if lignes:
            if montant_pdf:
                lignes[0] = lignes[0].rstrip('\n') + ',' + montant_pdf
            lignes[0] = lignes[0].rstrip('\n') + ',' + heure_pdf + '\n'
            lignes[1:] = [re.sub(r'^(?:-\d+)?;(\d{13};)', r'\1', l) for l in lignes[1:]]
        with open(bon_prepa_path, 'w', encoding='utf-8') as f:
            f.writelines(lignes)

        if articles_pdf is not None and produits_pdf is not None:
            with open(bon_prepa_path, 'r', encoding='utf-8') as _f:
                _entete = _f.readline().rstrip('\n')
            _parts = _entete.split(',')
            try:
                articles_gen = int(_parts[2].strip())
                produits_gen = int(_parts[3].strip())
                if articles_gen != articles_pdf or produits_gen != produits_pdf:
                    log_ecart_drive(drive_svc, order_num,
                                    articles_pdf, produits_pdf,
                                    articles_gen, produits_gen)
            except (IndexError, ValueError):
                pass

        lignes_invalides = []
        with open(bon_prepa_path, 'r', encoding='utf-8') as _f:
            for i, ligne in enumerate(_f, start=1):
                if i == 1:
                    continue
                if ligne.strip() and ligne.count(';') != 14:
                    lignes_invalides.append((i, ligne.count(';'), ligne.strip()))
        if lignes_invalides:
            details = '\n'.join(
                f"  ligne {i} ({nb} separateurs) : {l[:120]}"
                for i, nb, l in lignes_invalides
            )
            print(f" AVERTISSEMENT bon_prepa invalide ({len(lignes_invalides)} ligne(s)) :\n{details}")
            log_ecart_drive(drive_svc, order_num,
                            articles_pdf or 0, produits_pdf or 0,
                            -1, -1)
            _envoyer_email_anomalie_bon(gmail_svc, order_num, lignes_invalides)

        for src_name, dst_name in [
            ("bon_prepa.txt",        f"bon_prepa_{order_num}.txt"),
            ("bon_anticipation.txt", f"bon_anticipation_{order_num}.txt"),
        ]:
            src_f = os.path.join(WORK_DIR, src_name)
            dst_f = os.path.join(WORK_DIR, dst_name)
            if os.path.exists(src_f):
                os.rename(src_f, dst_f)

        anticipation_dst = os.path.join(WORK_DIR, f"bon_anticipation_{order_num}.txt")
        if os.path.exists(anticipation_dst) and os.path.getsize(anticipation_dst) > 0:
            archiver_anticipation_drive(drive_svc, anticipation_dst, dossier_jj_mm, dossier_mm_aaaa)

        for fname in [f"bon_prepa_{order_num}.txt",
                      f"bon_anticipation_{order_num}.txt"]:
            fpath = os.path.join(WORK_DIR, fname)
            if os.path.exists(fpath):
                if upload_bon(drive_svc, fpath):
                    os.remove(fpath)

        pdf_work = os.path.join(WORK_DIR, pdf)
        if os.path.exists(pdf_work):
            os.remove(pdf_work)

        processed.add(pdf)

    sauvegarder_traites(drive_svc, traites | processed)

if __name__ == "__main__":
    main()
