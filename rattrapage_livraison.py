#!/usr/bin/env python3
"""
Rattrapage des commandes en LIVRAISON absentes de LIVRAISON DRIVE 2026 pour
un ou plusieurs jours de livraison donnes.

Pourquoi : le 02/10/2026, l'onglet OCTOBRE n'existait pas encore ; toutes
les commandes LIVRAISON du 02/10 et du 03/10 ont echoue sur "onglet
introuvable" (et celles de EN ATTENTE promues a 14h ont ete effacees sans
etre reportees). livraison_drive cree desormais l'onglet manquant, mais les
commandes deja passees restent a reinscrire : c'est ce que fait ce script.

Source : les emails de confirmation Systeme U dont le sujet porte la date de
livraison (" Confirmation commande   03/10/2026 à 17:00 -- ... N° cde:...").
Une commande est en LIVRAISON quand son mode de remise est "Je reçois mes
courses chez moi" (corps de l'email). Nom/prenom sont extraits du
bon_encaissement.pdf joint, exactement comme lors du traitement normal.

Pour chaque commande LIVRAISON du jour :
- annulee/remplacee (registre des annulations)       -> ignoree
- deja dans l'onglet du mois (meme n° de commande)   -> ignoree
- presente dans EN ATTENTE (ex. 55792220, inscrite au 22/09 au lieu du
  03/10 par l'ancienne reinscription des commandes modifiees) -> retiree de
  EN ATTENTE puis inscrite au bon jour
- sinon                                              -> inscrite dans
  l'onglet du mois, a sa date, avec le km Shopopop ; km introuvable (la
  livraison n'est plus dans les "Programmees" une fois faite) -> cellule km
  en orange, a completer a la main (aucun email envoye).

Usage :
  rattrapage_livraison.py --dates "02/10/2026 03/10/2026" [--simulation]
  rattrapage_livraison.py --ajouter "55256662;22/09/2026;ROBERT;NADINE;4,74"
"""

import argparse
import base64
import html
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import auto_prepa as ap
import livraison_drive as ld

_RE_NUMERO = re.compile(r'N°\s*cde\s*[:\s]+(\d+)')

# Pause entre deux lectures d'email : une journee compte ~200 confirmations,
# lues d'affilee elles depassent le quota Gmail "Units per minute per user"
# (HttpError 403 rateLimitExceeded, run du 03/10/2026).
_PAUSE_GMAIL_SECONDES = 0.5

# Pause apres chaque commande inscrite : une inscription coute une dizaine de
# lectures Sheets, et le quota est de 60 lectures/minute (HttpError 429 au
# 9e enregistrement du run du 03/10/2026).
_PAUSE_SHEETS_SECONDES = 12
_TENTATIVES_GMAIL = 6


def _executer(requete):
    """execute() avec retentatives (attente croissante) sur depassement de
    quota Gmail (403 rateLimitExceeded / 429) et erreurs serveur."""
    for tentative in range(_TENTATIVES_GMAIL):
        try:
            return requete.execute()
        except HttpError as e:
            statut = getattr(e.resp, "status", 0)
            detail = (e.content or b"").decode("utf-8", errors="replace") + str(e)
            quota = statut == 429 or (statut == 403 and "rateLimitExceeded" in detail)
            if not (quota or statut >= 500) or tentative == _TENTATIVES_GMAIL - 1:
                raise
            attente = 2 ** (tentative + 2)
            print(f"  Gmail {statut} (quota), nouvelle tentative dans {attente}s...")
            time.sleep(attente)


def lire_dates(texte):
    """Dates JJ/MM/AAAA saisies (espaces, virgules...), dans l'ordre."""
    dates = []
    for d in re.findall(r"\d{2}/\d{2}/\d{4}", texte or ""):
        datetime.strptime(d, "%d/%m/%Y")  # leve ValueError si invalide
        if d not in dates:
            dates.append(d)
    return dates


def _texte_email(payload):
    """Texte brut du corps de l'email (parties text/plain et text/html,
    balises retirees)."""
    morceaux = []
    for part in ap._iter_parts(payload):
        if part.get("mimeType") not in ("text/plain", "text/html"):
            continue
        data = part.get("body", {}).get("data")
        if not data:
            continue
        brut = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        morceaux.append(html.unescape(re.sub(r"<[^>]+>", " ", brut)))
    return " ".join(morceaux)


def est_livraison(texte_email):
    """True si le mode de remise est la livraison a domicile ("Je reçois mes
    courses chez moi"), par opposition au retrait au drive."""
    return "CHEZ MOI" in ld._normaliser(re.sub(r"\s+", " ", texte_email))


def commandes_livraison_du_jour(gmail_svc, date_str):
    """[(numero, nom, prenom), ...] des commandes LIVRAISON dont l'email de
    confirmation annonce une livraison le `date_str` (JJ/MM/AAAA)."""
    q = f'from:{ap.GMAIL_CONF_FROM} subject:"{ap.GMAIL_CONF_SUBJECT}" subject:"{date_str}"'
    messages, page = [], None
    while True:
        res = _executer(gmail_svc.users().messages().list(
            userId="me", q=q, maxResults=100, pageToken=page))
        messages += res.get("messages", [])
        page = res.get("nextPageToken")
        if not page:
            break

    commandes, vus = [], set()
    for m in messages:
        time.sleep(_PAUSE_GMAIL_SECONDES)
        msg = _executer(gmail_svc.users().messages().get(userId="me", id=m["id"], format="full"))
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        sujet = headers.get("Subject", "")
        match_num = _RE_NUMERO.search(sujet)
        if not match_num or date_str not in sujet:
            continue
        numero = match_num.group(1)
        if numero in vus:
            continue
        vus.add(numero)
        if not est_livraison(_texte_email(msg["payload"])):
            continue

        attachment_id = next(
            (p["body"].get("attachmentId") for p in ap._iter_parts(msg["payload"])
             if p.get("filename", "").lower() == "bon_encaissement.pdf"), None)
        if not attachment_id:
            print(f"  {numero} : pas de bon_encaissement.pdf, ignoree.")
            continue
        att = _executer(gmail_svc.users().messages().attachments().get(
            userId="me", messageId=m["id"], id=attachment_id))
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(base64.urlsafe_b64decode(att["data"] + "=="))
            chemin = f.name
        try:
            pt = subprocess.run(["pdftotext", "-layout", chemin, "-"],
                                capture_output=True, text=True)
        finally:
            os.remove(chemin)
        _, nom, prenom, _, _ = ap.extraire_client_creneau_pdf(pt.stdout)
        if not (nom or prenom):
            print(f"  {numero} : nom/prenom illisibles dans le PDF, ignoree.")
            continue
        commandes.append((numero, nom.strip().upper(), prenom.strip().upper()))
    return sorted(commandes)


def _numeros_onglet(sheets_svc, spreadsheet_id, onglet, idx_numero):
    if not onglet:
        return set()
    res = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{onglet}'!A2:E{1 + ld._MAX_LIGNES}").execute()
    return {row[idx_numero].strip() for row in res.get("values", [])
            if len(row) > idx_numero and row[idx_numero]}


def rattraper(sheets_svc, spreadsheet_id, gmail_svc, drive_svc, dates, simulation=False):
    annulees = ap.commandes_annulees(drive_svc)
    token, drive_id = (None, None) if simulation else ld.connecter_shopopop(drive_svc)
    a_completer = []
    for date_str in dates:
        cible = datetime.strptime(date_str, "%d/%m/%Y").date()
        print(f"\nLivraisons du {date_str} :")
        commandes = commandes_livraison_du_jour(gmail_svc, date_str)
        print(f"  {len(commandes)} commande(s) LIVRAISON confirmee(s) par email.")
        onglet_mois = ld._trouver_onglet(sheets_svc, spreadsheet_id, ld.MOIS_FR[cible.month - 1])
        deja = _numeros_onglet(sheets_svc, spreadsheet_id, onglet_mois, 0)
        for numero, nom, prenom in commandes:
            if numero in annulees:
                print(f"  {numero} {nom} {prenom} : annulee/remplacee, ignoree.")
                continue
            if numero in deja:
                print(f"  {numero} {nom} {prenom} : deja inscrite, rien a faire.")
                continue
            onglet_attente = ld._trouver_onglet(sheets_svc, spreadsheet_id, ld.ONGLET_EN_ATTENTE)
            en_attente = numero in _numeros_onglet(sheets_svc, spreadsheet_id, onglet_attente, 3)
            if simulation:
                print(f"  {numero} {nom} {prenom} : A INSCRIRE"
                      + (" (et a retirer de EN ATTENTE)" if en_attente else "") + " [simulation]")
                continue
            if en_attente:
                ld._chercher_et_supprimer_numero(sheets_svc, spreadsheet_id, onglet_attente,
                                                 idx_numero=3, nb_colonnes=5, numero_cible=numero)
            km = ld.shopopop.distance_km(token, drive_id, cible, f"{nom} {prenom}") if token else None
            ligne = ld._inscrire_commande(sheets_svc, spreadsheet_id, cible, nom, prenom, numero, km)
            if km is None:
                onglet = ld._trouver_onglet(sheets_svc, spreadsheet_id, ld.MOIS_FR[cible.month - 1])
                ld._marquer_km_a_completer(sheets_svc, spreadsheet_id, onglet, ligne)
                a_completer.append(f"{numero} {nom} {prenom} ({cible.strftime('%d/%m')})")
            deja.add(numero)
            time.sleep(_PAUSE_SHEETS_SECONDES)

    if a_completer:
        print(f"\n{len(a_completer)} km a completer a la main (cellule en orange) :")
        for c in a_completer:
            print(f"  - {c}")


def lire_ajouts(texte):
    """Lignes a ajouter telles quelles, separees par des retours a la ligne
    ou '|' : "NUMERO;JJ/MM/AAAA;NOM;PRENOM;KM" (KM facultatif). Retourne
    [(numero, date, nom, prenom, km_ou_None), ...]."""
    ajouts = []
    for bloc in re.split(r"[|\n]", texte or ""):
        champs = [c.strip() for c in bloc.split(";")]
        if len(champs) < 4 or not champs[0]:
            continue
        km = champs[4].replace(",", ".") if len(champs) > 4 and champs[4] else None
        ajouts.append((champs[0], datetime.strptime(champs[1], "%d/%m/%Y").date(),
                       champs[2].upper(), champs[3].upper(), float(km) if km else None))
    return ajouts


def ajouter(sheets_svc, spreadsheet_id, ajouts, simulation=False):
    """Inscrit dans l'onglet du mois des lignes donnees a la main (ex. une
    livraison passee supprimee a tort), sauf si le n° y figure deja."""
    for numero, cible, nom, prenom, km in ajouts:
        onglet = ld._trouver_onglet(sheets_svc, spreadsheet_id, ld.MOIS_FR[cible.month - 1])
        if numero in _numeros_onglet(sheets_svc, spreadsheet_id, onglet, 0):
            print(f"  {numero} {nom} {prenom} : deja dans '{onglet}', rien a faire.")
            continue
        if simulation:
            print(f"  {numero} {nom} {prenom} ({cible.strftime('%d/%m')}) : A AJOUTER [simulation]")
            continue
        ld._inscrire_commande(sheets_svc, spreadsheet_id, cible, nom, prenom, numero, km)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dates", default="", help="Jours de livraison JJ/MM/AAAA")
    parser.add_argument("--ajouter", default="",
                        help="Lignes a ajouter : NUMERO;JJ/MM/AAAA;NOM;PRENOM;KM (separees par |)")
    parser.add_argument("--simulation", action="store_true",
                        help="Affiche ce qui serait fait, sans rien ecrire")
    args = parser.parse_args()
    dates = lire_dates(args.dates)
    ajouts = lire_ajouts(args.ajouter)
    if not dates and not ajouts:
        print("ERREUR : ni date JJ/MM/AAAA ni ligne a ajouter.")
        sys.exit(1)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)
    sheets_svc = build("sheets", "v4", credentials=creds)
    ap._charger_gmail_filters(drive_svc)
    spreadsheet_id = ld._charger_config_livraison(drive_svc)
    if ajouts:
        ajouter(sheets_svc, spreadsheet_id, ajouts, args.simulation)
    if dates:
        rattraper(sheets_svc, spreadsheet_id, gmail_svc, drive_svc, dates, args.simulation)


if __name__ == "__main__":
    main()
