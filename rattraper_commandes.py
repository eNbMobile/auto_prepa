#!/usr/bin/env python3
"""
Script de rattrapage a usage unique : le 05/09/2026 vers 13h46, les fichiers
de config gencod_adresses.csv et gencod_nomenclatures.csv ont ete convertis
en Google Sheets natifs sur Drive (cf. reparer_config_csv.py), rendant leur
telechargement impossible (HTTP 403 "Only files with binary content can be
downloaded"). Consequence : entre 2026-09-05T11:55 et 2026-09-06T09:19
(bug corrige), toutes les commandes recues ont bien ete confirmees par email
(et leur email marque comme "traite" cote Gmail), mais leur bon_prepa n'a
jamais ete genere, faute de ces deux CSV.

Ce script retelecharge le PDF joint a l'email de confirmation de chacune des
commandes touchees (liste ci-dessous, etablie a partir de
auto_prepa_state.json et des emails Gmail label BDC_Conf_Traites recus
depuis le 05/09) et relance leur generation via auto_prepa.traiter_commande_pdf,
exactement comme le ferait un run normal.

A executer une seule fois, apres avoir remis gencod_adresses.csv et
gencod_nomenclatures.csv en CSV plat sur Drive (reparer_config_csv.py).
Idempotent : toute commande deja presente dans l'historique
(auto_prepa_state.json) est ignoree.
"""
import base64
import os
import re
import sys

from googleapiclient.discovery import build

import auto_prepa as ap

# Commandes confirmees par email pendant la panne (05/09 11h55 -> 06/09
# 09h19) mais jamais preparees. 54607056 est volontairement exclue : elle a
# ete annulee et remplacee par la commande 54608063 (email de modification
# client recu le 05/09 a 13h31), elle ne doit donc pas etre preparee.
COMMANDES_A_RATTRAPER = [
    "54604892", "54605523", "54605525", "54605547", "54605800", "54605807",
    "54605876", "54606498", "54606594", "54606725", "54606840", "54607632",
    "54607773", "54607918", "54608063", "54608210", "54608287", "54608611",
    "54608662", "54608905", "54608973", "54609954", "54610040", "54611850",
    "54612961", "54612981", "54613264", "54613615", "54614254", "54614392",
]


def _telecharger_confirmation(gmail_svc, numero):
    """Retrouve l'email de confirmation deja recu pour ce numero de commande
    et telecharge son bon_encaissement.pdf dans CACHE_DIR. Retourne
    (dossier_jj_mm, dossier_mm_aaaa) ou None si introuvable."""
    q = f'from:{ap.GMAIL_CONF_FROM} subject:"{ap.GMAIL_CONF_SUBJECT}" "N° cde:{numero}"'
    res = gmail_svc.users().messages().list(userId='me', q=q, maxResults=5).execute()
    messages = res.get('messages', [])
    if not messages:
        print(f"  [{numero}] email de confirmation introuvable, ignore.")
        return None

    msg = gmail_svc.users().messages().get(
        userId='me', id=messages[0]['id'], format='full').execute()
    headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
    subject = headers.get('Subject', '')

    match_date = re.search(r'(\d{2}/\d{2}/\d{4})', subject)
    dossier_jj_mm = match_date.group(1)[:5].replace('/', '_') if match_date else ""
    dossier_mm_aaaa = match_date.group(1)[3:].replace('/', '_') if match_date else ""

    attachment_id = None
    for part in ap._iter_parts(msg['payload']):
        if part.get('filename', '').lower() == 'bon_encaissement.pdf':
            attachment_id = part['body'].get('attachmentId')
            break
    if not attachment_id:
        print(f"  [{numero}] aucun bon_encaissement.pdf dans l'email, ignore.")
        return None

    filename = f"BonDeCommande_{numero}.pdf"
    cache_path = os.path.join(ap.CACHE_DIR, filename)
    if not os.path.exists(cache_path):
        att = gmail_svc.users().messages().attachments().get(
            userId='me', messageId=messages[0]['id'], id=attachment_id).execute()
        pdf_bytes = base64.urlsafe_b64decode(att['data'] + '==')
        with open(cache_path, 'wb') as f:
            f.write(pdf_bytes)
    return dossier_jj_mm, dossier_mm_aaaa


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)
    os.makedirs(ap.CACHE_DIR, exist_ok=True)
    os.makedirs(ap.BDC_DIR, exist_ok=True)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)
    sheets_svc = build("sheets", "v4", credentials=creds)

    ap._charger_config(drive_svc)
    ap._charger_gmail_filters(drive_svc)
    ap.telecharger_config_drive(drive_svc)

    traites = ap.charger_traites(drive_svc)
    processed = set()
    shopopop_token, shopopop_drive_id, shopopop_connecte = None, None, False

    for numero in COMMANDES_A_RATTRAPER:
        pdf = f"BonDeCommande_{numero}.pdf"
        if pdf in traites:
            print(f"  [{numero}] deja dans l'historique, ignore.")
            continue

        dossiers = _telecharger_confirmation(gmail_svc, numero)
        if dossiers is None:
            continue
        dossier_jj_mm, dossier_mm_aaaa = dossiers

        statut, shopopop_token, shopopop_drive_id, shopopop_connecte = ap.traiter_commande_pdf(
            drive_svc, gmail_svc, sheets_svc, pdf, dossier_jj_mm, dossier_mm_aaaa,
            "rattrapage", shopopop_token, shopopop_drive_id, shopopop_connecte)

        if statut == "stop":
            print("ARRET : gencod_adresses.csv / gencod_nomenclatures.csv toujours indisponibles"
                  " (executer reparer_config_csv.py avant ce script).")
            ap.sauvegarder_traites(drive_svc, traites | processed)
            sys.exit(1)
        if statut == "processed":
            processed.add(pdf)
        else:
            print(f"  [{numero}] echec de generation, a retenter manuellement.")

    ap.sauvegarder_traites(drive_svc, traites | processed)
    print(f"\n{len(processed)}/{len(COMMANDES_A_RATTRAPER)} commande(s) rattrapee(s).")


if __name__ == "__main__":
    main()
