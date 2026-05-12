#!/usr/bin/env python3
"""
auto_prepa.py - Automatisation préparation Drive supermarché
Lit les emails de confirmation de commande (no-reply@systeme-u.fr),
télécharge bon_encaissement.pdf → renomme en BonDeCommande_XXX.pdf,
génère bon_prepa_XXX.txt via le binaire C++ et le pousse sur Drive.
"""

import os
import sys
import json
import re
import shutil
import subprocess
import io
import base64
import tempfile
import fcntl
from datetime import date, datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION — à remplir une seule fois
# ─────────────────────────────────────────────────────────────────

# Répertoire de base : dossier contenant ce script
_BASE = os.path.dirname(os.path.abspath(__file__))

# Dossier de travail du programme C++
WORK_DIR  = os.environ.get("WORK_DIR",  os.path.join(_BASE, "v 4.0.0"))

# Dossier cache : PDFs téléchargés une fois, conservés ici
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(_BASE, "pdf_cache"))

# Archive des PDFs d'origine, un sous-dossier par jour (JJ_MM)
BDC_DIR   = os.environ.get("BDC_DIR",   os.path.join(_BASE, "BDC"))

# Fichiers internes
TOKEN_FILE = os.path.expanduser("~/.auto_prepa_token.json")
CREDS_FILE = os.path.expanduser("~/.auto_prepa_credentials.json")

# Nom du fichier d'état stocké dans DRIVE_BONS_FOLDER_ID
STATE_DRIVE_FILENAME = "auto_prepa_state.json"

# Fichier de log des écarts articles/produits
LOG_CONTROLE_FILENAME = "controle_articles.log"


SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Label Gmail pour archiver les confirmations de commande traitées
GMAIL_LABEL_CONF = "BDC_Conf_Traites"

# Label Gmail pour archiver les modifications/annulations traitées
GMAIL_LABEL_NOM = "BDC_Modif_Traites"

# Dossier Drive où déposer les bons pour le téléphone.
DRIVE_BONS_FOLDER_ID = "1yw_z0d90UxAix6RZ-fLpxKXuc897ghk_"

# Dossier Drive pour l'archivage des PDFs BDC.
DRIVE_BDC_FOLDER_ID = "10gxP-IbO_-F03QiS75B027HLgKXI0mPs"

# Dossier Drive contenant les fichiers de configuration (CSV)
DRIVE_CONFIG_FOLDER_ID = "1rWyZiKe89c7c67eemD33gN4eSLal_FeV"

CONFIG_FILES = [
    "chemin_prepa_mono.csv",
    "chemin_prepa_ramasse.csv",
    "gencod_adresses.csv",
    "gencod_nomenclatures.csv",
]


# ── Auth ───────────────────────────────────────────────────────────

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
                print("Voir README_SETUP.txt pour la procédure.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


# ── État (liste plate des bons traités, stockée dans Drive) ──────

def charger_traites(drive_svc):
    """Retourne l'ensemble des BonDeCommande_*.pdf déjà traités."""
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
        # Compatibilité ascendante : ancien format {"DD/MM/YYYY": [...]}
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
        print(f"  Historique Drive non disponible ({e}), démarrage à zéro.")
        return set()


def sauvegarder_traites(drive_svc, traites):
    """Sauvegarde la liste des bons traités dans Drive."""
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
        print(f"  Sauvegarde historique Drive échouée : {e}")


# ── Gmail — helpers ───────────────────────────────────────────────

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
    """Parcourt récursivement les parties MIME d'un message Gmail."""
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
        print(f"    Marquage email échoué : {e}")


# ── Gmail — confirmations de commande ────────────────────────────

def telecharger_bons_email(gmail_svc, cache_dir, traites):
    """
    Lit les emails de confirmation (no-reply@systeme-u.fr),
    télécharge bon_encaissement.pdf → BonDeCommande_XXX.pdf dans cache_dir.
    Retourne {filename: dossier_jj_mm} pour les nouveaux PDFs téléchargés.
    """
    label_id = _get_or_create_gmail_label(gmail_svc, GMAIL_LABEL_CONF)
    q = f'from:no-reply@systeme-u.fr subject:"Confirmation commande" -label:{GMAIL_LABEL_CONF}'

    try:
        res = gmail_svc.users().messages().list(userId='me', q=q, maxResults=50).execute()
        messages = res.get('messages', [])
    except Exception as e:
        print(f"  Gmail inaccessible pour les confirmations ({e})")
        return {}

    if not messages:
        return {}

    print(f"  {len(messages)} email(s) de confirmation à traiter.")
    nouveaux = {}  # {filename: dossier_jj_mm}

    for m in messages:
        try:
            msg = gmail_svc.users().messages().get(
                userId='me', id=m['id'], format='full'
            ).execute()

            headers = {h['name']: h['value']
                       for h in msg['payload'].get('headers', [])}
            subject = headers.get('Subject', '')

            # Extraire le numéro de commande depuis l'objet du mail
            match_num = re.search(r'N°\s*cde\s*[:\s]+(\d+)', subject)
            if not match_num:
                print(f"    Sujet non reconnu : {subject[:80]}")
                continue
            numero = match_num.group(1)
            filename = f"BonDeCommande_{numero}.pdf"

            # Extraire la date du créneau (DD/MM/YYYY) depuis l'objet pour le classement
            match_date = re.search(r'(\d{2}/\d{2}/\d{4})', subject)
            dossier_jj_mm = ""
            if match_date:
                dossier_jj_mm = match_date.group(1)[:5].replace('/', '_')  # DD_MM

            # Déjà traité : marquer quand même et ignorer
            if filename in traites:
                _marquer_email(gmail_svc, m['id'], label_id)
                continue

            # Chercher l'attachement bon_encaissement.pdf
            attachment_id = None
            for part in _iter_parts(msg['payload']):
                if part.get('filename', '').lower() == 'bon_encaissement.pdf':
                    attachment_id = part['body'].get('attachmentId')
                    break

            if not attachment_id:
                print(f"    Aucun bon_encaissement.pdf dans l'email pour cde {numero}")
                continue

            # Télécharger l'attachement
            cache_path = os.path.join(cache_dir, filename)
            if not os.path.exists(cache_path):
                att = gmail_svc.users().messages().attachments().get(
                    userId='me', messageId=m['id'], id=attachment_id
                ).execute()
                pdf_bytes = base64.urlsafe_b64decode(att['data'] + '==')
                with open(cache_path, 'wb') as f:
                    f.write(pdf_bytes)
                print(f"    ↓ {filename} OK")

            nouveaux[filename] = dossier_jj_mm
            _marquer_email(gmail_svc, m['id'], label_id)

        except Exception as e:
            print(f"    Erreur traitement email : {e}")

    return nouveaux


# ── Gmail — modifications / annulations client ───────────────────

def traiter_modifications_clients(drive_svc, gmail_svc, traites):
    """Lit les mails de modification de commande, supprime les anciens bons, archive les mails."""
    try:
        label_id = _get_or_create_gmail_label(gmail_svc, GMAIL_LABEL_NOM)
        q_modif  = f'subject:"Modification par le client de la commande" -label:{GMAIL_LABEL_NOM}'
        q_annul  = f'subject:"Alerte annulation par le client commande" -label:{GMAIL_LABEL_NOM}'
        q_annul2 = f'subject:"Alerte annulation commande" -label:{GMAIL_LABEL_NOM}'
        messages = []
        for q in [q_modif, q_annul, q_annul2]:
            res = gmail_svc.users().messages().list(
                userId='me', q=q, maxResults=50).execute()
            messages += res.get('messages', [])
    except Exception as e:
        print(f"  Gmail inaccessible ({e}) — modifications/annulations ignorées.")
        return

    if not messages:
        return

    print(f"  {len(messages)} mail(s) de modification/annulation à traiter.")
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
                print(f"  Modification : cde {num_ancien} → remplacée par {num_nouveau}")
                now = datetime.now()
                if now.weekday() == 6:
                    seuil = None
                elif now.weekday() == 5:
                    seuil = 5
                else:
                    seuil = 6
                if seuil is not None and now.hour >= seuil:
                    dt_orig = _get_heure_email_original(gmail_svc, num_ancien)
                    if dt_orig and dt_orig.date() == now.date() and dt_orig.hour < seuil:
                        contenu_antici = _telecharger_anticipation_drive(drive_svc, num_ancien)
                        if contenu_antici:
                            _envoyer_email_anticipation(gmail_svc, num_ancien, contenu_antici)
                _supprimer_bons_drive(drive_svc, num_ancien)
                _supprimer_bdc_drive(drive_svc, num_ancien)
                _uploader_annulation_drive(drive_svc, num_ancien)
                traites.add(f"BonDeCommande_{num_ancien}.pdf")
            elif match_annul:
                num_annule = match_annul.group(1)
                print(f"  Annulation : cde {num_annule} supprimée")
                _supprimer_bons_drive(drive_svc, num_annule)
                _supprimer_bdc_drive(drive_svc, num_annule)
                _uploader_annulation_drive(drive_svc, num_annule)
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


# ── Google Drive ───────────────────────────────────────────────────

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
    """Dépose un fichier dans DRIVE_BONS_FOLDER_ID, écrase s'il existe déjà."""
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

    media = MediaFileUpload(local_path, mimetype="text/plain", resumable=False)
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
        print(f"    {filename} → Drive OK")
        return True
    except Exception as e:
        print(f"    {filename} → Drive ÉCHEC : {e}")
        return False


# ── Fichiers de configuration (CSV) ──────────────────────────────

def telecharger_config_drive(drive_svc):
    """Télécharge les CSV de config depuis Drive vers WORK_DIR."""
    for filename in CONFIG_FILES:
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
        except Exception as e:
            print(f"  ERREUR config {filename} : {e}")


# ── Archivage BDC sur Drive ───────────────────────────────────────

def _get_or_create_subfolder(drive_svc, parent_id, name):
    """Retourne l'ID d'un sous-dossier, le crée si nécessaire."""
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
        print(f"    Création dossier Drive '{name}' échouée : {e}")
        return None


def archiver_pdf_drive(drive_svc, pdf_path, dossier_jj_mm):
    """Archive un PDF dans DRIVE_BDC_FOLDER_ID/JJ_MM/ sur Drive."""
    if not DRIVE_BDC_FOLDER_ID:
        return
    filename = os.path.basename(pdf_path)
    try:
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
        print(f"    {filename} → Drive BDC/{dossier_jj_mm}/ OK")
    except Exception as e:
        print(f"    Archivage Drive BDC/{dossier_jj_mm}/ échoué : {e}")


# ── Modifications client (Drive) ──────────────────────────────────

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
            print(f"    Supprimé Drive BDC : {nom}")
    except Exception as e:
        print(f"    Suppression Drive BDC {nom} échouée : {e}")


def _supprimer_bons_drive(drive_svc, numero):
    """Supprime bon_prepa_ et bon_anticipation_ d'un numéro donné dans DRIVE_BONS_FOLDER_ID."""
    for nom_fichier in [f"bon_prepa_{numero}.txt", f"bon_anticipation_{numero}.txt"]:
        try:
            res = drive_svc.files().list(
                q=f"name='{nom_fichier}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
                fields="files(id)",
            ).execute()
            for f in res.get("files", []):
                drive_svc.files().delete(fileId=f["id"]).execute()
                print(f"    Supprimé Drive : {nom_fichier}")
        except Exception as e:
            print(f"    Suppression {nom_fichier} échouée : {e}")


def _uploader_annulation_drive(drive_svc, numero):
    """Dépose annuler_NUMERO.txt dans DRIVE_BONS_FOLDER_ID pour déclencher la suppression sur le téléphone."""
    nom_fichier = f"annuler_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom_fichier}' and '{DRIVE_BONS_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        if res.get("files"):
            print(f"    Annulation déjà présente sur Drive : {nom_fichier}")
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
            print(f"    Annulation déposée sur Drive : {nom_fichier}")
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"    Upload annulation {nom_fichier} échoué : {e}")
        raise


# ── Email anticipation (modification commande jour J) ────────────

def _get_heure_email_original(gmail_svc, numero):
    """Retourne le datetime local de réception de l'email de confirmation original."""
    q = f'label:{GMAIL_LABEL_CONF} "{numero}"'
    try:
        res = gmail_svc.users().messages().list(userId='me', q=q, maxResults=1).execute()
        messages = res.get('messages', [])
        if not messages:
            return None
        msg = gmail_svc.users().messages().get(
            userId='me', id=messages[0]['id'], format='minimal').execute()
        return datetime.fromtimestamp(int(msg['internalDate']) / 1000)
    except Exception as e:
        print(f"    Horodatage email original {numero} introuvable : {e}")
        return None


def _telecharger_anticipation_drive(drive_svc, numero):
    """Télécharge et retourne le contenu de bon_anticipation_NUMERO.txt depuis Drive."""
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
        print(f"    Téléchargement anticipation {numero} échoué : {e}")
        return ""


def _envoyer_email_anticipation(gmail_svc, numero, contenu):
    """Envoie le contenu du bon d'anticipation supprimé par email."""
    from email.mime.text import MIMEText
    destinataire = "superu.arnage.drive@systeme-u.fr"
    sujet = f"Commande {numero} - anticipation renouvellée"
    try:
        msg = MIMEText(contenu, "plain", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = sujet
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email anticipation envoyé pour cde {numero} → {destinataire}")
    except Exception as e:
        print(f"    Envoi email anticipation {numero} échoué : {e}")


# ── Contrôle articles/produits ────────────────────────────────────

def extraire_articles_produits_pdf(texte):
    """Extrait (nb_articles, nb_produits) depuis les premières lignes du PDF."""
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


def log_ecart_drive(drive_svc, numero, articles_pdf, produits_pdf, articles_gen, produits_gen):
    from datetime import datetime
    ligne = (f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | cde {numero} | "
             f"PDF: {articles_pdf} art. / {produits_pdf} pdt. | "
             f"généré: {articles_gen} art. / {produits_gen} pdt.\n")
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
        print(f"    Log écart Drive échoué : {e}")


# ── Pipeline principal ────────────────────────────────────────────

LOCK_FILE = os.path.expanduser("~/.auto_prepa.lock")


def main():
    lock_f = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Une autre instance est déjà en cours d'exécution.")
        sys.exit(0)

    try:
        _main()
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def _main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    creds = get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)

    # Télécharger les fichiers de config depuis Drive
    telecharger_config_drive(drive_svc)

    # Mettre à jour chemin_prepa_ramasse.csv sur Drive (pour le téléphone)
    chemin_csv = os.path.join(WORK_DIR, "chemin_prepa_ramasse.csv")
    if os.path.exists(chemin_csv):
        upload_bon(drive_svc, chemin_csv)

    # 1. Charger la liste des bons déjà traités
    traites = charger_traites(drive_svc)

    # 1b. Traiter les modifications/annulations client reçues par mail
    traiter_modifications_clients(drive_svc, gmail_svc, traites)

    # 2. Télécharger les bons depuis les emails de confirmation Gmail
    nouveaux = telecharger_bons_email(gmail_svc, CACHE_DIR, traites)
    # nouveaux = {filename: dossier_jj_mm}

    if not nouveaux:
        print(f"Pas de nouvelle commande ({len(traites)} déjà traitée(s)).")
        return

    print(f"{len(nouveaux)} nouvelle(s) commande(s) détectée(s) :")
    for pdf in sorted(nouveaux):
        print(f"  • {pdf}")

    # 3. Traiter chaque nouveau PDF → bon_prepa_XXXXXXXX.txt
    os.makedirs(BDC_DIR, exist_ok=True)
    processed = set()

    for pdf, dossier_jj_mm in sorted(nouveaux.items()):
        order_num = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")

        # Archiver le PDF d'origine dans BDC/JJ_MM/ (local + Drive)
        bdc_subdir = os.path.join(BDC_DIR, dossier_jj_mm) if dossier_jj_mm else BDC_DIR
        os.makedirs(bdc_subdir, exist_ok=True)
        bdc_dst = os.path.join(bdc_subdir, pdf)
        cache_path = os.path.join(CACHE_DIR, pdf)
        if not os.path.exists(bdc_dst):
            shutil.copy2(cache_path, bdc_dst)
        if dossier_jj_mm:
            archiver_pdf_drive(drive_svc, cache_path, dossier_jj_mm)

        # Nettoyer tous les fichiers temporaires du C++ avant génération
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

        # Vérifier que les bases C++ sont présentes et non vides
        _bases_ok = True
        for csv_requis in ["gencod_adresses.csv", "gencod_nomenclatures.csv"]:
            fpath = os.path.join(WORK_DIR, csv_requis)
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                print(f"  ERREUR CRITIQUE : {csv_requis} absent ou vide dans {WORK_DIR}")
                _bases_ok = False
                break
        if not _bases_ok:
            break

        # Vérifier que pdftotext arrive à lire le PDF
        pdf_path = os.path.join(WORK_DIR, pdf)
        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            print(f"  ÉCHEC pdftotext — PDF vide ou non lisible : {pdf}")
            os.remove(pdf_path)
            processed.add(pdf)
            continue

        # Extraire articles et produits depuis le PDF pour contrôle ultérieur
        articles_pdf, produits_pdf = extraire_articles_produits_pdf(pt.stdout)

        # Extraire le montant depuis le texte du PDF
        montant_pdf = ""
        for _ligne in pt.stdout.splitlines():
            if "Montant initial" in _ligne:
                _m = re.search(r'(\d+[.,]\d+)', _ligne)
                if _m:
                    montant_pdf = _m.group(1).replace(',', '.')
                break

        print(f"  [{order_num}] Génération...", end="", flush=True)
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

        # Vérifier que le bon_prepa généré est non vide
        bon_prepa_path = os.path.join(WORK_DIR, "bon_prepa.txt")
        if not os.path.exists(bon_prepa_path) or os.path.getsize(bon_prepa_path) == 0:
            print(f" VIDE — bon_prepa.txt absent ou vide")
            if r.stdout: print(f"    sortie C++ : {r.stdout[:300]}")
            processed.add(pdf)
            continue
        print(" OK")

        # Injecter le montant et nettoyer les préfixes "-N;" parasites du C++
        with open(bon_prepa_path, 'r', encoding='utf-8') as f:
            lignes = f.readlines()
        if lignes:
            if montant_pdf:
                lignes[0] = lignes[0].rstrip('\n') + ',' + montant_pdf + '\n'
            lignes[1:] = [re.sub(r'^-\d+;(\d{13};)', r'\1', l) for l in lignes[1:]]
        with open(bon_prepa_path, 'w', encoding='utf-8') as f:
            f.writelines(lignes)

        # Contrôle articles/produits : PDF vs généré
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

        # Renommer les sorties avec le numéro de commande
        for src_name, dst_name in [
            ("bon_prepa.txt",        f"bon_prepa_{order_num}.txt"),
            ("bon_anticipation.txt", f"bon_anticipation_{order_num}.txt"),
        ]:
            src_f = os.path.join(WORK_DIR, src_name)
            dst_f = os.path.join(WORK_DIR, dst_name)
            if os.path.exists(src_f):
                os.rename(src_f, dst_f)

        # Upload vers Drive puis suppression locale
        for fname in [f"bon_prepa_{order_num}.txt",
                      f"bon_anticipation_{order_num}.txt"]:
            fpath = os.path.join(WORK_DIR, fname)
            if os.path.exists(fpath):
                if upload_bon(drive_svc, fpath):
                    os.remove(fpath)

        # Nettoyer le PDF de travail (déjà dans le cache)
        pdf_work = os.path.join(WORK_DIR, pdf)
        if os.path.exists(pdf_work):
            os.remove(pdf_work)

        processed.add(pdf)

    # 4. Sauvegarder l'état dans Drive
    sauvegarder_traites(drive_svc, traites | processed)


if __name__ == "__main__":
    main()
