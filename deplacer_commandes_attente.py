#!/usr/bin/env python3
"""
Deplace effectivement, chaque soir a 22h, les BonDeCommande dont le
deplacement a ete demande dans la journee via le workflow "Deplacer
commandes" (sans --forcer) : cette demande n'a fait, sur le moment,
qu'inscrire un marqueur Drive GITHUB/DeplacementsEnAttente/deplacer_NUMERO.txt
(date cible deja resolue), depose par deplacer_commande.mettre_en_attente.
Traite aussi les demandes de suppression sans forcage (marqueur contenant
SUPPRIMER, depose par deplacer_commande.mettre_en_attente_suppression) : les
exemplaires archives de la commande sont alors mis a la corbeille Drive.

Pourquoi differe : les ventes du jour (generer_ventes, controle_stocks,
cumul_ventes_semaine, renseigne_ca) tournent dans la journee a partir des
BonDeCommande presents dans BDC/MM_AAAA/JJ_MM ; un deplacement immediat d'une
commande du jour vers le lendemain la faisait disparaitre du CA quotidien
alors qu'elle avait bien ete preparee. En attendant le soir, une fois ces
calculs du jour deja faits, le deplacement ne les fausse plus.

Chaque marqueur traite avec succes est supprime (mis a la corbeille) ; un
echec le laisse en place pour une nouvelle tentative le soir suivant.

Usage : deplacer_commandes_attente.py
"""

import os
import sys

from googleapiclient.discovery import build

import auto_prepa as ap
import deplacer_commande as dc


def _resume(lignes):
    """Recapitulatif visible sur la page du run GitHub Actions."""
    chemin = os.environ.get("GITHUB_STEP_SUMMARY")
    if not chemin:
        return
    try:
        with open(chemin, "a", encoding="utf-8") as f:
            f.write("## Deplacer commandes en attente (22h)\n\n")
            if not lignes:
                f.write("- Aucune commande en attente de deplacement.\n")
            for ok, message in lignes:
                f.write(f"- {'✅' if ok else '❌'} {message}\n")
    except OSError:
        pass


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    ap._charger_config(drive_svc)

    marqueurs = dc.lister_marqueurs_attente(drive_svc)
    if not marqueurs:
        print("Aucune commande en attente de deplacement.")
        _resume([])
        return

    print(f"\n{len(marqueurs)} commande(s) en attente de deplacement :")
    resultats = []
    echecs = False
    for file_id, numero, cible in marqueurs:
        ok, message = dc.traiter_marqueur(drive_svc, numero, cible)
        print(f"  {'OK ' if ok else 'ERREUR'} {message}")
        resultats.append((ok, message))
        if ok:
            try:
                drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
            except Exception as e:
                print(f"    Marqueur non supprime ({e}) — sera retraite demain soir.")
        else:
            echecs = True

    _resume(resultats)
    print("\nSi les ventes / le CA d'un des jours concernes ont deja ete calcules, "
          "relancer les workflows correspondants (generer_ventes, renseigne_ca, "
          "controle_stocks) pour ces jours.")
    if echecs:
        sys.exit(1)


if __name__ == "__main__":
    main()
