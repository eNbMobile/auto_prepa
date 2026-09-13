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
import urllib.request
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
DEBUG_RAW_DIR = os.environ.get("DEBUG_RAW_DIR")  # si defini, dump diagnostic de la sortie brute de prepa_drive_degrade
TOKEN_FILE = os.path.expanduser("~/.auto_prepa_token.json")
CREDS_FILE = os.path.expanduser("~/.auto_prepa_credentials.json")
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
EMAIL_ANTICIPATION_2 = ""
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

def telecharger_bons_email(gmail_svc, cache_dir, drive_svc=None):
    """
    Lit les emails de confirmation (no-reply@systeme-u.fr),
    telecharge bon_encaissement.pdf => BonDeCommande_XXX.pdf dans cache_dir.
    Retourne {filename: (dossier_jj_mm, dossier_mm_aaaa)} pour les nouveaux PDFs telecharges.

    `drive_svc` (facultatif) sert a ecarter les commandes deja preparees a
    partir d'un bon depose dans le dossier de traitement manuel, dont l'email
    de confirmation finit malgre tout par arriver.
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

            # Commande deja preparee depuis un bon depose dans le dossier de
            # traitement manuel : son email de confirmation, arrive apres coup,
            # ne doit pas la faire traiter une seconde fois.
            if _preparee_depuis_depot_manuel(drive_svc, numero):
                print(f"    Commande {numero} deja preparee depuis un bon depose "
                      f"a la main : email ignore.")
                _marquer_email(gmail_svc, m['id'], label_id)
                continue

            match_date = re.search(r'(\d{2}/\d{2}/\d{4})', subject)
            dossier_jj_mm = ""
            dossier_mm_aaaa = ""
            if match_date:
                dossier_jj_mm   = match_date.group(1)[:5].replace('/', '_')   # DD_MM
                dossier_mm_aaaa = match_date.group(1)[3:].replace('/', '_')   # MM_AAAA

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

# ---------------------------------------------------------------------------
# Bons de commande deposes manuellement sur Drive
# ---------------------------------------------------------------------------
# Il arrive, tres rarement, qu'aucun email de confirmation ne soit recu pour
# une commande : sans email, telecharger_bons_email ne la voit jamais et elle
# n'est donc jamais preparee. Filet de secours : deposer a la main le bon
# d'encaissement PDF dans le dossier Drive GITHUB/BDC/Traitement manuel (ou
# GITHUB/MobUDrive_Bons/Traitement manuel). Chaque run le recupere et le
# traite exactement comme une piece jointe d'email : numero de commande et
# date de livraison sont alors lus dans le PDF lui-meme, a defaut de sujet
# d'email. Une fois la commande traitee, le depot est mis a la corbeille pour
# ne pas etre repris au run suivant (le PDF reste archive par
# archiver_pdf_drive dans BDC/MM_AAAA/JJ_MM).
DOSSIER_TRAITEMENT_MANUEL = "Traitement manuel"

# Entete du bon d'encaissement : "Commande : 54868421 - H9 ... LIVRAISON ..."
_RE_NUMERO_PDF = re.compile(r'Commande\s*:\s*(\d{6,})')
_RE_NUMERO_NOM = re.compile(r'BonDeCommande[_\- ]*(\d{6,})', re.IGNORECASE)


def _dossier_traitement_manuel(drive_svc):
    """Retourne l'ID du sous-dossier de depot manuel, cherche dans le dossier
    Drive BDC puis dans le dossier des bons. Comparaison insensible a la casse
    ('Traitement manuel' / 'traitement manuel'). None s'il n'existe pas."""
    for parent_id in (DRIVE_BDC_FOLDER_ID, DRIVE_BONS_FOLDER_ID):
        if not parent_id:
            continue
        try:
            res = drive_svc.files().list(
                q=(f"'{parent_id}' in parents "
                   f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
                fields="files(id,name)",
            ).execute()
        except Exception as e:
            print(f"  Dossier '{DOSSIER_TRAITEMENT_MANUEL}' inaccessible : {e}")
            continue
        for f in res.get("files", []):
            if f.get("name", "").strip().casefold() == DOSSIER_TRAITEMENT_MANUEL.casefold():
                return f["id"]
    return None


def _numero_bon_depose(nom_fichier, texte_pdf):
    """Numero de commande d'un bon depose manuellement : lu dans le nom du
    fichier (BonDeCommande_NUMERO.pdf), sinon dans l'entete du PDF
    ("Commande : 54868421 - ..."), sinon dans tout nombre assez long du nom
    (le fichier peut avoir ete renomme a la main)."""
    m = _RE_NUMERO_NOM.search(nom_fichier)
    if m:
        return m.group(1)
    m = _RE_NUMERO_PDF.search(texte_pdf)
    if m:
        return m.group(1)
    m = re.search(r'(\d{6,})', nom_fichier)
    return m.group(1) if m else ""


def _commande_deja_traitee(drive_svc, numero, ignorer_parents=()):
    """Vrai si la commande a deja ete preparee, et ne doit donc pas l'etre une
    seconde fois : elle ressortirait sinon en double dans l'anticipation, la
    livraison et le suivi des avoirs. Cas vise : une commande arrivee par les
    deux voies, un bon depose a la main puis l'arrivee tardive de son email de
    confirmation (ou l'inverse).

    Deux conditions, dans cet ordre : son BonDeCommande_NUMERO.pdf est archive
    sur Drive ailleurs que dans `ignorer_parents` (le dossier de depot manuel),
    test rapide et negatif pour toute commande nouvelle ; ET elle figure dans
    le suivi Avoir/Commandes en cours. Le second test evite de tenir pour
    traitee une commande dont seul le PDF a ete archive, la generation du bon
    ayant echoue juste apres (traiter_commande_pdf archive avant de generer) :
    celle-la doit au contraire etre retentee au run suivant."""
    if not drive_svc or not numero:
        return False
    nom = f"BonDeCommande_{numero}.pdf"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and trashed=false",
            fields="files(id,parents)",
        ).execute()
    except Exception as e:
        print(f"    Recherche de {nom} sur Drive echouee : {e}")
        return False
    archive = False
    for f in res.get("files", []):
        parents = f.get("parents") or []
        if any(p in ignorer_parents for p in parents):
            continue
        archive = True
        break
    return archive and _commande_dans_suivi_avoir(drive_svc, numero)


def _archiver_depot_manuel(drive_svc, file_id, nom_fichier, motif):
    """Met a la corbeille un bon depose manuellement (restaurable depuis Drive,
    et de toute facon archive dans BDC/MM_AAAA/JJ_MM), pour qu'il ne soit pas
    repris a chaque run.

    Le depot est renomme au passage en BonDeCommande_NUMERO.pdf (`nom_fichier`,
    toujours le nom canonique cote appelant) : c'est cette trace, dans la
    corbeille du dossier de depot, que _preparee_depuis_depot_manuel relit pour
    reconnaitre une commande preparee a la main — un bon depose sous un nom
    quelconque ("bon_encaissement (1).pdf") resterait sinon introuvable."""
    try:
        drive_svc.files().update(
            fileId=file_id, body={"trashed": True, "name": nom_fichier}).execute()
        print(f"    {nom_fichier} : depot manuel mis a la corbeille ({motif}).")
    except Exception as e:
        print(f"    Mise a la corbeille du depot manuel {nom_fichier} echouee : {e}")


def _preparee_depuis_depot_manuel(drive_svc, numero):
    """Vrai si la commande a deja ete preparee a partir d'un bon depose a la
    main dans le dossier de traitement manuel — seul cas ou son email de
    confirmation, arrive apres coup, doit etre ignore : le traiter ferait
    ressortir la commande en double dans l'anticipation, la livraison et le
    suivi des avoirs.

    Deux traces exigees : le depot lui-meme, mis a la corbeille (jamais
    supprime) sous le nom BonDeCommande_NUMERO.pdf une fois la commande
    traitee ; ET une preparation reellement aboutie (_commande_deja_traitee),
    pour ne pas ecarter l'email d'une commande dont le depot a ete jete sans
    que le bon ait pu etre genere.

    Ce test remplace l'appel direct a _commande_deja_traitee : celui-ci
    ecartait aussi les emails REPLACES a la main en boite de reception pour
    faire regenerer un bon (gencod_adresses/gencod_nomenclatures mis a jour),
    laissant les commandes concernees marquees traitees sans etre reprises."""
    if not drive_svc or not numero:
        return False
    dossier_id = _dossier_traitement_manuel(drive_svc)
    if not dossier_id:
        return False
    try:
        res = drive_svc.files().list(
            q=(f"name='BonDeCommande_{numero}.pdf' and '{dossier_id}' in parents "
               f"and trashed=true"),
            fields="files(id)",
        ).execute()
    except Exception as e:
        print(f"    Recherche du depot manuel de {numero} echouee : {e}")
        return False
    if not res.get("files"):
        return False
    return _commande_deja_traitee(drive_svc, numero, ignorer_parents=(dossier_id,))


def telecharger_bons_traitement_manuel(drive_svc, cache_dir):
    """Recupere les bons de commande deposes a la main dans le dossier Drive de
    traitement manuel et les prepare comme ceux recus par email.

    Retourne ({filename: (dossier_jj_mm, dossier_mm_aaaa)}, {filename: file_id})
    ou file_id est l'identifiant Drive du depot, a mettre a la corbeille via
    _archiver_depot_manuel une fois la commande effectivement traitee."""
    dossier_id = _dossier_traitement_manuel(drive_svc)
    if not dossier_id:
        return {}, {}

    try:
        res = drive_svc.files().list(
            q=(f"'{dossier_id}' in parents and mimeType='application/pdf' "
               f"and trashed=false"),
            fields="files(id,name)",
        ).execute()
        fichiers = res.get("files", [])
    except Exception as e:
        print(f"  Dossier '{DOSSIER_TRAITEMENT_MANUEL}' illisible ({e})")
        return {}, {}

    if not fichiers:
        return {}, {}

    print(f"  {len(fichiers)} bon(s) a traiter dans '{DOSSIER_TRAITEMENT_MANUEL}'.")
    nouveaux = {}   # {filename: (dossier_jj_mm, dossier_mm_aaaa)}
    depots = {}     # {filename: file_id du depot Drive}

    for f in fichiers:
        nom_depot = f.get("name", "")
        tmp_path = os.path.join(cache_dir, f"depot_manuel_{f['id']}.pdf")
        try:
            download_pdf(drive_svc, f["id"], tmp_path)
            texte = subprocess.run(["pdftotext", "-layout", tmp_path, "-"],
                                   capture_output=True, text=True).stdout
            if not texte.strip():
                print(f"    {nom_depot} : PDF vide ou illisible, ignore.")
                continue

            numero = _numero_bon_depose(nom_depot, texte)
            if not numero:
                print(f"    {nom_depot} : numero de commande introuvable "
                      f"(ni dans le nom du fichier, ni dans le PDF), ignore.")
                continue

            if _commande_deja_traitee(drive_svc, numero, ignorer_parents=(dossier_id,)):
                print(f"    {nom_depot} : commande {numero} deja traitee.")
                _archiver_depot_manuel(drive_svc, f["id"], nom_depot,
                                       "commande deja traitee")
                continue

            _, _, _, date_cde, _ = extraire_client_creneau_pdf(texte)
            if not date_cde:
                print(f"    {nom_depot} : date de retrait/livraison introuvable "
                      f"dans le PDF, ignore.")
                continue

            filename = f"BonDeCommande_{numero}.pdf"
            os.replace(tmp_path, os.path.join(cache_dir, filename))
            nouveaux[filename] = (date_cde[:5].replace('/', '_'),    # JJ_MM
                                  date_cde[3:].replace('/', '_'))    # MM_AAAA
            depots[filename] = f["id"]
            print(f"    => {filename} OK (depot manuel, livraison {date_cde})")

        except Exception as e:
            print(f"    Erreur traitement du depot manuel {nom_depot} : {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return nouveaux, depots


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
    """Si la commande annulee ou remplacee etait une LIVRAISON, supprime sa
    ligne dans LIVRAISON DRIVE 2026. Nom/prenom/date sont extraits de
    l'archive BDC Drive, seule source encore disponible a ce stade (le mail
    d'annulation/remplacement ne contient que le numero de commande).
    Retourne (nom, prenom, date_cde) si une ligne a effectivement ete
    supprimee (la commande etait bien une LIVRAISON) — utile a l'appelant
    pour la reinscrire sous le nouveau numero en cas de remplacement — None
    sinon (commande non-LIVRAISON, ou archive introuvable/illisible)."""
    pdf_path = _telecharger_bdc_archive_drive(drive_svc, numero)
    if not pdf_path:
        return None
    try:
        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            print(f"    ECHEC pdftotext sur l'archive BDC {numero}, annulation livraison ignoree.")
            return None
        civilite, nom, prenom, date_cde, creneau = extraire_client_creneau_pdf(pt.stdout)
        if livraison_drive.annuler_commande_livraison(
                sheets_svc, LIVRAISON_SPREADSHEET_ID, nom, prenom, date_cde, numero_commande=numero):
            return nom, prenom, date_cde
        return None
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


def _traiter_commande_potentiellement_anticipee(drive_svc, gmail_svc, numero, numero_remplacement=None):
    """Si la commande annulee (numero, remplacee par numero_remplacement le cas
    echeant) a pu etre anticipee, la retire de l'anticipation de sa VRAIE date
    de livraison (extraite du sujet de son email de confirmation original via
    _infos_email_original — et non de la date du jour ou l'annulation est
    traitee, qui peut differer de plusieurs jours quand la commande a ete
    passee a l'avance ; c'etait le bug de la version precedente, laissant des
    commandes annulees/remplacees en double dans l'anticipation d'un jour
    different de celui ou l'annulation etait traitee) : renvoie par email son
    bon d'anticipation individuel s'il existe encore sur Drive, alerte si elle
    etait deja marquee comme anticipee ce jour-la, et retire retroactivement
    son anticipation du brouillon du jour si elle y a deja ete integree
    (marqueur Drive + dispatch async, cf. declencher_retrait_anticipation) —
    pour qu'une commande annulee ne soit plus jamais preparee ni visible dans
    l'anticipation, meme quand l'assemblage a eu lieu avant l'annulation.
    L'inscription au registre des annulations (enregistrer_commande_annulee)
    est faite en premier et sans condition : c'est la seule protection qui ne
    depend pas de la date de livraison, et donc la seule qui couvre le cas ou
    l'annulation arrive avant meme que la commande n'ait ete traitee.
    Sans date de livraison exploitable (email de confirmation introuvable —
    typiquement pas encore traite — et aucun bon d'anticipation deja archive),
    le nettoyage du brouillon du jour est impossible faute de savoir quel
    dossier viser : le registre prend alors le relais, cote assemblage."""
    enregistrer_commande_annulee(drive_svc, numero)

    _, dossier_jj_mm, dossier_mm_aaaa = _infos_email_original(gmail_svc, numero)
    if not dossier_jj_mm or not dossier_mm_aaaa:
        dossier_jj_mm, dossier_mm_aaaa = _dossier_jour_anticipation_du_numero(drive_svc, numero)
    if not dossier_jj_mm or not dossier_mm_aaaa:
        print(f"    Date de livraison de {numero} inconnue : nettoyage du brouillon "
              f"d'anticipation reporte (registre des annulations pris en compte "
              f"a l'assemblage).")
        return

    contenu_antici = _telecharger_anticipation_drive(drive_svc, numero)
    if contenu_antici:
        _envoyer_email_anticipation(gmail_svc, numero, contenu_antici)

    _alerter_si_commande_anticipee_annulee(
        drive_svc, gmail_svc, numero, dossier_jj_mm, dossier_mm_aaaa, numero_remplacement)

    _marquer_retrait_anticipation_drive(drive_svc, numero, dossier_mm_aaaa, dossier_jj_mm)
    declencher_retrait_anticipation(numero, dossier_jj_mm, dossier_mm_aaaa)


def traiter_modifications_clients(drive_svc, gmail_svc, sheets_svc,
                                   shopopop_token=None, shopopop_drive_id=None, shopopop_connecte=False):
    """Lit les mails de modification de commande, supprime les anciens bons, archive les mails.
    Retourne (shopopop_token, shopopop_drive_id, shopopop_connecte), a jour si une
    connexion Shopopop a ete etablie ici (reinscription d'un remplacement en
    LIVRAISON), pour que l'appelant la reutilise sans se reconnecter."""
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
        return shopopop_token, shopopop_drive_id, shopopop_connecte

    if not messages:
        return shopopop_token, shopopop_drive_id, shopopop_connecte

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
                _traiter_commande_potentiellement_anticipee(drive_svc, gmail_svc, num_ancien, num_nouveau)
                resultat_livraison = _traiter_annulation_livraison(drive_svc, sheets_svc, num_ancien)
                if resultat_livraison:
                    nom_l, prenom_l, date_l = resultat_livraison
                    if not shopopop_connecte:
                        shopopop_token, shopopop_drive_id = livraison_drive.connecter_shopopop(drive_svc)
                        shopopop_connecte = True
                    km_manquant = livraison_drive.traiter_commande_livraison(
                        sheets_svc, LIVRAISON_SPREADSHEET_ID, nom_l, prenom_l, date_l,
                        numero_commande=num_nouveau,
                        shopopop_token=shopopop_token, shopopop_drive_id=shopopop_drive_id)
                    if km_manquant:
                        _envoyer_email_km_manquant(gmail_svc, num_nouveau, nom_l, prenom_l, date_l)
                _supprimer_bons_drive(drive_svc, num_ancien)
                _supprimer_anticipation_archive_drive(drive_svc, num_ancien)
                _supprimer_bdc_drive(drive_svc, num_ancien)
                _uploader_annulation_drive(drive_svc, num_ancien)
                supprimer_commande_avoir_drive(drive_svc, num_ancien)
            elif match_annul:
                num_annule = match_annul.group(1)
                print(f"  Annulation : cde {num_annule} supprimee")
                _traiter_commande_potentiellement_anticipee(drive_svc, gmail_svc, num_annule)
                _traiter_annulation_livraison(drive_svc, sheets_svc, num_annule)
                _supprimer_bons_drive(drive_svc, num_annule)
                _supprimer_anticipation_archive_drive(drive_svc, num_annule)
                _supprimer_bdc_drive(drive_svc, num_annule)
                _uploader_annulation_drive(drive_svc, num_annule)
                supprimer_commande_avoir_drive(drive_svc, num_annule)
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

    return shopopop_token, shopopop_drive_id, shopopop_connecte

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

def _dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm, archives=False, creer=True):
    """Retourne l'ID du dossier Drive GITHUB/Anticipation/[archives/]MM_AAAA/JJ_MM,
    en le creant si necessaire (creer=True) ou en le recherchant seulement
    (creer=False, retourne None si un niveau du chemin n'existe pas encore)."""
    def _sous_dossier(parent_id, nom):
        if not parent_id:
            return None
        if creer:
            return _get_or_create_subfolder(drive_svc, parent_id, nom)
        res = drive_svc.files().list(
            q=(f"name='{nom}' and '{parent_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    github_id = _sous_dossier("root", "GITHUB")
    anticipation_id = _sous_dossier(github_id, "Anticipation")
    base_id = anticipation_id
    if archives:
        base_id = _sous_dossier(anticipation_id, "archives")
    mois_id = _sous_dossier(base_id, dossier_mm_aaaa)
    return _sous_dossier(mois_id, dossier_jj_mm)


def archiver_anticipation_drive(drive_svc, anticipation_path, dossier_jj_mm, dossier_mm_aaaa,
                                ecraser=False):
    """Copie bon_anticipation_NUMERO.txt dans Drive GITHUB/Anticipation/MM_AAAA/JJ_MM/.

    Le fichier deja archive est conserve tel quel, sauf `ecraser` : c'est le cas
    d'une commande regeneree apres mise a jour des gencod, dont l'anticipation
    archivee porte encore les anciennes adresses."""
    if not dossier_jj_mm or not dossier_mm_aaaa:
        return
    filename = os.path.basename(anticipation_path)
    path = f"GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}"
    try:
        subfolder_id = _dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm)
        if not subfolder_id:
            return
        res = drive_svc.files().list(
            q=f"name='{filename}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existant = res.get("files", [])
        if existant and not ecraser:
            return
        media = MediaFileUpload(anticipation_path, mimetype="text/plain", resumable=False)
        if existant:
            drive_svc.files().update(fileId=existant[0]["id"], media_body=media).execute()
            print(f"    {filename} => Drive {path}/ mis a jour")
            return
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
        subfolder_id = _dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm, archives=True)
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

def deposer_fichier_jour_anticipation(drive_svc, local_path, dossier_mm_aaaa, dossier_jj_mm):
    """Depose/ecrase, dans Drive GITHUB/Anticipation/MM_AAAA/JJ_MM/, un fichier
    'brouillon' tenu a jour au fil des commandes (bon_anticipation_JJ_MM.txt
    assemble, ou son PDF anticipation_JJ_MM.pdf) — a distinguer du resultat
    final depose par archiver_resultat_anticipation_drive dans archives/."""
    filename = os.path.basename(local_path)
    path = f"GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}"
    try:
        subfolder_id = _dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm)
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
        print(f"    Depot Drive {path}/ echoue : {e}")
        return False

def declencher_assemblage_anticipation(numero, dossier_jj_mm, dossier_mm_aaaa):
    """Declenche en fire-and-forget (repository_dispatch) le workflow GitHub
    anticipation_assemble.yml, qui integre bon_anticipation_{numero}.txt dans
    le fichier du jour bon_anticipation_JJ_MM.txt et regenere son PDF
    brouillon. Fait dans un workflow separe (et non ici) car l'assemblage —
    telechargement/reupload Drive, generation PDF avec photos et
    codes-barres — prend du temps, et aut_prep tourne toutes les minutes :
    le faire ici bloquerait le run suivant."""
    if not dossier_jj_mm or not dossier_mm_aaaa:
        return
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        print("    Assemblage anticipation non declenche (GITHUB_TOKEN/GH_PAT/GITHUB_REPOSITORY manquant).")
        return
    url = f"https://api.github.com/repos/{repo}/dispatches"
    body = json.dumps({
        "event_type": "anticipation_assemble",
        "client_payload": {
            "numero": numero,
            "dossier_jj_mm": dossier_jj_mm,
            "dossier_mm_aaaa": dossier_mm_aaaa,
        },
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"    Assemblage anticipation declenche (cde {numero})")
    except Exception as e:
        print(f"    Declenchement assemblage anticipation {numero} echoue : {e}")

def _marquer_retrait_anticipation_drive(drive_svc, numero, dossier_mm_aaaa, dossier_jj_mm):
    """Depose un marqueur annuler_anticipation_NUMERO.txt dans Drive
    GITHUB/Anticipation/MM_AAAA/JJ_MM/ (cree si besoin), pour que
    retirer_anticipation.py retire retroactivement cette commande du
    brouillon d'anticipation du jour (bon_anticipation_JJ_MM.txt) si elle y a
    deja ete integree. Marqueur persistant plutot qu'un simple appel direct :
    resiste a un dispatch perdu (meme concurrency group que anticipation_assemble,
    cf. son commentaire sur les runs qui peuvent sauter) puisque le prochain
    retrait declenche, meme pour une autre commande, le retrouvera et le
    traitera."""
    folder_id = _dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm)
    if not folder_id:
        return
    nom_fichier = f"annuler_anticipation_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom_fichier}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        if res.get("files"):
            return
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False, encoding="utf-8") as f:
            f.write(numero)
            tmp = f.name
        try:
            media = MediaFileUpload(tmp, mimetype="text/plain", resumable=False)
            drive_svc.files().create(
                body={"name": nom_fichier, "parents": [folder_id]},
                media_body=media, fields="id",
            ).execute()
            print(f"    Retrait anticipation marque sur Drive : {nom_fichier}")
        finally:
            os.remove(tmp)
    except Exception as e:
        print(f"    Marquage retrait anticipation {numero} echoue : {e}")

def declencher_retrait_anticipation(numero, dossier_jj_mm, dossier_mm_aaaa):
    """Declenche en fire-and-forget (repository_dispatch) le workflow GitHub
    anticipation_retirer.yml, qui retire du brouillon d'anticipation du jour
    (bon_anticipation_JJ_MM.txt + PDF) toute commande marquee par
    _marquer_retrait_anticipation_drive (celle-ci comprise) : meme
    architecture (et meme concurrency group, pour ne jamais tourner en
    parallele d'un assemblage sur le meme fichier) que
    declencher_assemblage_anticipation, cf. son docstring."""
    if not dossier_jj_mm or not dossier_mm_aaaa:
        return
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        print("    Retrait anticipation non declenche (GITHUB_TOKEN/GH_PAT/GITHUB_REPOSITORY manquant).")
        return
    url = f"https://api.github.com/repos/{repo}/dispatches"
    body = json.dumps({
        "event_type": "anticipation_retirer",
        "client_payload": {
            "numero": numero,
            "dossier_jj_mm": dossier_jj_mm,
            "dossier_mm_aaaa": dossier_mm_aaaa,
        },
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"    Retrait anticipation declenche (cde {numero})")
    except Exception as e:
        print(f"    Declenchement retrait anticipation {numero} echoue : {e}")

def _supprimer_anticipation_archive_drive(drive_svc, numero):
    """Met a la corbeille la copie de bon_anticipation_NUMERO.txt archivee sous
    GITHUB/Anticipation/ (trashed=True plutot que suppression definitive, pour
    rester restaurable depuis Drive)."""
    nom = f"bon_anticipation_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and trashed=false",
            fields="files(id,parents)",
        ).execute()
        for f in res.get("files", []):
            if DRIVE_BONS_FOLDER_ID and DRIVE_BONS_FOLDER_ID in (f.get("parents") or []):
                continue
            drive_svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
            print(f"    Mis a la corbeille Drive GITHUB/Anticipation : {nom}")
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


# ---------------------------------------------------------------------------
# Registre persistant des commandes annulees / remplacees
# ---------------------------------------------------------------------------
# Fichier Drive GITHUB/Annulations/commandes_annulees.txt : une ligne
# "NUMERO;AAAA-MM-JJ" par commande annulee ou remplacee, purgee au-dela de
# _RETENTION_ANNULATIONS_JOURS.
#
# Pourquoi ce registre, en plus des marqueurs annuler_anticipation_NUMERO.txt
# deposes dans le dossier du jour : ces marqueurs supposent qu'on connaisse la
# DATE DE LIVRAISON de la commande annulee, lue dans le sujet de son email de
# confirmation d'origine (_infos_email_original). Or cet email n'est pas
# toujours deja traite quand l'annulation arrive : un client qui modifie sa
# commande dans la foulee genere le mail de modification AVANT que
# telecharger_bons_email n'ait traite la confirmation initiale — et
# traiter_modifications_clients tourne avant telecharger_bons_email dans
# main(). Dans ce cas l'ancienne version n'a aucun marqueur possible, puis
# elle est traitee normalement quelques lignes plus bas : son bon
# d'anticipation est genere et assemble APRES son annulation, ce qui la fait
# apparaitre en double (ancien + nouveau numero) dans l'anticipation du jour.
# Le registre, lui, ne depend d'aucune date : il est consulte avant tout
# traitement de commande (main) et a chaque etape de l'anticipation
# (assemblage, retrait, envoi), quel que soit l'ordre d'arrivee des emails.
_RETENTION_ANNULATIONS_JOURS = 60
_FICHIER_ANNULATIONS = "commandes_annulees.txt"


def _dossier_annulations(drive_svc, creer=True):
    """Retourne l'ID du dossier Drive GITHUB/Annulations (cree si besoin)."""
    try:
        if creer:
            github_id = _get_or_create_subfolder(drive_svc, "root", "GITHUB")
            if not github_id:
                return None
            return _get_or_create_subfolder(drive_svc, github_id, "Annulations")
        parent = "root"
        for nom in ("GITHUB", "Annulations"):
            res = drive_svc.files().list(
                q=(f"name='{nom}' and '{parent}' in parents "
                   f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
                fields="files(id)",
            ).execute()
            files = res.get("files", [])
            if not files:
                return None
            parent = files[0]["id"]
        return parent
    except Exception as e:
        print(f"    Dossier Drive GITHUB/Annulations introuvable : {e}")
        return None


def _lire_registre_annulations(drive_svc, creer=False):
    """Retourne ({numero: 'AAAA-MM-JJ'}, file_id ou None) du registre Drive."""
    folder_id = _dossier_annulations(drive_svc, creer=creer)
    if not folder_id:
        return {}, None
    try:
        res = drive_svc.files().list(
            q=(f"name='{_FICHIER_ANNULATIONS}' and '{folder_id}' in parents "
               f"and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return {}, None
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        contenu = buf.getvalue().decode("utf-8", errors="replace")
        registre = {}
        for ligne in contenu.splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            numero, _, jour = ligne.partition(";")
            numero = numero.strip()
            if numero:
                registre[numero] = jour.strip()
        return registre, files[0]["id"]
    except Exception as e:
        print(f"    Lecture {_FICHIER_ANNULATIONS} echouee : {e}")
        return {}, None


def _ecrire_registre_annulations(drive_svc, registre, file_id):
    """(Re)ecrit le registre Drive, purge des entrees trop anciennes."""
    limite = (datetime.now(_TZ).date() - timedelta(days=_RETENTION_ANNULATIONS_JOURS)).isoformat()
    lignes = [f"{num};{jour}" for num, jour in sorted(registre.items())
              if not jour or jour >= limite]
    contenu = "\n".join(lignes) + "\n"

    folder_id = _dossier_annulations(drive_svc, creer=True)
    if not folder_id:
        return False
    os.makedirs(WORK_DIR, exist_ok=True)
    chemin = os.path.join(WORK_DIR, _FICHIER_ANNULATIONS)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(contenu)
    try:
        media = MediaFileUpload(chemin, mimetype="text/plain", resumable=False)
        if file_id:
            drive_svc.files().update(fileId=file_id, media_body=media).execute()
        else:
            drive_svc.files().create(
                body={"name": _FICHIER_ANNULATIONS, "parents": [folder_id]},
                media_body=media, fields="id",
            ).execute()
        return True
    except Exception as e:
        print(f"    Ecriture {_FICHIER_ANNULATIONS} echouee : {e}")
        return False
    finally:
        if os.path.exists(chemin):
            os.remove(chemin)


def enregistrer_commande_annulee(drive_svc, numero):
    """Inscrit definitivement (fenetre de retention) la commande annulee ou
    remplacee dans le registre Drive, pour qu'elle ne soit plus jamais
    traitee ni anticipee, meme si son email de confirmation n'a pas encore
    ete traite au moment de l'annulation."""
    try:
        registre, file_id = _lire_registre_annulations(drive_svc, creer=True)
        if numero in registre:
            return
        registre[numero] = datetime.now(_TZ).date().isoformat()
        if _ecrire_registre_annulations(drive_svc, registre, file_id):
            print(f"    Commande {numero} inscrite au registre des annulations.")
    except Exception as e:
        print(f"    Inscription de {numero} au registre des annulations echouee : {e}")


def commandes_annulees(drive_svc):
    """Numeros des commandes annulees/remplacees encore dans la fenetre de
    retention. Set vide si le registre est illisible (on retombe alors sur le
    comportement d'avant : aucun filtrage)."""
    registre, _ = _lire_registre_annulations(drive_svc)
    limite = (datetime.now(_TZ).date() - timedelta(days=_RETENTION_ANNULATIONS_JOURS)).isoformat()
    return {num for num, jour in registre.items() if not jour or jour >= limite}


def _ecarter_commandes_annulees(drive_svc, nouveaux):
    """Retire des commandes a traiter celles deja annulees/remplacees (leur
    email de confirmation etait encore non traite quand l'annulation est
    arrivee). Sans ce filtre, la commande annulee serait preparee et anticipee
    apres coup — c'est ce qui laissait ancien et nouveau numero en double dans
    l'anticipation apres une modification de commande."""
    if not nouveaux:
        return nouveaux
    annulees = commandes_annulees(drive_svc)
    if not annulees:
        return nouveaux
    retenus = {}
    for pdf, infos in nouveaux.items():
        numero = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")
        if numero in annulees:
            print(f"  Commande {numero} annulee/remplacee : traitement ignore "
                  f"(registre des annulations).")
            cache_path = os.path.join(CACHE_DIR, pdf)
            if os.path.exists(cache_path):
                os.remove(cache_path)
            continue
        retenus[pdf] = infos
    return retenus


def _dossier_jour_anticipation_du_numero(drive_svc, numero):
    """Retrouve (dossier_jj_mm, dossier_mm_aaaa) a partir de l'emplacement du
    bon_anticipation_NUMERO.txt archive sous GITHUB/Anticipation/MM_AAAA/JJ_MM/.
    Filet quand l'email de confirmation d'origine est introuvable (donc sa
    date de livraison inconnue) : sans lui, une commande annulee restait dans
    le brouillon d'anticipation, faute de savoir quel dossier nettoyer."""
    nom = f"bon_anticipation_{numero}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom}' and trashed=false",
            fields="files(id,parents)",
        ).execute()
        for f in res.get("files", []):
            for parent_id in (f.get("parents") or []):
                if DRIVE_BONS_FOLDER_ID and parent_id == DRIVE_BONS_FOLDER_ID:
                    continue
                jour = drive_svc.files().get(fileId=parent_id, fields="name,parents").execute()
                if not re.fullmatch(r"\d{2}_\d{2}", jour.get("name", "")):
                    continue
                for grand_parent_id in (jour.get("parents") or []):
                    mois = drive_svc.files().get(fileId=grand_parent_id, fields="name").execute()
                    if re.fullmatch(r"\d{2}_\d{4}", mois.get("name", "")):
                        return jour["name"], mois["name"]
    except Exception as e:
        print(f"    Recherche du dossier d'anticipation de {numero} echouee : {e}")
    return "", ""


def _infos_email_original(gmail_svc, numero):
    """Retourne (dt_reception, dossier_jj_mm, dossier_mm_aaaa) de l'email de
    confirmation original de cette commande : dt_reception est le datetime
    (Paris) de reception de cet email, dossier_jj_mm/dossier_mm_aaaa la date
    de livraison/anticipation extraite de son sujet (meme regex que dans
    chercher_nouvelles_commandes) — a ne pas confondre avec dt_reception, qui
    peut preceder cette date de plusieurs jours si la commande a ete passee
    a l'avance. Retourne (None, "", "") si l'email ou une date exploitable
    dans son sujet sont introuvables."""
    q = f'label:{GMAIL_LABEL_CONF} "{numero}"'
    try:
        res = gmail_svc.users().messages().list(userId='me', q=q, maxResults=1).execute()
        messages = res.get('messages', [])
        if not messages:
            return None, "", ""
        msg = gmail_svc.users().messages().get(
            userId='me', id=messages[0]['id'],
            format='metadata', metadataHeaders=['Subject']).execute()
        dt_reception = datetime.fromtimestamp(int(msg['internalDate']) / 1000, tz=_TZ)
        subject = next(
            (h['value'] for h in msg['payload'].get('headers', []) if h['name'] == 'Subject'), '')
        match_date = re.search(r'(\d{2}/\d{2}/\d{4})', subject)
        if not match_date:
            return dt_reception, "", ""
        dossier_jj_mm   = match_date.group(1)[:5].replace('/', '_')
        dossier_mm_aaaa = match_date.group(1)[3:].replace('/', '_')
        return dt_reception, dossier_jj_mm, dossier_mm_aaaa
    except Exception as e:
        print(f"    Horodatage/date email original {numero} introuvable : {e}")
        return None, "", ""

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


def _telecharger_numeros_archive_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm, nom_fichier):
    """Telecharge et parse un fichier de numeros separes par des virgules depuis
    GITHUB/Anticipation/archives/MM_AAAA/JJ_MM/ (ecrit par
    anticipation_commandes.py). Retourne l'ensemble des numeros qu'il contient
    (vide si le fichier ou un dossier parent n'existe pas encore)."""
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


def _telecharger_commandes_anticipation_envoyee(drive_svc, dossier_mm_aaaa, dossier_jj_mm):
    """Numeros reellement PARTIS par mail a l'equipe dans l'anticipation du jour
    (commandes_envoyées_JJ_MM.txt, ecrit par anticipation_commandes.py juste
    apres l'envoi du PDF). C'est la seule liste qui justifie une alerte en cas
    d'annulation : tant que l'anticipation n'a pas ete envoyee, personne n'a
    sorti les produits de la commande."""
    return _telecharger_numeros_archive_jour(
        drive_svc, dossier_mm_aaaa, dossier_jj_mm,
        f"commandes_envoyées_{dossier_jj_mm}.txt")


def _envoyer_email_anticipation_annulee(gmail_svc, civilite, nom, prenom, num_ancien, num_nouveau=None):
    """Alerte : la commande annulee (remplacee ou non) faisait partie d'une
    anticipation DEJA ENVOYEE par mail a l'equipe (cf.
    _alerter_si_commande_anticipee_annulee) — ses produits ont donc pu etre
    sortis en rayon avant l'annulation.

    Envoye en HTML, un seul <p> par paragraphe : en text/plain, Gmail replie le
    corps a ~78 colonnes en inserant ses propres <br>, ce qui coupait les
    phrases en plein milieu a l'affichage."""
    from email.mime.text import MIMEText
    from html import escape
    destinataire = EMAIL_ANTICIPATION
    if not destinataire:
        return
    civilite_txt = _CIVILITES_LONGUES.get(civilite, "Monsieur/Madame")
    client = escape(" ".join(p for p in (civilite_txt, nom, prenom) if p))
    motif = (f"a été annulée et remplacée par la commande n°{num_nouveau}"
             if num_nouveau else "a été annulée")
    paragraphes = [
        "Bonjour,",
        (f"La commande de {client}, n°{num_ancien} {motif} et faisait partie de "
         f"l'anticipation déjà envoyée. Son retrait du bon d'anticipation a été "
         f"déclenché automatiquement."),
        "Merci d'être vigilant sur les produits de cette commande.",
        "Cordialement,<br>Erwan",
    ]
    corps = "<html><body>" + "".join(f"<p>{p}</p>" for p in paragraphes) + "</body></html>"
    try:
        msg = MIMEText(corps, "html", "utf-8")
        msg["to"] = destinataire
        msg["subject"] = "Attention commande anticipée et annulée"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"    Email alerte anticipation annulee envoye pour cde {num_ancien} => {destinataire}")
    except Exception as e:
        print(f"    Envoi email alerte anticipation annulee {num_ancien} echoue : {e}")


def _alerter_si_commande_anticipee_annulee(drive_svc, gmail_svc, num_ancien, dossier_jj_mm,
                                            dossier_mm_aaaa, num_nouveau=None):
    """Alerte par email, avec le nom du client (extrait de l'archive BDC, encore
    presente sur Drive a ce stade, avant sa suppression par
    _supprimer_bdc_drive), UNIQUEMENT si la commande annulee (remplacee ou non,
    num_ancien) figurait dans l'anticipation du jour dossier_jj_mm/dossier_mm_aaaa
    (sa date de livraison reelle, cf. _infos_email_original — pas
    necessairement aujourd'hui) DEJA ENVOYEE par mail a l'equipe
    (commandes_envoyées_JJ_MM.txt).

    Ce n'est pas la meme chose que de figurer dans le brouillon du jour
    (commandes_anticipées_JJ_MM.txt) : tant que l'anticipation n'est pas
    partie, personne n'a sorti les produits, la commande est simplement
    retiree du brouillon en silence et l'alerte n'aurait aucun objet — c'est
    le mail inutile que recevait l'equipe pour toute commande annulee le jour
    meme de son arrivee, avant l'envoi de l'anticipation."""
    commandes_envoyees = _telecharger_commandes_anticipation_envoyee(
        drive_svc, dossier_mm_aaaa, dossier_jj_mm)
    if num_ancien not in commandes_envoyees:
        return

    print(f"    ATTENTION : commande {num_ancien} annulee faisait partie de "
          f"l'anticipation du {dossier_jj_mm} deja envoyee !")

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

def _commande_dans_suivi_avoir(drive_svc, numero):
    """Vrai si `numero` figure dans Drive GITHUB/Avoir/Commandes en cours (2e
    colonne). La ligne y est inscrite par inscrire_commande_avoir_drive une
    fois le bon de preparation genere : c'est donc la trace qu'une commande a
    reellement ete preparee. Le suivi etant vide periodiquement par
    verif_avoirs.py, une commande ancienne n'y figure plus et est alors tenue
    pour non traitee — au pire elle est repreparee, jamais perdue."""
    try:
        parent = "root"
        for nom in ("GITHUB", "Avoir"):
            res = drive_svc.files().list(
                q=(f"name='{nom}' and '{parent}' in parents "
                   f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
                fields="files(id)",
            ).execute()
            files = res.get("files", [])
            if not files:
                return False
            parent = files[0]["id"]

        res = drive_svc.files().list(
            q=(f"name='{AVOIR_SHEET_FILENAME}' and '{parent}' in parents "
               f"and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"),
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        if not existing:
            return False

        buf = io.BytesIO()
        dl = MediaIoBaseDownload(
            buf, drive_svc.files().export_media(fileId=existing[0]["id"], mimeType="text/csv"))
        done = False
        while not done:
            _, done = dl.next_chunk()
        contenu = buf.getvalue().decode("utf-8-sig", errors="replace")
        for ligne in csv.reader(io.StringIO(contenu)):
            if len(ligne) > 1 and ligne[1].strip() == str(numero):
                return True
    except Exception as e:
        print(f"    Lecture Drive GITHUB/Avoir/{AVOIR_SHEET_FILENAME} echouee : {e}")
    return False

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
    global DRIVE_BONS_FOLDER_ID, DRIVE_BDC_FOLDER_ID, EMAIL_ANTICIPATION, EMAIL_ANTICIPATION_2, LIVRAISON_SPREADSHEET_ID
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
        EMAIL_ANTICIPATION_2 = cfg.get("email_destinataire_2", "")
        LIVRAISON_SPREADSHEET_ID = (cfg.get("livraison_spreadsheet_id", "").strip()
                                     or livraison_drive.LIVRAISON_SPREADSHEET_ID_DEFAUT)
    except Exception as e:
        print(f"ERREUR chargement config Drive : {e}")
        sys.exit(1)

def traiter_commande_pdf(drive_svc, gmail_svc, sheets_svc, pdf, dossier_jj_mm, dossier_mm_aaaa,
                          heure_cron, shopopop_token, shopopop_drive_id, shopopop_connecte):
    """Genere le bon_prepa/bon_anticipation d'un BonDeCommande_NUMERO.pdf deja
    present dans CACHE_DIR, l'archive/upload sur Drive, gere livraison/Shopopop
    et les anomalies.

    Retourne (statut, shopopop_token, shopopop_drive_id, shopopop_connecte) ou
    statut vaut :
      "stop"      : gencod_adresses/nomenclatures indisponibles, l'appelant
                    doit arreter le traitement des commandes suivantes.
      "processed" : le pdf est considere traite (succes ou echec definitif).
      "retry"     : echec du binaire de generation, a retenter plus tard.
    """
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

    # prepa_drive_degrade compte les .pdf presents dans WORK_DIR (nb_files_def)
    # pour decider s'il tourne en mode MONO (1 fichier) ou RAMASSE (plusieurs) :
    # un .pdf residuel d'une commande precedente (ex. bon_prepa.txt vide/absent
    # n'entraine pas toujours son nettoyage) le ferait basculer a tort en
    # RAMASSE et fausserait le matching d'adresse de la commande courante.
    for fname in os.listdir(WORK_DIR):
        if fname.lower().endswith(".pdf"):
            os.remove(os.path.join(WORK_DIR, fname))

    shutil.copy2(cache_path, os.path.join(WORK_DIR, pdf))

    for csv_requis in ["gencod_adresses.csv", "gencod_nomenclatures.csv"]:
        fpath = os.path.join(WORK_DIR, csv_requis)
        if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
            print(f"  ERREUR CRITIQUE : {csv_requis} absent ou vide dans {WORK_DIR}")
            return "stop", shopopop_token, shopopop_drive_id, shopopop_connecte

    pdf_path = os.path.join(WORK_DIR, pdf)
    pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                        capture_output=True, text=True)
    if not pt.stdout.strip():
        print(f"  ECHEC pdftotext - PDF vide ou non lisible : {pdf}")
        os.remove(pdf_path)
        return "processed", shopopop_token, shopopop_drive_id, shopopop_connecte

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

    if DEBUG_RAW_DIR:
        os.makedirs(DEBUG_RAW_DIR, exist_ok=True)
        for src_name in ["bon_prepa.txt", "log_gencod.txt", "bon_encaissement.csv"]:
            src_f = os.path.join(WORK_DIR, src_name)
            if os.path.exists(src_f):
                shutil.copy2(src_f, os.path.join(DEBUG_RAW_DIR, f"{order_num}_{src_name}"))
        with open(os.path.join(DEBUG_RAW_DIR, f"{order_num}_stdout_stderr.txt"), "w", encoding="utf-8") as _f:
            _f.write(f"returncode={r.returncode}\n\n--- stdout ---\n{r.stdout}\n\n--- stderr ---\n{r.stderr}\n")

    if r.returncode != 0:
        print(f" ERREUR (code {r.returncode})")
        if r.stdout: print(f"    stdout : {r.stdout[:300]}")
        if r.stderr: print(f"    stderr : {r.stderr[:300]}")
        p = os.path.join(WORK_DIR, pdf)
        if os.path.exists(p):
            os.remove(p)
        return "retry", shopopop_token, shopopop_drive_id, shopopop_connecte

    bon_prepa_path = os.path.join(WORK_DIR, "bon_prepa.txt")
    if not os.path.exists(bon_prepa_path) or os.path.getsize(bon_prepa_path) == 0:
        print(f" VIDE - bon_prepa.txt absent ou vide")
        if r.stdout: print(f"    sortie C++ : {r.stdout[:300]}")
        return "processed", shopopop_token, shopopop_drive_id, shopopop_connecte
    print(" OK")

    civilite, nom, prenom, date_cde, creneau = extraire_client_creneau_pdf(pt.stdout)

    # Commande deja preparee que l'on regenere (email de confirmation replace a
    # la main en boite de reception apres une mise a jour de gencod_adresses /
    # gencod_nomenclatures) : ses lignes de suivi existantes sont retirees
    # avant d'etre reecrites plus bas. Ni inscrire_commande_avoir_drive ni
    # LIVRAISON DRIVE ne dedoublonnent : sans ce nettoyage, chaque reprise
    # laisserait la commande deux fois dans Avoir/Commandes en cours et dans
    # l'onglet du mois (ou EN ATTENTE).
    regeneration = _commande_deja_traitee(drive_svc, order_num)
    if regeneration:
        print(f"    Commande {order_num} deja preparee : suivis nettoyes avant regeneration.")
        supprimer_commande_avoir_drive(drive_svc, order_num)
        livraison_drive.annuler_commande_livraison(
            sheets_svc, LIVRAISON_SPREADSHEET_ID, nom, prenom, date_cde,
            numero_commande=order_num)

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
        archiver_anticipation_drive(drive_svc, anticipation_dst, dossier_jj_mm, dossier_mm_aaaa,
                                    ecraser=regeneration)
        declencher_assemblage_anticipation(order_num, dossier_jj_mm, dossier_mm_aaaa)

    for fname in [f"bon_prepa_{order_num}.txt",
                  f"bon_anticipation_{order_num}.txt"]:
        fpath = os.path.join(WORK_DIR, fname)
        if os.path.exists(fpath):
            if upload_bon(drive_svc, fpath):
                os.remove(fpath)

    pdf_work = os.path.join(WORK_DIR, pdf)
    if os.path.exists(pdf_work):
        os.remove(pdf_work)

    return "processed", shopopop_token, shopopop_drive_id, shopopop_connecte


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

    # Connexion Shopopop differee : uniquement quand une commande LIVRAISON
    # est effectivement rencontree plus bas (5 a 10 fois/jour), ou quand il y
    # a des km en attente de retentative (voir juste ci-dessous) — pas a
    # chaque run.
    shopopop_token, shopopop_drive_id, shopopop_connecte = None, None, False

    # Retentative des km Shopopop non recuperes lors d'un run precedent (la
    # commande n'etait pas encore synchronisee cote Shopopop au moment du
    # premier essai, cf. livraison_drive.traiter_commande_livraison). Faite a
    # chaque run, meme sans nouvelle commande a traiter ci-dessous : c'est le
    # "run d'apres" qui rattrape le km, une connexion Shopopop dediee n'etant
    # ouverte que s'il y a effectivement quelque chose a retenter. Le token
    # obtenu ici est reutilise plus bas si une nouvelle commande LIVRAISON
    # est aussi rencontree dans ce run (pas de 2e connexion).
    if livraison_drive.km_manquants_en_attente(sheets_svc, LIVRAISON_SPREADSHEET_ID):
        shopopop_token, shopopop_drive_id = livraison_drive.connecter_shopopop(drive_svc)
        shopopop_connecte = True
        livraison_drive.retenter_km_manquants(
            sheets_svc, LIVRAISON_SPREADSHEET_ID, shopopop_token, shopopop_drive_id)

    # Garde-fou : le workflow dedie "Livraison Drive - En attente" (declenche
    # a 14h pile) peut etre saute par GitHub Actions en cas de forte charge
    # (declenchements 'schedule' a l'heure ronde). Rattrapage ici a chaque
    # execution d'auto_prepa.py une fois 14h passees, tant qu'il reste
    # effectivement quelque chose a promouvoir (lecture seule sinon).
    if (datetime.now(_TZ).hour >= 14
            and livraison_drive.promotion_en_attente_necessaire(sheets_svc, LIVRAISON_SPREADSHEET_ID)):
        print("  Rattrapage EN ATTENTE (workflow 14h non detecte pour aujourd'hui).")
        livraison_drive.traiter_en_attente(sheets_svc, LIVRAISON_SPREADSHEET_ID)

    shopopop_token, shopopop_drive_id, shopopop_connecte = traiter_modifications_clients(
        drive_svc, gmail_svc, sheets_svc,
        shopopop_token, shopopop_drive_id, shopopop_connecte)
    nouveaux = telecharger_bons_email(gmail_svc, CACHE_DIR, drive_svc)

    # Bons deposes a la main sur Drive (commande sans email de confirmation) :
    # meme traitement que ceux recus par email, a partir d'ici.
    nouveaux_manuels, depots_manuels = telecharger_bons_traitement_manuel(
        drive_svc, CACHE_DIR)
    nouveaux.update(nouveaux_manuels)

    nouveaux = _ecarter_commandes_annulees(drive_svc, nouveaux)

    # Un bon depose pour une commande entre-temps annulee/remplacee n'a plus
    # lieu d'etre : sans cela il resterait dans le dossier et serait reexamine
    # a chaque run.
    for pdf in [p for p in depots_manuels if p not in nouveaux]:
        _archiver_depot_manuel(drive_svc, depots_manuels.pop(pdf), pdf,
                               "commande annulee ou remplacee")

    if not nouveaux:
        print("Pas de nouvelle commande.")
        return

    print(f"{len(nouveaux)} nouvelle(s) commande(s) detectee(s) :")
    for pdf in sorted(nouveaux):
        print(f"  - {pdf}")

    os.makedirs(BDC_DIR, exist_ok=True)

    for pdf, (dossier_jj_mm, dossier_mm_aaaa) in sorted(nouveaux.items()):
        statut, shopopop_token, shopopop_drive_id, shopopop_connecte = traiter_commande_pdf(
            drive_svc, gmail_svc, sheets_svc, pdf, dossier_jj_mm, dossier_mm_aaaa,
            heure_cron, shopopop_token, shopopop_drive_id, shopopop_connecte)
        # Le depot manuel n'est retire qu'une fois la commande reellement
        # traitee : sur "retry" (echec de generation) il reste en place et sera
        # repris au run suivant.
        if statut == "processed" and pdf in depots_manuels:
            _archiver_depot_manuel(drive_svc, depots_manuels[pdf], pdf, "commande traitee")
        if statut == "stop":
            break

if __name__ == "__main__":
    main()
