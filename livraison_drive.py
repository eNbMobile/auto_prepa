#!/usr/bin/env python3
"""
Enregistrement des commandes en LIVRAISON dans le classeur Google Sheets
"LIVRAISON DRIVE 2026" : un onglet par mois (N° cde, Date, Nom, Prénom,
Distance, Frais — Frais est une formule du classeur, jamais écrite par ce
script) plus un onglet "EN ATTENTE" (Nom, Prénom, Jour, N° commande, km)
pour les commandes trop en avance pour être renseignées tout de suite.

Règle (demande utilisateur) :
- commande du jour même                    -> renseignée directement (onglet
                                               du mois, date du jour)
- commande pour le lendemain ouvré (le
  lendemain, sauf si on est samedi -> alors
  le lundi, le dimanche étant fermé), s'il
  est déjà 14h ou plus le jour même         -> renseignée directement (onglet
                                               du mois, date du lendemain ouvré)
- tous les autres cas                       -> onglet "EN ATTENTE" (nom
                                               prénom en CAPS, jour au format
                                               JJ/MM, n° de commande, km —
                                               le km est recupere sur
                                               Shopopop des ce moment-la,
                                               pas lors de la promotion)

Le nom/prénom est toujours inscrit en CAPS. Dans EN ATTENTE, le n° de
commande permet d'identifier sans ambiguïté la ligne à annuler (nom+jour
peut correspondre à plusieurs commandes du même client le même jour).

auto_prepa.py appelle traiter_commande_livraison() pour chaque commande en
LIVRAISON détectée (présence de ',Livraison,' sur la 2e ligne de
bon_prepa.txt). Le workflow "Livraison Drive - En attente" (déclenché à
14h) appelle traiter_en_attente() pour renseigner les commandes de
EN ATTENTE prévues pour le lendemain.
"""
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import controle_stocks as cs
import shopopop

_TZ = ZoneInfo("Europe/Paris")

# ID du classeur "LIVRAISON DRIVE 2026" (docs.google.com/spreadsheets/d/<id>).
# Utilisé si absent de config.json (clé "livraison_spreadsheet_id") — à
# mettre à jour dans config.json les années suivantes, quand un nouveau
# classeur est créé.
LIVRAISON_SPREADSHEET_ID_DEFAUT = "1vfBGpXnU2mi_JyNIcukbp0Gk48a9AIGYRl9KF98wG7g"

MOIS_FR = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
           "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]

ONGLET_EN_ATTENTE = "EN ATTENTE"

# Vert #00FF00 (meme couleur que le nom/prenom des livraisons deja
# confirmees en debut de fichier) : applique par marquer_livree() quand le
# workflow "Verif LAD" confirme la livraison cote Shopopop.
_VERT_LIVREE = {"red": 0.0, "green": 1.0, "blue": 0.0}

_MAX_LIGNES = 500  # profondeur de recherche de ligne libre / lecture EN ATTENTE

# Delai avant une 2e tentative de recuperation du km dans le meme run, pour
# laisser le temps a Shopopop de synchroniser une commande tres recente
# (cf. traiter_commande_livraison).
_DELAI_RETRY_KM_SECONDES = 30

# Au-dela de ce nombre de jours de retard sur la date de livraison, une ligne
# sans km n'est plus retentee par retenter_km_manquants (cf. plus bas) : la
# commande a de toute facon deja ete signalee par email et completee a la
# main si besoin.
_FENETRE_RETENTATIVE_JOURS = 3


def _lendemain_ouvre(aujourdhui):
    """Jour ouvré suivant `aujourdhui` : le lendemain, sauf si `aujourdhui`
    est un samedi (dimanche fermé), auquel cas c'est le lundi suivant."""
    if aujourdhui.weekday() == 5:  # samedi
        return aujourdhui + timedelta(days=2)
    return aujourdhui + timedelta(days=1)


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


def _charger_config_dict(drive_svc):
    """Télécharge et parse config.json depuis le dossier Drive de config."""
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
    return json.loads(buf.getvalue().decode())


def _charger_config_livraison(drive_svc):
    """Retourne l'ID du classeur LIVRAISON DRIVE 2026 depuis config.json
    (clé "livraison_spreadsheet_id"), ou la valeur par défaut."""
    cfg = _charger_config_dict(drive_svc)
    return cfg.get("livraison_spreadsheet_id", "").strip() or LIVRAISON_SPREADSHEET_ID_DEFAUT


def connecter_shopopop(drive_svc):
    """Se connecte à Shopopop Pro avec les identifiants de config.json (clés
    "ID_Shopopop", "MDP_Shopopop") et retourne (access_token, drive_id).
    access_token est None si les identifiants sont absents ou la connexion a
    échoué — la colonne km est alors laissée vide (comme actuellement)."""
    cfg = _charger_config_dict(drive_svc)
    email = cfg.get("ID_Shopopop", "").strip()
    mdp = cfg.get("MDP_Shopopop", "").strip()
    drive_id = cfg.get("shopopop_drive_id", "").strip() or shopopop.SHOPOPOP_DRIVE_ID_DEFAUT
    if not email or not mdp:
        print("    ID_Shopopop/MDP_Shopopop absents de config.json, km Shopopop ignoré.")
        return None, drive_id
    token = shopopop.login(email, mdp)
    if not token:
        print("    Connexion Shopopop échouée, km Shopopop ignoré.")
    return token, drive_id


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
        spreadsheetId=spreadsheet_id, range=f"'{ONGLET_EN_ATTENTE}'!A1:E1",
        valueInputOption="USER_ENTERED",
        body={"values": [["Nom", "Prénom", "Jour", "N° commande", "km"]]},
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


def _inscrire_commande(sheets_svc, spreadsheet_id, cible, nom, prenom, numero_commande=None, km=None):
    """Renseigne (N° cde, Date, Nom, Prénom, Distance) sur la premiere ligne
    libre de l'onglet du mois de `cible` (colonne C = nom, sert de reference
    pour trouver la ligne libre). `km` (distance magasin -> client, recuperee
    sur Shopopop) est laisse vide si absent/introuvable, a completer a la
    main. La colonne Frais n'est jamais ecrite ici : c'est une formule du
    classeur."""
    mois = MOIS_FR[cible.month - 1]
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, mois)
    if not onglet:
        print(f"    ERREUR : onglet '{mois}' introuvable dans LIVRAISON DRIVE 2026.")
        return False
    ligne = _premiere_ligne_libre(sheets_svc, spreadsheet_id, onglet, "C")
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A{ligne}:E{ligne}",
        valueInputOption="USER_ENTERED",
        body={"values": [[numero_commande or "", cible.strftime("%d/%m"), nom, prenom,
                           km if km is not None else ""]]},
    ).execute()
    print(f"    LIVRAISON DRIVE 2026 / {onglet} L{ligne} : {numero_commande or ''} | "
          f"{cible.strftime('%d/%m')} | {nom} {prenom}"
          + (f" | {km} km" if km is not None else " | km non trouve"))
    return True


def _inscrire_en_attente(sheets_svc, spreadsheet_id, cible, nom, prenom, numero_commande=None, km=None):
    """Ajoute une ligne (Nom, Prénom, Jour, N° commande, km) dans EN ATTENTE. Le
    n° de commande sert d'identifiant fiable pour l'annulation, le nom seul
    ne suffisant pas quand deux commandes partagent le même nom et jour. `km`
    est recupere sur Shopopop des le traitement de la commande (meme si la
    livraison n'est renseignee que plus tard dans l'onglet du mois), pour ne
    pas avoir a interroger Shopopop une seconde fois lors de la promotion."""
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
    if not onglet:
        onglet = _creer_onglet_en_attente(sheets_svc, spreadsheet_id)
    ligne = _premiere_ligne_libre(sheets_svc, spreadsheet_id, onglet, "A")
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A{ligne}:E{ligne}",
        valueInputOption="USER_ENTERED",
        body={"values": [[nom, prenom, cible.strftime("%d/%m"), numero_commande or "",
                           km if km is not None else ""]]},
    ).execute()
    print(f"    LIVRAISON DRIVE 2026 / {ONGLET_EN_ATTENTE} L{ligne} : "
          f"{nom} {prenom} | {cible.strftime('%d/%m')} | {numero_commande or ''}"
          + (f" | {km} km" if km is not None else " | km non trouve"))


def _sheet_id(sheets_svc, spreadsheet_id, titre_onglet):
    res = sheets_svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)").execute()
    for s in res.get("sheets", []):
        if s["properties"]["title"] == titre_onglet:
            return s["properties"]["sheetId"]
    return None


def marquer_livree(sheets_svc, spreadsheet_id, aujourdhui, ligne):
    """Met en vert le FOND (backgroundColor _VERT_LIVREE, comme le nom/prenom
    des livraisons deja confirmees en debut de fichier) des cellules Nom et
    Prenom (colonnes C:D) de la ligne `ligne` de l'onglet du mois de
    `aujourdhui`, pour signaler qu'une livraison a ete confirmee cote
    Shopopop (workflow "Verif LAD"). Retourne True si applique, False si
    l'onglet est introuvable."""
    mois = MOIS_FR[aujourdhui.month - 1]
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, mois)
    if not onglet:
        print(f"    ERREUR : onglet '{mois}' introuvable dans LIVRAISON DRIVE 2026.")
        return False
    sheet_id = _sheet_id(sheets_svc, spreadsheet_id, onglet)
    if sheet_id is None:
        return False
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": ligne - 1, "endRowIndex": ligne,
                    "startColumnIndex": 2, "endColumnIndex": 4,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": _VERT_LIVREE}},
                "fields": "userEnteredFormat.backgroundColor",
            },
        }]}).execute()
    return True


def _supprimer_ligne(sheets_svc, spreadsheet_id, titre_onglet, ligne):
    """Supprime la ligne `ligne` (les lignes suivantes remontent d'un cran)."""
    sheet_id = _sheet_id(sheets_svc, spreadsheet_id, titre_onglet)
    if sheet_id is None:
        return False
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id, "dimension": "ROWS",
                    "startIndex": ligne - 1, "endIndex": ligne,
                },
            },
        }]}).execute()
    return True


def _chercher_et_supprimer(sheets_svc, spreadsheet_id, titre_onglet,
                            idx_nom, idx_date, nb_colonnes, nom_complet_cible, jour_str,
                            idx_prenom=None):
    """Cherche, dans les nb_colonnes premieres colonnes de `titre_onglet`, une
    ligne dont le nom (colonne idx_nom, complete de idx_prenom si fourni, les
    deux colonnes etant alors combinees avant comparaison) = nom_complet_cible
    (compare via _normaliser) et la colonne idx_date = jour_str (JJ/MM) ; si
    trouvee, supprime la ligne.
    Retourne True si une ligne a ete trouvee et supprimee."""
    derniere_colonne = chr(ord('A') + nb_colonnes - 1)
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{titre_onglet}'!A2:{derniere_colonne}{1 + _MAX_LIGNES}").execute()
    lignes = res.get("values", [])
    for i, row in enumerate(lignes):
        nom_val = row[idx_nom].strip() if idx_nom < len(row) and row[idx_nom] else ""
        if idx_prenom is not None:
            prenom_val = row[idx_prenom].strip() if idx_prenom < len(row) and row[idx_prenom] else ""
            nom_val = f"{nom_val} {prenom_val}".strip()
        date_val = row[idx_date].strip() if idx_date < len(row) and row[idx_date] else ""
        if not nom_val or not date_val:
            continue
        if _normaliser(nom_val) != nom_complet_cible or date_val != jour_str:
            continue
        ligne = 2 + i
        if not _supprimer_ligne(sheets_svc, spreadsheet_id, titre_onglet, ligne):
            return False
        print(f"    LIVRAISON DRIVE 2026 / {titre_onglet} L{ligne} : "
              f"{nom_val} annulee -> ligne supprimee.")
        return True
    return False


def _chercher_et_supprimer_numero(sheets_svc, spreadsheet_id, titre_onglet,
                                   idx_numero, nb_colonnes, numero_cible):
    """Cherche, dans les nb_colonnes premieres colonnes de `titre_onglet`, une
    ligne dont la colonne idx_numero = numero_cible (n° de commande) ; si
    trouvee, supprime la ligne. Le n° de commande identifie sans ambiguite la
    ligne, contrairement au nom+jour qui peut correspondre a plusieurs
    commandes du meme client le meme jour.
    Retourne True si une ligne a ete trouvee et supprimee."""
    derniere_colonne = chr(ord('A') + nb_colonnes - 1)
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{titre_onglet}'!A2:{derniere_colonne}{1 + _MAX_LIGNES}").execute()
    lignes = res.get("values", [])
    for i, row in enumerate(lignes):
        numero_val = row[idx_numero].strip() if idx_numero < len(row) and row[idx_numero] else ""
        if not numero_val or numero_val != numero_cible:
            continue
        ligne = 2 + i
        if not _supprimer_ligne(sheets_svc, spreadsheet_id, titre_onglet, ligne):
            return False
        print(f"    LIVRAISON DRIVE 2026 / {titre_onglet} L{ligne} : "
              f"commande {numero_cible} annulee -> ligne supprimee.")
        return True
    return False


def annuler_commande_livraison(sheets_svc, spreadsheet_id, nom, prenom, date_cde_str, numero_commande=None):
    """A appeler pour une commande en LIVRAISON annulee ou remplacee par une
    nouvelle commande, afin que l'ancienne ligne ne reste pas (ou ne soit pas
    dupliquee) dans LIVRAISON DRIVE 2026.
    Localise la ligne correspondante dans LIVRAISON DRIVE 2026 — d'abord
    l'onglet du mois de la commande, puis EN ATTENTE si absente du mois — et
    la supprime.
    Dans EN ATTENTE, le matching se fait en priorite sur `numero_commande`
    (identifiant fiable, contrairement au nom+jour qui peut correspondre a
    plusieurs commandes du meme client le meme jour), avec repli sur
    nom+jour si le numero est absent ou introuvable."""
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
        if onglet_mois and _chercher_et_supprimer(
                sheets_svc, spreadsheet_id, onglet_mois,
                idx_nom=2, idx_prenom=3, idx_date=1, nb_colonnes=5,
                nom_complet_cible=nom_complet_cible, jour_str=jour_str):
            return

        onglet_attente = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
        if onglet_attente:
            numero_str = str(numero_commande).strip() if numero_commande else ""
            if numero_str and _chercher_et_supprimer_numero(
                    sheets_svc, spreadsheet_id, onglet_attente,
                    idx_numero=3, nb_colonnes=5, numero_cible=numero_str):
                return
            if _chercher_et_supprimer(
                    sheets_svc, spreadsheet_id, onglet_attente,
                    idx_nom=0, idx_prenom=1, idx_date=2, nb_colonnes=5,
                    nom_complet_cible=nom_complet_cible, jour_str=jour_str):
                return

        print(f"    Aucune ligne LIVRAISON DRIVE 2026 trouvee pour {nom} {prenom} "
              f"({date_cde_str}), rien a supprimer.")
    except Exception as e:
        print(f"    Annulation LIVRAISON DRIVE 2026 echouee ({nom} {prenom}) : {e}")


def traiter_commande_livraison(sheets_svc, spreadsheet_id, nom, prenom, date_cde_str,
                                numero_commande=None, maintenant=None,
                                shopopop_token=None, shopopop_drive_id=None):
    """A appeler pour chaque commande en LIVRAISON (detectee via ',Livraison,'
    sur la 2e ligne de bon_prepa.txt). `date_cde_str` est au format
    JJ/MM/AAAA (extrait du PDF par extraire_client_creneau_pdf). `numero_commande`
    est reporte dans la colonne N° cde/N° commande (onglet du mois ou EN
    ATTENTE selon le cas), pour identifier la ligne sans ambiguite en cas
    d'annulation. `shopopop_token`/
    `shopopop_drive_id` (obtenus via connecter_shopopop) servent a recuperer
    la distance (colonne km), y compris quand la commande part en EN ATTENTE
    (la livraison est deja visible sur Shopopop des la commande, meme si sa
    date est trop lointaine pour etre renseignee tout de suite dans l'onglet
    du mois).
    Retourne True si la commande a ete inscrite mais sans km (a signaler par
    email par l'appelant), False sinon (km trouve, ou commande non inscrite)."""
    if not sheets_svc or not spreadsheet_id:
        print("    Sheets/LIVRAISON DRIVE 2026 indisponible, commande ignoree.")
        return False
    if not (nom or prenom) or not date_cde_str:
        print("    Nom/prenom/date introuvables dans le PDF, livraison Drive ignoree.")
        return False
    try:
        date_cde = datetime.strptime(date_cde_str, "%d/%m/%Y").date()
    except ValueError:
        print(f"    Date de commande illisible ({date_cde_str}), livraison Drive ignoree.")
        return False

    maintenant = maintenant or datetime.now(_TZ)
    aujourdhui = maintenant.date()
    nom_complet = f"{nom} {prenom}".strip().upper()

    try:
        km = None
        if shopopop_token:
            km = shopopop.distance_km(shopopop_token, shopopop_drive_id, date_cde, nom_complet)
            if km is None:
                print(f"    km Shopopop introuvable pour {nom_complet}, nouvelle tentative dans "
                      f"{_DELAI_RETRY_KM_SECONDES}s (commande tres recente, pas encore synchronisee ?)...")
                time.sleep(_DELAI_RETRY_KM_SECONDES)
                km = shopopop.distance_km(shopopop_token, shopopop_drive_id, date_cde, nom_complet)
                if km is None:
                    print(f"    km Shopopop toujours introuvable pour {nom_complet} apres nouvelle "
                          f"tentative (sera retente lors des prochaines executions).")
        else:
            print(f"    Pas de token Shopopop, km non recherche pour {nom_complet}.")
        nom_maj, prenom_maj = nom.strip().upper(), prenom.strip().upper()
        if date_cde == aujourdhui or (
                date_cde == _lendemain_ouvre(aujourdhui) and maintenant.hour >= 14):
            _inscrire_commande(sheets_svc, spreadsheet_id, date_cde, nom_maj, prenom_maj,
                                numero_commande, km)
        else:
            _inscrire_en_attente(sheets_svc, spreadsheet_id, date_cde, nom_maj, prenom_maj,
                                  numero_commande, km)
        return km is None
    except Exception as e:
        print(f"    Ecriture LIVRAISON DRIVE 2026 echouee ({nom_complet}) : {e}")
        return False


def _lister_km_manquants(sheets_svc, spreadsheet_id, maintenant=None):
    """Repere, sans appeler Shopopop, les lignes LIVRAISON dont la colonne km
    est encore vide : onglets du mois courant et du mois du lendemain ouvre
    (au cas ou la date de livraison soit a cheval sur un changement de mois),
    plus l'onglet EN ATTENTE. Ignore les lignes dont la date de livraison
    remonte a plus de _FENETRE_RETENTATIVE_JOURS jours (deja signalees par
    email, pas la peine de continuer a les retenter indefiniment). Retourne
    [(onglet, ligne, nom_complet, date_cible), ...]."""
    maintenant = maintenant or datetime.now(_TZ)
    aujourdhui = maintenant.date()
    limite = aujourdhui - timedelta(days=_FENETRE_RETENTATIVE_JOURS)

    a_retenter = []

    mois_cibles = {MOIS_FR[aujourdhui.month - 1], MOIS_FR[_lendemain_ouvre(aujourdhui).month - 1]}
    for mois in mois_cibles:
        onglet = _trouver_onglet(sheets_svc, spreadsheet_id, mois)
        if not onglet:
            continue
        res = sheets_svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{onglet}'!A2:E{1 + _MAX_LIGNES}").execute()
        for i, row in enumerate(res.get("values", [])):
            date_val = row[1].strip() if len(row) > 1 and row[1] else ""
            nom = row[2].strip() if len(row) > 2 and row[2] else ""
            prenom = row[3].strip() if len(row) > 3 and row[3] else ""
            km_val = row[4].strip() if len(row) > 4 and row[4] else ""
            if not date_val or not nom or km_val:
                continue
            cible = _parser_jour(date_val, aujourdhui)
            if cible is None or cible < limite:
                continue
            a_retenter.append((onglet, 2 + i, f"{nom} {prenom}".strip(), cible))

    onglet_attente = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
    if onglet_attente:
        res = sheets_svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{onglet_attente}'!A2:E{1 + _MAX_LIGNES}").execute()
        for i, row in enumerate(res.get("values", [])):
            nom = row[0].strip() if len(row) > 0 and row[0] else ""
            prenom = row[1].strip() if len(row) > 1 and row[1] else ""
            jour = row[2].strip() if len(row) > 2 and row[2] else ""
            km_val = row[4].strip() if len(row) > 4 and row[4] else ""
            if not nom or not jour or km_val:
                continue
            cible = _parser_jour(jour, aujourdhui)
            if cible is None or cible < limite:
                continue
            a_retenter.append((onglet_attente, 2 + i, f"{nom} {prenom}".strip(), cible))

    return a_retenter


def km_manquants_en_attente(sheets_svc, spreadsheet_id, maintenant=None):
    """True s'il existe au moins une ligne LIVRAISON avec un km encore vide a
    retenter (cf. _lister_km_manquants). Ne fait que lire le classeur (aucun
    appel Shopopop) : sert a decider, dans auto_prepa.py, s'il vaut la peine
    de se connecter a Shopopop meme quand aucune nouvelle commande LIVRAISON
    n'a ete rencontree lors du run en cours."""
    return bool(_lister_km_manquants(sheets_svc, spreadsheet_id, maintenant))


def retenter_km_manquants(sheets_svc, spreadsheet_id, shopopop_token, shopopop_drive_id, maintenant=None):
    """Reparcourt les lignes LIVRAISON dont le km est reste vide (voir
    _lister_km_manquants) et retente leur recuperation aupres de Shopopop —
    la livraison a pu ne pas etre encore synchronisee cote Shopopop lors du
    ou des essais precedents (recherche initiale + retentative dans
    traiter_commande_livraison). Appelee a chaque execution du workflow
    (auto_prepa.py), elle complete ainsi progressivement les km manques d'une
    execution a l'autre, jusqu'a _FENETRE_RETENTATIVE_JOURS jours apres la
    date de livraison. Met a jour la cellule km (colonne E) des que trouve.
    Retourne le nombre de km recuperes."""
    if not shopopop_token:
        return 0
    a_retenter = _lister_km_manquants(sheets_svc, spreadsheet_id, maintenant)
    if not a_retenter:
        return 0

    print(f"    {len(a_retenter)} livraison(s) en attente de km, nouvelle tentative...")
    trouves = 0
    for onglet, ligne, nom_complet, cible in a_retenter:
        km = shopopop.distance_km(shopopop_token, shopopop_drive_id, cible, nom_complet)
        if km is None:
            continue
        sheets_svc.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=f"'{onglet}'!E{ligne}",
            valueInputOption="USER_ENTERED", body={"values": [[km]]}).execute()
        print(f"    LIVRAISON DRIVE 2026 / {onglet} L{ligne} : km recupere en retentative "
              f"pour {nom_complet} -> {km} km.")
        trouves += 1
    return trouves


def lire_commandes_jour(sheets_svc, spreadsheet_id, aujourdhui):
    """Retourne [(ligne, nom_complet, km), ...] des commandes en LIVRAISON
    inscrites pour `aujourdhui` dans l'onglet du mois de `aujourdhui` de
    LIVRAISON DRIVE 2026 (colonne B = Date au format JJ/MM, colonne C = Nom,
    colonne D = Prénom, colonne E = km ; nom_complet = "Nom Prénom", pour la
    recherche cote Shopopop). `ligne` (numero de ligne dans l'onglet) sert a
    cibler la cellule a colorer via marquer_livree(). Utilisé par le
    workflow "Vérif LAD" pour vérifier chaque soir que ces commandes ont
    bien été livrées côté Shopopop."""
    mois = MOIS_FR[aujourdhui.month - 1]
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, mois)
    if not onglet:
        print(f"    Onglet '{mois}' introuvable dans LIVRAISON DRIVE 2026.")
        return []
    jour_str = aujourdhui.strftime("%d/%m")
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{onglet}'!A2:E{1 + _MAX_LIGNES}").execute()
    commandes = []
    for i, row in enumerate(res.get("values", [])):
        date_val = row[1].strip() if len(row) > 1 and row[1] else ""
        nom = row[2].strip() if len(row) > 2 and row[2] else ""
        prenom = row[3].strip() if len(row) > 3 and row[3] else ""
        km = row[4].strip() if len(row) > 4 and row[4] else ""
        if date_val == jour_str and nom:
            commandes.append((2 + i, f"{nom} {prenom}".strip(), km))
    return commandes


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


def promotion_en_attente_necessaire(sheets_svc, spreadsheet_id, maintenant=None):
    """True s'il existe au moins une ligne dans EN ATTENTE dont la date cible
    est le lendemain ouvre (par rapport a `maintenant`), c'est-a-dire une
    ligne que traiter_en_attente() devrait promouvoir dans l'onglet du mois.
    Ne fait qu'une lecture (aucune ecriture) : sert de garde-fou, appele a
    chaque execution d'auto_prepa.py une fois 14h passees, pour rattraper la
    promotion si le workflow dedie declenche a 14h a ete manque (les
    declenchements 'schedule' GitHub Actions pile a l'heure ronde peuvent
    etre retardes voire sautes en cas de forte charge)."""
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
    if not onglet:
        return False

    maintenant = maintenant or datetime.now(_TZ)
    aujourdhui = maintenant.date()
    lendemain = _lendemain_ouvre(aujourdhui)

    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!B2:B{1 + _MAX_LIGNES}").execute()
    for row in res.get("values", []):
        jour = row[0].strip() if row and row[0] else ""
        if jour and _parser_jour(jour, aujourdhui) == lendemain:
            return True
    return False


def traiter_en_attente(sheets_svc, spreadsheet_id, maintenant=None):
    """Renseigne dans l'onglet du mois les commandes de EN ATTENTE prevues
    pour le lendemain ouvre (par rapport a `maintenant` ; le lendemain, sauf
    le samedi ou c'est le lundi, le dimanche etant ferme), et les retire de
    EN ATTENTE. Appelee par le workflow declenche a 14h, et en garde-fou par
    auto_prepa.py (cf. promotion_en_attente_necessaire) si ce declenchement a
    ete manque. Le km, deja recupere sur Shopopop au moment ou la commande a
    ete mise en EN ATTENTE (colonne E), est simplement reporte tel quel — pas
    de nouvel appel Shopopop ici."""
    onglet = _trouver_onglet(sheets_svc, spreadsheet_id, ONGLET_EN_ATTENTE)
    if not onglet:
        print(f"  Onglet '{ONGLET_EN_ATTENTE}' introuvable, rien a traiter.")
        return

    maintenant = maintenant or datetime.now(_TZ)
    aujourdhui = maintenant.date()
    lendemain = _lendemain_ouvre(aujourdhui)

    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A2:E{1 + _MAX_LIGNES}").execute()
    lignes = res.get("values", [])

    a_traiter, a_garder = [], []
    for row in lignes:
        nom = row[0].strip() if len(row) > 0 and row[0] else ""
        prenom = row[1].strip() if len(row) > 1 and row[1] else ""
        jour = row[2].strip() if len(row) > 2 and row[2] else ""
        numero_commande = row[3].strip() if len(row) > 3 and row[3] else ""
        km = row[4].strip() if len(row) > 4 and row[4] else ""
        if not nom and not jour:
            continue
        cible = _parser_jour(jour, aujourdhui) if jour else None
        if cible == lendemain:
            a_traiter.append((cible, nom, prenom, numero_commande, km))
        else:
            a_garder.append((nom, prenom, jour, numero_commande, km))

    print(f"  EN ATTENTE : {len(a_traiter)} commande(s) pour le {lendemain.strftime('%d/%m')}, "
          f"{len(a_garder)} conservee(s).")

    for cible, nom, prenom, numero_commande, km in a_traiter:
        _inscrire_commande(sheets_svc, spreadsheet_id, cible, nom, prenom,
                            numero_commande or None, km or None)

    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{onglet}'!A2:E{1 + _MAX_LIGNES}", body={}).execute()
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
