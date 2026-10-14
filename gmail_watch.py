#!/usr/bin/env python3
"""(Re)active la notification Gmail -> Pub/Sub qui déclenche aut_prep.

Gmail n'envoie de notifications que pendant 7 jours après un appel à
users.watch : ce script est relancé chaque jour (workflow « Gmail watch »,
déclenché par le worker Cloudflare gmailpush et par un schedule GitHub en
secours). Seuls les changements de la boîte de réception sont notifiés :
c'est là qu'arrivent les emails de confirmation, de modification et
d'annulation que traite auto_prepa.py.

Le topic Pub/Sub est lu dans config.json (clé « gmail_pubsub_topic », de la
forme projects/<projet>/topics/<topic>). Tant qu'elle est absente, le script
ne fait rien : aut_prep continue alors d'être déclenché par cron.
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import controle_stocks as cs
import livraison_drive as ld


def main():
    drive_svc = cs._get_drive_service()
    gmail_svc = cs._get_gmail_service()
    if not drive_svc or not gmail_svc:
        print("ERREUR : Drive ou Gmail inaccessible.")
        sys.exit(1)
    topic = str(ld._charger_config_dict(drive_svc).get("gmail_pubsub_topic", "")).strip()
    if not topic:
        print("gmail_pubsub_topic absent de config.json : notification Gmail non configurée.")
        return
    rep = gmail_svc.users().watch(userId="me", body={
        "topicName": topic,
        "labelIds": ["INBOX"],
        "labelFilterBehavior": "INCLUDE",
    }).execute()
    expire = datetime.fromtimestamp(int(rep["expiration"]) / 1000, ZoneInfo("Europe/Paris"))
    print(f"Notification Gmail active jusqu'au {expire.strftime('%d/%m/%Y %H:%M')}.")


if __name__ == "__main__":
    main()
