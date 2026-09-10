#!/usr/bin/env python3
"""
Retire, a chaque commande annulee (remplacee ou non) ayant pu faire partie de
l'anticipation du jour, sa contribution du brouillon d'anticipation en cours
(bon_anticipation_JJ_MM.txt sur Drive GITHUB/Anticipation/MM_AAAA/JJ_MM/) et
regenere le PDF brouillon anticipation_JJ_MM.pdf en consequence — pour qu'une
commande annulee ne soit plus jamais preparee ni visible dans l'anticipation,
meme quand l'assemblage a eu lieu avant l'annulation.

Le retrait proprement dit est fait par ac.appliquer_annulations_jour, partage
avec assembler_anticipation.py et anticipation_commandes.py : les trois
etapes de la chaine appliquent les memes annulations, si bien qu'aucune ne
peut laisser passer ce qu'une autre aurait manque. Ce workflow reste le
chemin rapide (declenche des l'annulation), pas le seul.

Comme assembler_anticipation.py, ne se fie pas seulement a --numero : reprend
a chaque run TOUS les marqueurs annuler_anticipation_NUMERO.txt presents dans
le dossier du jour (deposes par auto_prepa.py via
_marquer_retrait_anticipation_drive) ainsi que le registre global des
annulations (GITHUB/Annulations/commandes_annulees.txt), pour rattraper un
dispatch perdu par le concurrency group partage avec anticipation_assemble.yml
(meme groupe : assemblage et retrait ne s'executent donc jamais en parallele
sur le meme fichier).

Les marqueurs ne sont PAS purges en fin de run : ils doivent rester tant que
le dossier du jour vit, sinon un assemblage declenche plus tard (commande
suivante, rattrapage) n'a plus aucun moyen de savoir que ces commandes sont
annulees et les reintegre. Ils sont supprimes avec le reste du dossier par
anticipation_commandes._reinitialiser_dossier_jour_anticipation, une fois le
PDF du jour envoye.

Declenche en fire-and-forget par auto_prepa.py (repository_dispatch) : cf.
auto_prepa.declencher_retrait_anticipation.
"""

import os
import sys

from googleapiclient.discovery import build

import auto_prepa as ap
import anticipation_commandes as ac


def _parser_args(argv):
    valeurs = {}
    for nom in ("--numero", "--jour", "--mois"):
        if nom in argv:
            i = argv.index(nom)
            if i + 1 < len(argv):
                valeurs[nom] = argv[i + 1]
    manquants = [nom for nom in ("--numero", "--jour", "--mois") if nom not in valeurs]
    if manquants:
        print(f"Arguments manquants : {', '.join(manquants)} "
              f"(usage : --numero N --jour JJ_MM --mois MM_AAAA)")
        sys.exit(1)
    return valeurs["--numero"], valeurs["--jour"], valeurs["--mois"]


def main():
    numero, dossier_jj_mm, dossier_mm_aaaa = _parser_args(sys.argv[1:])

    os.makedirs(ap.WORK_DIR, exist_ok=True)
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)

    folder_id = ap._dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm, creer=False)
    if not folder_id:
        print(f"Aucun dossier Drive GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}/ "
              f"— rien a retirer (cde {numero}).")
        return

    # Le marqueur de --numero peut manquer (echec de son depot cote
    # auto_prepa.py) : on le (re)depose pour que les runs suivants — retrait
    # comme assemblage — sachent eux aussi que cette commande est annulee, et
    # on le passe explicitement en numeros_sup pour ne pas dependre de sa
    # visibilite immediate cote Drive.
    ap._marquer_retrait_anticipation_drive(drive_svc, numero, dossier_mm_aaaa, dossier_jj_mm)

    annules, _, modifie = ac.appliquer_annulations_jour(
        drive_svc, folder_id, dossier_mm_aaaa, dossier_jj_mm,
        numeros_sup={numero}, regenerer_pdf=True)

    if not modifie:
        print(f"  Aucune des commande(s) annulee(s) "
              f"({', '.join(sorted(annules, key=ac._cle_tri_commande))}) "
              f"n'etait presente dans bon_anticipation_{dossier_jj_mm}.txt "
              f"— rien a regenerer.")

    ac._retirer_commandes_fichier_anticipees(drive_svc, annules, dossier_mm_aaaa, dossier_jj_mm)


if __name__ == "__main__":
    main()
