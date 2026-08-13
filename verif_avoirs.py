#!/usr/bin/env python3
"""
Workflow "vav" : pour chaque commande listee dans Drive GITHUB/Avoir/
"Commandes en cours" (civilite, nom, prenom, date, creneau), verifie si le
client a un avoir jaune (du, pas encore deduit) dans le classeur Google
Sheets "Avoir/Demarque" — un avoir n'etant valable que 3 mois, seuls les
onglets du mois courant et des deux mois precedents sont regardes. Envoie un
mail par avoir trouve, puis vide "Commandes en cours" (hors en-tete) pour ne
pas retraiter ces commandes au prochain declenchement.
"""
import base64
import io
import os
import sys
import unicodedata
from datetime import date, datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import controle_stocks as cs

_TZ = ZoneInfo("Europe/Paris")

MOIS_FR = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
           "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]

# ID du classeur "AVOIR DEMARQUE DRIVE 2026" (docs.google.com/spreadsheets/d/<id>).
# Utilise si absent de config.json (cle "avoir_spreadsheet_id") — a mettre a
# jour dans config.json les annees suivantes, quand un nouveau classeur est cree.
AVOIR_SPREADSHEET_ID_DEFAUT = "1TEz5Bmx_sIOOSdAoBGB9KXuZAzP3TdhnPCfVDS4yyrs"


def _normaliser(texte):
    """Majuscules sans accents, pour comparer noms/mois insensiblement a la casse/accents."""
    d = unicodedata.normalize('NFD', (texte or '').strip().upper())
    return ''.join(c for c in d if unicodedata.category(c) != 'Mn')


def _est_jaune(rgb):
    """Distingue un fond jaune (avoir du) d'un fond vert (avoir deja deduit)
    ou blanc (ligne vide/hors template)."""
    r, g, b = rgb
    return r > 0.7 and g > 0.7 and b < min(r, g) - 0.2


def _civilite_longue(civilite):
    c = _normaliser(civilite)
    return 'Madame' if c.startswith('MME') or c.startswith('MADAME') else 'Monsieur'


def _formatter_montant(brut):
    """Normalise un montant lu en cellule (ex. '7,98 €', '7.98') en '7,98 €'."""
    nettoye = brut.replace('€', '').replace('\xa0', ' ').strip().replace(' ', '').replace(',', '.')
    try:
        return f"{float(nettoye):.2f}".replace('.', ',') + " €"
    except ValueError:
        return brut if '€' in brut else f"{brut} €"


def _onglets_a_verifier(date_ref, nb_mois=3):
    """Noms d'onglets (normalises) des nb_mois derniers mois, mois courant
    inclus — inutile de regarder plus loin, un avoir n'est valable que 3 mois."""
    onglets = []
    y, m = date_ref.year, date_ref.month
    for i in range(nb_mois):
        mm = m - i
        while mm <= 0:
            mm += 12
        onglets.append(MOIS_FR[mm - 1])
    return onglets


def _date_fin_valide(date_fin_str, aujourdhui):
    try:
        j, m, a = date_fin_str.split('/')
        return date(int(a), int(m), int(j)) >= aujourdhui
    except Exception:
        return True  # format inattendu : on ne filtre pas plutot que de perdre un avoir valide


def _get_sheets_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        if not os.path.exists(cs.TOKEN_FILE):
            return None
        creds = Credentials.from_authorized_user_file(cs.TOKEN_FILE, cs.SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"  Sheets inaccessible : {e}")
        return None


def _charger_config_avoir(drive_svc):
    """Retourne (avoir_spreadsheet_id, email_destinataire) depuis config.json."""
    import json
    from googleapiclient.http import MediaIoBaseDownload
    res = drive_svc.files().list(
        q=f"name='config.json' and '{cs.DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
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
    avoir_id = cfg.get("avoir_spreadsheet_id", "").strip() or AVOIR_SPREADSHEET_ID_DEFAUT
    email = cfg.get("email_destinataire", "").strip()
    if not email:
        print("ERREUR : email_destinataire absent de config.json.")
        sys.exit(1)
    return avoir_id, email


def _lire_avoirs_jaunes(sheets_svc, spreadsheet_id, date_ref):
    """Lit les lignes a fond jaune (avoir du) des onglets des 3 derniers mois."""
    onglets_cibles = _onglets_a_verifier(date_ref)
    meta = sheets_svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    titres = [s["properties"]["title"] for s in meta.get("sheets", [])]
    correspondance = {}
    for titre in titres:
        norm = _normaliser(titre)
        if norm in onglets_cibles and norm not in correspondance:
            correspondance[norm] = titre
    manquants = [o for o in onglets_cibles if o not in correspondance]
    if manquants:
        print(f"  Onglets Avoir introuvables (ignores) : {', '.join(manquants)}")

    avoirs = []
    for norm in onglets_cibles:
        titre = correspondance.get(norm)
        if not titre:
            continue
        res = sheets_svc.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"'{titre}'!A3:F1000"],
            includeGridData=True,
            fields="sheets.data.rowData.values(formattedValue,effectiveFormat.backgroundColor)",
        ).execute()
        row_data = res["sheets"][0]["data"][0].get("rowData", [])
        for row in row_data:
            cells = row.get("values", [])
            if not cells or not cells[0].get("formattedValue", "").strip():
                continue

            def val(i):
                return cells[i].get("formattedValue", "").strip() if i < len(cells) else ""

            bg = cells[0].get("effectiveFormat", {}).get("backgroundColor", {})
            rgb = (bg.get("red", 1.0), bg.get("green", 1.0), bg.get("blue", 1.0))
            print(f"    [{titre}] {val(0)} {val(1)} — fond rgb={rgb}")
            if not _est_jaune(rgb):
                continue
            avoirs.append({
                "onglet": titre, "nom": val(0), "prenom": val(1),
                "montant": val(2), "date_debut": val(3), "date_fin": val(4),
                "raison": val(5),
            })
    return avoirs


def _trouver_fichier_commandes(drive_svc):
    """Cherche GITHUB/Avoir/Commandes en cours sur Drive. Retourne (id, mimeType) ou None."""
    res = drive_svc.files().list(
        q=("name='GITHUB' and 'root' in parents "
           "and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    github = res.get("files", [])
    if not github:
        print("  Dossier GITHUB/ introuvable sur Drive.")
        return None
    res = drive_svc.files().list(
        q=(f"name='Avoir' and '{github[0]['id']}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    avoir_folder = res.get("files", [])
    if not avoir_folder:
        print("  Dossier GITHUB/Avoir/ introuvable sur Drive.")
        return None
    res = drive_svc.files().list(
        q=(f"name contains 'Commandes en cours' and '{avoir_folder[0]['id']}' in parents "
           f"and trashed=false"),
        fields="files(id,name,mimeType)",
    ).execute()
    fichiers = res.get("files", [])
    if not fichiers:
        print("  'Commandes en cours' introuvable dans GITHUB/Avoir/.")
        return None
    return fichiers[0]["id"], fichiers[0]["mimeType"]


def _lire_commandes_en_cours(sheets_svc, file_id):
    """Retourne [(civilite, nom, prenom, date, creneau), ...] (lignes non vides, hors en-tete)."""
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=file_id, range="A2:E1000").execute()
    lignes = []
    for row in res.get("values", []):
        row = row + [""] * (5 - len(row))
        if row[1].strip() or row[2].strip():
            lignes.append(tuple(c.strip() for c in row[:5]))
    return lignes


def _vider_commandes_en_cours(sheets_svc, file_id):
    """Vide les lignes de donnees (garde l'en-tete) pour ne pas retraiter ces
    commandes au prochain declenchement."""
    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=file_id, range="A2:E1000", body={}).execute()
    print("  'Commandes en cours' vide.")


def _envoyer_email_avoir(gmail_svc, destinataire, civilite, avoir, date_cde, creneau):
    if not gmail_svc:
        print("  Gmail inaccessible — email non envoye.")
        return
    civ = _civilite_longue(civilite)
    montant = _formatter_montant(avoir["montant"])
    corps = (
        f"Bonjour,\n\n"
        f"Un avoir est dû à {civ} {avoir['nom']} {avoir['prenom']} "
        f"d'un montant de {montant} pour le {date_cde} entre {creneau}"
    )
    msg = MIMEText(corps, 'plain', 'utf-8')
    msg['To'] = destinataire
    msg['Subject'] = "Avoir à déduire"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        gmail_svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email envoye -> {destinataire} ({avoir['nom']} {avoir['prenom']}, {montant})")
    except Exception as e:
        print(f"  Email echoue ({avoir['nom']} {avoir['prenom']}) : {e}")


def main():
    if not cs.DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : secret DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)

    drive_svc = cs._get_drive_service()
    if not drive_svc:
        print("ERREUR : Drive inaccessible.")
        sys.exit(1)
    sheets_svc = _get_sheets_service()
    if not sheets_svc:
        print("ERREUR : Sheets inaccessible.")
        sys.exit(1)

    avoir_spreadsheet_id, email_destinataire = _charger_config_avoir(drive_svc)

    aujourdhui = datetime.now(_TZ).date()
    print(f"Lecture des avoirs jaunes ({aujourdhui.strftime('%d/%m/%Y')}) …")
    avoirs_jaunes = _lire_avoirs_jaunes(sheets_svc, avoir_spreadsheet_id, aujourdhui)
    print(f"→ {len(avoirs_jaunes)} avoir(s) jaune(s) (du) sur les 3 derniers mois.")

    fichier = _trouver_fichier_commandes(drive_svc)
    if not fichier:
        print("Rien a verifier : 'Commandes en cours' introuvable.")
        return
    file_id, mime_type = fichier
    if mime_type != "application/vnd.google-apps.spreadsheet":
        print(f"ERREUR : 'Commandes en cours' doit etre une Google Sheet (type actuel : {mime_type}).")
        sys.exit(1)

    commandes = _lire_commandes_en_cours(sheets_svc, file_id)
    print(f"{len(commandes)} commande(s) a verifier.")
    if not commandes:
        return

    gmail_svc = cs._get_gmail_service()
    nb_envoyes = 0
    for civilite, nom, prenom, date_cde, creneau in commandes:
        nom_n, prenom_n = _normaliser(nom), _normaliser(prenom)
        for avoir in avoirs_jaunes:
            if _normaliser(avoir["nom"]) != nom_n or _normaliser(avoir["prenom"]) != prenom_n:
                continue
            if not _date_fin_valide(avoir["date_fin"], aujourdhui):
                continue
            _envoyer_email_avoir(gmail_svc, email_destinataire, civilite, avoir, date_cde, creneau)
            nb_envoyes += 1

    print(f"\n{nb_envoyes} email(s) envoye(s).")

    print("\nVidage de 'Commandes en cours' …")
    _vider_commandes_en_cours(sheets_svc, file_id)


if __name__ == "__main__":
    main()
