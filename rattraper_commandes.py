#!/usr/bin/env python3
"""
Script de rattrapage a usage unique, incident du 05-06/09/2026 :

1) Le 05/09 vers 13h46, gencod_adresses.csv et gencod_nomenclatures.csv ont
   ete convertis en Google Sheets natifs sur Drive, rendant leur
   telechargement impossible (403). Consequence : de 11h55 (05/09) a 09h19
   (06/09), plus aucun bon_prepa n'etait genere.
2) Une fois le mimetype/separateur corriges (a la main), un second probleme
   est apparu : gencod_nomenclatures.csv ne permettait plus de retrouver la
   bonne adresse de rayon (le %d scanne dans prepa_drive_degrade retombait a
   0), produisant des dizaines d'anomalies d'adressage par commande au lieu
   de 1-3 normalement. Corrige en reuploadant les anciennes versions valides
   de tous les CSV de config.

Toutes les commandes recues entre le dernier bon_prepa correctement genere
(N° cde 54604128, 05/09 11h30) et maintenant ont donc pu etre traitees avec
des donnees d'adressage corrompues (echec pur et simple, ou bon_prepa genere
mais avec des adresses fausses). Ce script les identifie dynamiquement
(recherche Gmail, pas de liste figee) et regenere leur bon_prepa avec les
CSV desormais corrects - y compris celles deja presentes dans l'historique
auto_prepa_state.json, puisque leur premier passage a pu produire un bon
errone.

Pour eviter de dupliquer les lignes de suivi (LIVRAISON DRIVE 2026, Avoir/
Commandes en cours) sur les commandes deja traitees une premiere fois
aujourd'hui, chaque commande voit sa ligne existante nettoyee (si presente)
juste avant d'etre regeneree.

A executer une seule fois, apres verification que gencod_adresses.csv et
gencod_nomenclatures.csv sont a nouveau corrects sur Drive.
"""
import base64
import os
import re
import sys

from googleapiclient.discovery import build

import auto_prepa as ap

SEUIL_NUMERO = 54604128  # dernier BonDeCommande genere correctement avant l'incident
DATE_RECHERCHE = "2026/09/05"


def _lister_messages(gmail_svc, query):
    """Pagine sur l'API Gmail et retourne tous les message id correspondant a `query`."""
    ids = []
    page_token = None
    while True:
        res = gmail_svc.users().messages().list(
            userId='me', q=query, maxResults=100, pageToken=page_token).execute()
        ids += [m['id'] for m in res.get('messages', [])]
        page_token = res.get('nextPageToken')
        if not page_token:
            break
    return ids


def _sujet(gmail_svc, message_id):
    msg = gmail_svc.users().messages().get(
        userId='me', id=message_id, format='metadata', metadataHeaders=['Subject']).execute()
    return next((h['value'] for h in msg['payload']['headers'] if h['name'] == 'Subject'), '')


def _lister_confirmations_a_rattraper(gmail_svc):
    """Retourne {numero: message_id} pour toutes les confirmations recues
    depuis DATE_RECHERCHE avec numero > SEUIL_NUMERO."""
    q = f'from:{ap.GMAIL_CONF_FROM} subject:"{ap.GMAIL_CONF_SUBJECT}" after:{DATE_RECHERCHE}'
    resultats = {}
    for message_id in _lister_messages(gmail_svc, q):
        match = re.search(r'N°\s*cde:(\d+)', _sujet(gmail_svc, message_id))
        if not match:
            continue
        numero = int(match.group(1))
        if numero > SEUIL_NUMERO:
            resultats[numero] = message_id
    return resultats


def _lister_commandes_exclues(gmail_svc):
    """Numeros de commande annules/remplaces depuis DATE_RECHERCHE : a ne pas
    (re)generer, la version valable est celle qui les remplace."""
    exclus = set()
    for sujet_filtre in ap.GMAIL_MODIF_SUBJECTS:
        q = f'subject:"{sujet_filtre}" after:{DATE_RECHERCHE}'
        for message_id in _lister_messages(gmail_svc, q):
            subject = _sujet(gmail_svc, message_id)
            match_modif = re.search(r'N°\s*cde:(\d+).*?N°\s*cde:(\d+)', subject)
            match_annul = re.search(r'N°\s*:\s*(\d+)', subject)
            if match_modif:
                exclus.add(int(match_modif.group(1)))
            elif match_annul:
                exclus.add(int(match_annul.group(1)))
    return exclus


def _telecharger_pdf(gmail_svc, numero, message_id):
    """Telecharge le bon_encaissement.pdf de `message_id` dans CACHE_DIR.
    Retourne (dossier_jj_mm, dossier_mm_aaaa) ou None si introuvable."""
    msg = gmail_svc.users().messages().get(userId='me', id=message_id, format='full').execute()
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
            userId='me', messageId=message_id, id=attachment_id).execute()
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

    confirmations = _lister_confirmations_a_rattraper(gmail_svc)
    exclus = _lister_commandes_exclues(gmail_svc)
    a_traiter = sorted(n for n in confirmations if n not in exclus)

    print(f"{len(confirmations)} confirmation(s) > {SEUIL_NUMERO} trouvee(s), "
          f"{len(exclus & confirmations.keys())} exclue(s) (annulee/remplacee), "
          f"{len(a_traiter)} a regenerer.")

    traites = ap.charger_traites(drive_svc)
    processed = set()
    shopopop_token, shopopop_drive_id, shopopop_connecte = None, None, False

    for numero in a_traiter:
        pdf = f"BonDeCommande_{numero}.pdf"
        dossiers = _telecharger_pdf(gmail_svc, numero, confirmations[numero])
        if dossiers is None:
            continue
        dossier_jj_mm, dossier_mm_aaaa = dossiers

        # Deja traitee une premiere fois aujourd'hui (avec des donnees
        # corrompues) : nettoie ses lignes de suivi avant de regenerer, pour
        # ne pas les dupliquer. No-op si la commande n'avait pas encore ete
        # traitee (pas de ligne existante).
        ap._traiter_annulation_livraison(drive_svc, sheets_svc, str(numero))
        ap.supprimer_commande_avoir_drive(drive_svc, str(numero))

        statut, shopopop_token, shopopop_drive_id, shopopop_connecte = ap.traiter_commande_pdf(
            drive_svc, gmail_svc, sheets_svc, pdf, dossier_jj_mm, dossier_mm_aaaa,
            "rattrapage", shopopop_token, shopopop_drive_id, shopopop_connecte)

        if statut == "stop":
            print("ARRET : gencod_adresses.csv / gencod_nomenclatures.csv toujours indisponibles"
                  " ou invalides.")
            ap.sauvegarder_traites(drive_svc, traites | processed)
            sys.exit(1)
        if statut == "processed":
            processed.add(pdf)
        else:
            print(f"  [{numero}] echec de generation, a retenter manuellement.")

    ap.sauvegarder_traites(drive_svc, traites | processed)
    print(f"\n{len(processed)}/{len(a_traiter)} commande(s) regeneree(s).")


if __name__ == "__main__":
    main()
