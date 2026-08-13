#!/usr/bin/env python3
"""
Enregistrement des commandes en LIVRAISON dans le classeur Google Sheets
"LIVRAISON DRIVE 2026" : un onglet par mois (Préparateur, Date, Nom Prénom,
...) plus un onglet "EN ATTENTE" pour les commandes trop en avance pour
être renseignées tout de suite.

Règle (demande utilisateur) :
- commande du jour même                    -> renseignée directement (onglet
                                               du mois, date du jour)
- commande pour le lendemain, s'il est
  déjà 14h ou plus le jour même             -> renseignée directement (onglet
                                               du mois, date du lendemain)
- tous les autres cas                       -> onglet "EN ATTENTE" (nom
                                               prénom, jour au format JJ/MM)

auto_prepa.py appelle traiter_commande_livraison() pour chaque commande en
LIVRAISON détectée (présence de ',Livraison,' sur la 2e ligne de
bon_prepa.txt). Le workflow "Livraison Drive - En attente" (déclenché à
14h) appelle traiter_en_attente() pour renseigner les commandes de
EN ATTENTE prévues pour le lendemain.
"""
import sys
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import controle_stocks as cs

_TZ = ZoneInfo("Europe/Paris")

# ID du classeur "LIVRAISON DRIVE 2026" (docs.google.com/spreadsheets/d/<id>).
# Utilisé si absent de config.json (clé "livraison_spreadsheet_id") — à
# mettre à jour dans config.json les années suivantes, quand un nouveau
# classeur est créé.
LIVRAISON_SPREADSHEET_ID_DEFAUT = "1vfBGpXnU2mi_JyNIcukbp0Gk48a9AIGYRl9KF98wG7g"

MOIS_FR = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
           "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]

ONGLET_EN_ATTENTE = "EN ATTENTE"
PREPARATEUR = "Claude"

_MAX_LIGNES = 500  # profondeur de recherche de ligne libre / lecture EN ATTENTE


def _normaliser(texte):
    """Majuscules sans accents, pour comparer les titres d'onglets insensiblement a la casse/accents."""
    d = unicodedata.normalize('NFD', (texte or '').strip().upper())
    return ''.join(c for c in d if unicodedata.category(c) != 'Mn')


def _get_sheets_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        import os
        if not os.path.exists(cs.TOKEN_FILE):
            return None
        creds = Credentials.from_authorized_user_file(cs.TOKEN_FILE, cs.SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"  Sheets inaccessible : {e}")
        return None


def _charger_config_livraison(drive_svc):
    """Retourne l'ID du classeur LIVRAISON DRIVE 2026 depuis config.json
    (clé "livraison_spreadsheet_id"), ou la valeur par défaut."""
    import io
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
    return cfg.get("livraison_spreadsheet_id", "").strip() or LIVRAISON_SPREADSHEET_ID_DEFAUT


def _lister_onglets(sheets_svc, spreadsheet_id):
    res = sheets_svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties(title)").execute()
    return [s["properties"]["title"] for s in res.get("sheets", [])]


def _trouver_onglet(sheets_svc, spreadsheet_id, nom_normalise):
    for titre in _lister_onglets(sheets_svc, spreadsheet_id):
        if _normaliser(titre) == nom_normalise:
            return titre
    return None


def _creer_onglet_en_attente(sheets_svc, spreadsheet_id):
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": ONGLET_EN_ATTENTE}}}]},
    ).execute()
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{ONGLET_EN_ATTENTE}'!A1:B1",
        valueInputOption="USER_ENTERED",
        body={"values": [["Nom Prénom", "Jour"]]},
    ).execute()
    print(f"    Onglet '{ONGLET_EN_ATTENTE}' créé dans LIVRAISON DRIVE 2026.")
    return ONGLET_EN_ATTENTE


def _premiere_ligne_libre(sheets_svc, spreadsheet_id, titre_onglet, colonne):
    """Premiere ligne (>= 2) ou `colonne` est vide dans l'onglet, dans les
    _MAX_LIGNES lignes suivant l'en-tete."""
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{titre_onglet}'!{colonne}2:{colonne}{1 + _MAX_LIGNES}").execute()
    valeurs = res.get("values", [])
    for i in range(_MAX_LIGNES):
        v = valeurs[i][0] if i < len(valeurs) and valeurs[i] else ""
        if not v.strip():
            return 2 + i
    return 2 + _MAX_LIGNES


def _inscrire_commande(sheets_svc, spreadsheet_id, cible, nom_complet):
    """Renseigne (Préparateur, Date, Nom Prénom) sur la premiere ligne libre
    de l'onglet du mois de `cible` (colonne C = nom, sert de reference pour
    trouver la ligne libre)."""
    mois = MOIS_FR[cible.month - 1]
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, mois)
    if not onglet:
        print(f"    ERREUR : onglet '{mois}' introuvable dans LIVRAISON DRIVE 2026.")
        return False
    ligne = _premiere_ligne_libre(sheets_svc, spreadsheet_id, onglet, "C")
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A{ligne}:C{ligne}",
        valueInputOption="USER_ENTERED",
        body={"values": [[PREPARATEUR, cible.strftime("%d/%m"), nom_complet]]},
    ).execute()
    print(f"    LIVRAISON DRIVE 2026 / {onglet} L{ligne} : {PREPARATEUR} | "
          f"{cible.strftime('%d/%m')} | {nom_complet}")
    return True


def _inscrire_en_attente(sheets_svc, spreadsheet_id, cible, nom_complet):
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
    if not onglet:
        onglet = _creer_onglet_en_attente(sheets_svc, spreadsheet_id)
    ligne = _premiere_ligne_libre(sheets_svc, spreadsheet_id, onglet, "A")
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A{ligne}:B{ligne}",
        valueInputOption="USER_ENTERED",
        body={"values": [[nom_complet, cible.strftime("%d/%m")]]},
    ).execute()
    print(f"    LIVRAISON DRIVE 2026 / {ONGLET_EN_ATTENTE} L{ligne} : "
          f"{nom_complet} | {cible.strftime('%d/%m')}")


_ROUGE = {"red": 1.0, "green": 0.0, "blue": 0.0}


def _sheet_id(sheets_svc, spreadsheet_id, titre_onglet):
    res = sheets_svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)").execute()
    for s in res.get("sheets", []):
        if s["properties"]["title"] == titre_onglet:
            return s["properties"]["sheetId"]
    return None


def _chercher_et_colorier(sheets_svc, spreadsheet_id, titre_onglet,
                           idx_nom, idx_date, nb_colonnes, nom_complet_cible, jour_str):
    """Cherche, dans les nb_colonnes premieres colonnes de `titre_onglet`, une
    ligne dont la colonne idx_nom = nom_complet_cible (compare via _normaliser)
    et la colonne idx_date = jour_str (JJ/MM) ; si trouvee, colore ses
    nb_colonnes premieres cellules en rouge (le fond jaune existant du
    classeur signale une livraison a venir, le rouge une livraison annulee).
    Retourne True si une ligne a ete trouvee et coloriee."""
    derniere_colonne = chr(ord('A') + nb_colonnes - 1)
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{titre_onglet}'!A2:{derniere_colonne}{1 + _MAX_LIGNES}").execute()
    lignes = res.get("values", [])
    for i, row in enumerate(lignes):
        nom_val = row[idx_nom].strip() if idx_nom < len(row) and row[idx_nom] else ""
        date_val = row[idx_date].strip() if idx_date < len(row) and row[idx_date] else ""
        if not nom_val or not date_val:
            continue
        if _normaliser(nom_val) != nom_complet_cible or date_val != jour_str:
            continue
        ligne = 2 + i
        sheet_id = _sheet_id(sheets_svc, spreadsheet_id, titre_onglet)
        if sheet_id is None:
            return False
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": ligne - 1, "endRowIndex": ligne,
                        "startColumnIndex": 0, "endColumnIndex": nb_colonnes,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": _ROUGE}},
                    "fields": "userEnteredFormat.backgroundColor",
                },
            }]}).execute()
        print(f"    LIVRAISON DRIVE 2026 / {titre_onglet} L{ligne} : "
              f"{nom_val} annulee -> fond rouge.")
        return True
    return False


def annuler_commande_livraison(sheets_svc, spreadsheet_id, nom, prenom, date_cde_str):
    """A appeler pour une commande en LIVRAISON strictement annulee (pas une
    modification/remplacement, qui ne change pas la date de livraison).
    Localise la ligne correspondante dans LIVRAISON DRIVE 2026 — d'abord
    l'onglet du mois de la commande, puis EN ATTENTE si absente du mois — et
    passe son fond au rouge. La ligne n'est pas supprimee."""
    if not sheets_svc or not spreadsheet_id:
        print("    Sheets/LIVRAISON DRIVE 2026 indisponible, annulation livraison ignoree.")
        return
    if not (nom or prenom) or not date_cde_str:
        print("    Nom/prenom/date introuvables, annulation livraison Drive ignoree.")
        return
    try:
        date_cde = datetime.strptime(date_cde_str, "%d/%m/%Y").date()
    except ValueError:
        print(f"    Date de commande illisible ({date_cde_str}), annulation livraison Drive ignoree.")
        return

    nom_complet_cible = _normaliser(f"{nom} {prenom}".strip())
    jour_str = date_cde.strftime("%d/%m")

    try:
        mois = MOIS_FR[date_cde.month - 1]
        onglet_mois = _trouver_onglet(sheets_svc, spreadsheet_id, mois)
        if onglet_mois and _chercher_et_colorier(
                sheets_svc, spreadsheet_id, onglet_mois,
                idx_nom=2, idx_date=1, nb_colonnes=3,
                nom_complet_cible=nom_complet_cible, jour_str=jour_str):
            return

        onglet_attente = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
        if onglet_attente and _chercher_et_colorier(
                sheets_svc, spreadsheet_id, onglet_attente,
                idx_nom=0, idx_date=1, nb_colonnes=2,
                nom_complet_cible=nom_complet_cible, jour_str=jour_str):
            return

        print(f"    Aucune ligne LIVRAISON DRIVE 2026 trouvee pour {nom} {prenom} "
              f"({date_cde_str}), rien a colorier.")
    except Exception as e:
        print(f"    Annulation LIVRAISON DRIVE 2026 echouee ({nom} {prenom}) : {e}")


def traiter_commande_livraison(sheets_svc, spreadsheet_id, nom, prenom, date_cde_str, maintenant=None):
    """A appeler pour chaque commande en LIVRAISON (detectee via ',Livraison,'
    sur la 2e ligne de bon_prepa.txt). `date_cde_str` est au format
    JJ/MM/AAAA (extrait du PDF par extraire_client_creneau_pdf)."""
    if not sheets_svc or not spreadsheet_id:
        print("    Sheets/LIVRAISON DRIVE 2026 indisponible, commande ignoree.")
        return
    if not (nom or prenom) or not date_cde_str:
        print("    Nom/prenom/date introuvables dans le PDF, livraison Drive ignoree.")
        return
    try:
        date_cde = datetime.strptime(date_cde_str, "%d/%m/%Y").date()
    except ValueError:
        print(f"    Date de commande illisible ({date_cde_str}), livraison Drive ignoree.")
        return

    maintenant = maintenant or datetime.now(_TZ)
    aujourdhui = maintenant.date()
    nom_complet = f"{nom} {prenom}".strip()

    try:
        if date_cde == aujourdhui or (
                date_cde == aujourdhui + timedelta(days=1) and maintenant.hour >= 14):
            _inscrire_commande(sheets_svc, spreadsheet_id, date_cde, nom_complet)
        else:
            _inscrire_en_attente(sheets_svc, spreadsheet_id, date_cde, nom_complet)
    except Exception as e:
        print(f"    Ecriture LIVRAISON DRIVE 2026 echouee ({nom_complet}) : {e}")


def _parser_jour(jour_str, aujourdhui):
    """Parse 'JJ/MM' en date, en choisissant l'annee la plus proche de
    aujourdhui (gere le cas d'une commande de fin decembre encore en
    attente en janvier)."""
    try:
        jj, mm = (int(p) for p in jour_str.split('/'))
    except ValueError:
        return None
    meilleure = None
    for annee in (aujourdhui.year - 1, aujourdhui.year, aujourdhui.year + 1):
        try:
            d = date(annee, mm, jj)
        except ValueError:
            continue
        if meilleure is None or abs((d - aujourdhui).days) < abs((meilleure - aujourdhui).days):
            meilleure = d
    return meilleure


def traiter_en_attente(sheets_svc, spreadsheet_id, maintenant=None):
    """Renseigne dans l'onglet du mois les commandes de EN ATTENTE prevues
    pour le lendemain (par rapport a `maintenant`), et les retire de EN
    ATTENTE. Appelee par le workflow declenche a 14h."""
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
    if not onglet:
        print(f"  Onglet '{ONGLET_EN_ATTENTE}' introuvable, rien a traiter.")
        return

    maintenant = maintenant or datetime.now(_TZ)
    aujourdhui = maintenant.date()
    lendemain = aujourdhui + timedelta(days=1)

    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A2:B{1 + _MAX_LIGNES}").execute()
    lignes = res.get("values", [])

    a_traiter, a_garder = [], []
    for row in lignes:
        nom_complet = row[0].strip() if len(row) > 0 and row[0] else ""
        jour = row[1].strip() if len(row) > 1 and row[1] else ""
        if not nom_complet and not jour:
            continue
        cible = _parser_jour(jour, aujourdhui) if jour else None
        if cible == lendemain:
            a_traiter.append((cible, nom_complet))
        else:
            a_garder.append((nom_complet, jour))

    print(f"  EN ATTENTE : {len(a_traiter)} commande(s) pour le {lendemain.strftime('%d/%m')}, "
          f"{len(a_garder)} conservee(s).")

    for cible, nom_complet in a_traiter:
        _inscrire_commande(sheets_svc, spreadsheet_id, cible, nom_complet)

    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A2:B{1 + _MAX_LIGNES}", body={}).execute()
    if a_garder:
        sheets_svc.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A2",
            valueInputOption="USER_ENTERED",
            body={"values": [list(r) for r in a_garder]}).execute()


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

    spreadsheet_id = _charger_config_livraison(drive_svc)
    print(f"Traitement de l'onglet '{ONGLET_EN_ATTENTE}' de LIVRAISON DRIVE 2026 …")
    traiter_en_attente(sheets_svc, spreadsheet_id)


if __name__ == "__main__":
    main()
