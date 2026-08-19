#!/usr/bin/env python3
"""
Workflow "Vérif LAD" : chaque soir, pour chaque commande du jour en
LIVRAISON (onglet du mois de LIVRAISON DRIVE 2026, colonne Date =
aujourd'hui), vérifie côté back-office Shopopop (nom/prénom du
destinataire) qu'elle n'est plus dans l'onglet "Programmées" — c'est-à-dire
qu'elle est bien passée dans "Livrées" (ou un autre statut final).

Une commande est signalée en anomalie si :
- elle est introuvable chez Shopopop (statut_livraison retourne None) ;
- elle est toujours au statut "schedule" (donc toujours "Programmées").

Un email récapitulatif des anomalies est envoyé s'il y en a au moins une.
"""
import base64
import sys
from datetime import datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import controle_stocks as cs
import livraison_drive as ld
import shopopop

_TZ = ZoneInfo("Europe/Paris")

_STATUT_PROGRAMMEE = "schedule"


def _charger_config(drive_svc):
    """Retourne (spreadsheet_id, email_destinataire, email_destinataire_2,
    shopopop_email, shopopop_mdp, shopopop_drive_id) depuis config.json."""
    cfg = ld._charger_config_dict(drive_svc)
    spreadsheet_id = cfg.get("livraison_spreadsheet_id", "").strip() or ld.LIVRAISON_SPREADSHEET_ID_DEFAUT
    email = cfg.get("email_destinataire", "").strip()
    if not email:
        print("ERREUR : email_destinataire absent de config.json.")
        sys.exit(1)
    email_2 = cfg.get("email_destinataire_2", "").strip()
    shopopop_email = cfg.get("ID_Shopopop", "").strip()
    shopopop_mdp = cfg.get("MDP_Shopopop", "").strip()
    shopopop_drive_id = cfg.get("shopopop_drive_id", "").strip() or shopopop.SHOPOPOP_DRIVE_ID_DEFAUT
    return spreadsheet_id, email, email_2, shopopop_email, shopopop_mdp, shopopop_drive_id


def _envoyer_email_anomalies(gmail_svc, destinataire, destinataire_2, aujourdhui, anomalies):
    if not gmail_svc:
        print("  Gmail inaccessible — email non envoyé.")
        return
    corps = (
        f"Bonjour,\n\n\n"
        f"{len(anomalies)} commande(s) en LIVRAISON du {aujourdhui.strftime('%d/%m/%Y')} "
        f"ne sont pas confirmées livrées côté Shopopop :\n\n"
    )
    for nom_complet, raison in anomalies:
        corps += f"  - {nom_complet} : {raison}\n"
    corps += "\n\nA vérifier.\n\nCordialement,\n\nErwan"

    msg = MIMEText(corps, 'plain', 'utf-8')
    msg['To'] = destinataire
    if destinataire_2:
        msg['Cc'] = destinataire_2
    msg['Subject'] = f"Vérif LAD {aujourdhui.strftime('%d/%m/%Y')} — {len(anomalies)} anomalie(s)"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        gmail_svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email envoyé -> {destinataire} (cc: {destinataire_2})")
    except Exception as e:
        print(f"  Email échoué : {e}")


def main():
    if not cs.DRIVE_CONFIG_FOLDER_ID:
        print("ERREUR : secret DRIVE_CONFIG_FOLDER_ID manquant.")
        sys.exit(1)

    drive_svc = cs._get_drive_service()
    if not drive_svc:
        print("ERREUR : Drive inaccessible.")
        sys.exit(1)
    sheets_svc = ld._get_sheets_service()
    if not sheets_svc:
        print("ERREUR : Sheets inaccessible.")
        sys.exit(1)

    (spreadsheet_id, email_destinataire, email_destinataire_2,
     shopopop_email, shopopop_mdp, shopopop_drive_id) = _charger_config(drive_svc)

    if not shopopop_email or not shopopop_mdp:
        print("ERREUR : ID_Shopopop/MDP_Shopopop absents de config.json.")
        sys.exit(1)
    shopopop_token = shopopop.login(shopopop_email, shopopop_mdp)
    if not shopopop_token:
        print("ERREUR : connexion Shopopop impossible.")
        sys.exit(1)

    aujourdhui = datetime.now(_TZ).date()
    print(f"Vérification livraison Shopopop du {aujourdhui.strftime('%d/%m/%Y')} …")

    commandes = ld.lire_commandes_jour(sheets_svc, spreadsheet_id, aujourdhui)
    print(f"{len(commandes)} commande(s) LIVRAISON du jour dans LIVRAISON DRIVE 2026.")
    if not commandes:
        return

    anomalies = []
    for nom_complet, km in commandes:
        statut = shopopop.statut_livraison(shopopop_token, shopopop_drive_id, aujourdhui, nom_complet)
        if statut is None:
            print(f"  {nom_complet} : INTROUVABLE chez Shopopop")
            anomalies.append((nom_complet, "introuvable chez Shopopop"))
        elif statut == _STATUT_PROGRAMMEE:
            print(f"  {nom_complet} : toujours 'Programmée' (pas livrée)")
            anomalies.append((nom_complet, "toujours 'Programmée' (pas livrée)"))
        else:
            print(f"  {nom_complet} : OK (livrée, statut={statut})")

    print(f"\n{len(anomalies)} anomalie(s) sur {len(commandes)} commande(s).")

    if anomalies:
        gmail_svc = cs._get_gmail_service()
        _envoyer_email_anomalies(gmail_svc, email_destinataire, email_destinataire_2, aujourdhui, anomalies)


if __name__ == "__main__":
    main()
