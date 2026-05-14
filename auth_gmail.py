#!/usr/bin/env python3
"""
auth_gmail.py — Génère le token OAuth pour le compte Gmail secondaire.

À lancer UNE SEULE FOIS en local, en étant connecté au compte Gmail
qui contient les mails BDC_Traite. Ouvre un navigateur pour l'autorisation.

Prérequis : ~/.auto_prepa_credentials.json (credentials OAuth Google Cloud)

Usage :
  python3 auth_gmail.py
"""

import os
import sys

CREDENTIALS_FILE  = os.path.expanduser("~/.auto_prepa_credentials.json")
GMAIL2_TOKEN_FILE = os.path.expanduser("~/.auto_prepa_gmail2_token.json")
GMAIL_SCOPES      = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"ERREUR : {CREDENTIALS_FILE} absent.")
        print("  Téléchargez les credentials OAuth depuis Google Cloud Console.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERREUR : google-auth-oauthlib manquant.")
        print("  pip install google-auth-oauthlib")
        sys.exit(1)

    print("Ouverture du navigateur pour autoriser l'accès Gmail …")
    print("  Connectez-vous avec le compte Gmail qui contient les BDC_Traite.")
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)

    with open(GMAIL2_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"\nToken sauvegardé : {GMAIL2_TOKEN_FILE}")
    print("\nProchaine étape — ajouter le secret GitHub :")
    print(f"  gh secret set GMAIL2_TOKEN_JSON --body \"$(cat {GMAIL2_TOKEN_FILE})\" --repo <votre-repo>")


if __name__ == "__main__":
    main()
