#!/usr/bin/env python3
"""
Script de rattrapage a usage unique : la commande 54522243 (pizza chorizo,
livraison du 04/09/2026 18:30) a ete anticipee (bon_anticipation_54522243.txt
genere et depose sur Drive par auto_prepa.py) mais n'a jamais ete integree au
PDF d'anticipation du 04/09 envoye par email — son dispatch d'assemblage a du
etre perdu par le concurrency group GitHub Actions partage entre
anticipation_assemble.yml et anticipation_retirer.yml (meme cause que
l'incident deja documente sur la commande 54216286 du 28/08/2026, cf.
assembler_anticipation.py). Consequence : bon_anticipation_54522243.txt est
reste seul sur Drive, jamais integre, puis silencieusement mis a la corbeille
par _reinitialiser_dossier_jour_anticipation une fois le mail du jour envoye
- sans aucune alerte avant le correctif apporte a anticipation_commandes.py
(cf. _envoyer_email_commandes_orphelines).

Ce script, a executer une seule fois :
- retrouve bon_anticipation_54522243.txt (mis a la corbeille, jamais supprime
  definitivement) dans GITHUB/Anticipation/09_2026/04_09/ et le restaure, pour
  garder une trace correcte de ce qui avait ete anticipe ce jour-la ;
- envoie l'alerte email qui aurait du partir le 04/09 (la fenetre de
  preparation - avant 7h30 - est deja passee, la pizza n'a pas pu etre
  anticipee ; ce mail permet au moins de le signaler pour suite a donner
  cote client).

Idempotent : si le fichier est deja restaure ou introuvable, se contente de
signaler la situation sans erreur.
"""
import os

from googleapiclient.discovery import build

import auto_prepa as ap
import anticipation_commandes as ac

NUMERO = "54522243"
DOSSIER_MM_AAAA = "09_2026"
DOSSIER_JJ_MM = "04_09"


def _retrouver_bon(drive_svc, folder_id, numero):
    """Cherche bon_anticipation_NUMERO.txt dans folder_id, corbeille incluse.
    Retourne (file_id, trashed) ou None si absent."""
    nom = f"bon_anticipation_{numero}.txt"
    res = drive_svc.files().list(
        q=f"name='{nom}' and '{folder_id}' in parents",
        fields="files(id,trashed)",
    ).execute()
    fichiers = res.get("files", [])
    if not fichiers:
        return None
    return fichiers[0]["id"], fichiers[0].get("trashed", False)


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)

    ap._charger_config(drive_svc)

    folder_id = ap._dossier_anticipation_jour(drive_svc, DOSSIER_MM_AAAA, DOSSIER_JJ_MM, creer=False)
    if not folder_id:
        print(f"Dossier Drive GITHUB/Anticipation/{DOSSIER_MM_AAAA}/{DOSSIER_JJ_MM}/ introuvable.")
        return

    bon = _retrouver_bon(drive_svc, folder_id, NUMERO)
    if bon is None:
        print(f"bon_anticipation_{NUMERO}.txt introuvable (meme dans la corbeille) "
              f"dans {DOSSIER_MM_AAAA}/{DOSSIER_JJ_MM}/ — rien a restaurer.")
    else:
        file_id, trashed = bon
        if trashed:
            drive_svc.files().update(fileId=file_id, body={"trashed": False}).execute()
            print(f"bon_anticipation_{NUMERO}.txt restaure depuis la corbeille "
                  f"(preuve de l'anticipation generee mais jamais integree).")
        else:
            print(f"bon_anticipation_{NUMERO}.txt deja present (non supprime) sur Drive.")
        contenu = ac._telecharger_texte(drive_svc, file_id)
        print(f"Contenu :\n{contenu}")

    ac._envoyer_email_commandes_orphelines(gmail_svc, DOSSIER_JJ_MM, [NUMERO])


if __name__ == "__main__":
    main()
