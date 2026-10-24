#!/usr/bin/env python3
"""
Annule a la main une commande dont le mail d'annulation n'est jamais arrive
(ou a ete perdu) : applique exactement le traitement fait a la reception de
ce mail (auto_prepa.annuler_commande) — retrait de l'anticipation, de
LIVRAISON DRIVE, des bons de l'app, des archives et de l'avoir.

Usage : python3 annuler_commande.py --numero N
Declenche par le workflow manuel annuler_commande.yml.
"""

import os
import sys

from googleapiclient.discovery import build

import auto_prepa as ap


def _parser_numero(argv):
    if "--numero" in argv:
        i = argv.index("--numero")
        if i + 1 < len(argv) and argv[i + 1].strip().isdigit():
            return argv[i + 1].strip()
    print("Numero de commande manquant ou invalide (usage : --numero N)")
    sys.exit(1)


def main():
    numero = _parser_numero(sys.argv[1:])

    os.makedirs(ap.WORK_DIR, exist_ok=True)
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)
    sheets_svc = build("sheets", "v4", credentials=creds)
    ap._charger_config(drive_svc)

    print(f"  Annulation manuelle : cde {numero} supprimee")
    ap.annuler_commande(drive_svc, gmail_svc, sheets_svc, numero)


if __name__ == "__main__":
    main()
