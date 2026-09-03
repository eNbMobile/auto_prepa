#!/usr/bin/env python3
"""
Retire, a chaque commande annulee (remplacee ou non) ayant pu faire partie de
l'anticipation du jour, sa contribution du brouillon d'anticipation en cours
(bon_anticipation_JJ_MM.txt sur Drive GITHUB/Anticipation/MM_AAAA/JJ_MM/) et
regenere le PDF brouillon anticipation_JJ_MM.pdf en consequence — pour qu'une
commande annulee ne soit plus jamais preparee ni visible dans l'anticipation,
meme quand l'assemblage a eu lieu avant l'annulation.

Comme assembler_anticipation.py, ne se fie pas seulement a --numero : reprend
a chaque run TOUS les marqueurs annuler_anticipation_NUMERO.txt presents dans
le dossier du jour (deposes par auto_prepa.py via
_marquer_retrait_anticipation_drive), pour rattraper un dispatch perdu par le
concurrency group partage avec anticipation_assemble.yml (meme groupe :
assemblage et retrait ne s'executent donc jamais en parallele sur le meme
fichier).

Declenche en fire-and-forget par auto_prepa.py (repository_dispatch) : cf.
auto_prepa.declencher_retrait_anticipation.
"""

import os
import re
import sys

from googleapiclient.discovery import build

import auto_prepa as ap
import anticipation_commandes as ac


_RE_MARQUEUR_RETRAIT = re.compile(r'^annuler_anticipation_(\d+)\.txt$')


def _lister_marqueurs_retrait(drive_svc, folder_id):
    res = drive_svc.files().list(
        q=(f"'{folder_id}' in parents and trashed=false "
           f"and name contains 'annuler_anticipation_'"),
        fields="files(id,name)",
        pageSize=1000,
    ).execute()
    resultat = []
    for f in res.get("files", []):
        m = _RE_MARQUEUR_RETRAIT.match(f["name"])
        if m:
            resultat.append((f["id"], m.group(1)))
    return resultat


def _retirer_blocs(contenu_jour, numeros_a_retirer):
    """Retire du contenu de bon_anticipation_JJ_MM.txt tous les blocs
    '#CDE:NUMERO' ... dont le numero est dans numeros_a_retirer. Retourne le
    contenu restant."""
    lignes_resultat = []
    ignorer = False
    for ligne in contenu_jour.splitlines():
        m = ac._RE_MARQUEUR_CDE.match(ligne.strip())
        if m:
            ignorer = m.group(1) in numeros_a_retirer
            if ignorer:
                continue
        if not ignorer:
            lignes_resultat.append(ligne)
    return "\n".join(lignes_resultat) + ("\n" if lignes_resultat else "")


def _telecharger_texte_dossier(drive_svc, folder_id, filename):
    res = drive_svc.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    if not files:
        return None, None
    return ac._telecharger_texte(drive_svc, files[0]["id"]), files[0]["id"]


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

    marqueurs = _lister_marqueurs_retrait(drive_svc, folder_id)
    numeros_a_retirer = {num for _, num in marqueurs}
    if numero not in numeros_a_retirer:
        print(f"Aucun marqueur annuler_anticipation_{numero}.txt trouve dans "
              f"{dossier_mm_aaaa}/{dossier_jj_mm}/ — rien a retirer.")
        return

    nom_jour = f"bon_anticipation_{dossier_jj_mm}.txt"
    contenu_jour, file_id_jour = _telecharger_texte_dossier(drive_svc, folder_id, nom_jour)

    modifie = False
    contenu_restant = ""
    if contenu_jour:
        contenu_restant = _retirer_blocs(contenu_jour, numeros_a_retirer)
        modifie = contenu_restant.strip() != contenu_jour.strip()

    if not modifie:
        print(f"  Aucune des commande(s) marquee(s) "
              f"({', '.join(sorted(numeros_a_retirer, key=ac._cle_tri_commande))}) "
              f"n'etait presente dans {nom_jour} — rien a regenerer.")
    else:
        if contenu_restant.strip():
            chemin_local_txt = os.path.join(ap.WORK_DIR, nom_jour)
            with open(chemin_local_txt, "w", encoding="utf-8") as f:
                f.write(contenu_restant)
            try:
                ap.deposer_fichier_jour_anticipation(drive_svc, chemin_local_txt, dossier_mm_aaaa, dossier_jj_mm)
            finally:
                os.remove(chemin_local_txt)
            print(f"  {nom_jour} mis a jour (commande(s) retiree(s) : "
                  f"{', '.join(sorted(numeros_a_retirer, key=ac._cle_tri_commande))})")
        elif file_id_jour:
            drive_svc.files().update(fileId=file_id_jour, body={"trashed": True}).execute()
            print(f"  {nom_jour} vide apres retrait — mis a la corbeille.")

        nom_pdf = f"anticipation_{dossier_jj_mm}.pdf"
        if not contenu_restant.strip():
            res = drive_svc.files().list(
                q=f"name='{nom_pdf}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            ).execute()
            for f in res.get("files", []):
                drive_svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
                print(f"  {nom_pdf} mis a la corbeille (plus aucun produit anticipe aujourd'hui).")
        else:
            produits = ac._parser_lignes_anticipation_jour(contenu_restant)
            par_lettre = {}
            for p in produits:
                par_lettre.setdefault(p["lettre"], []).append(p)
            produits_pdf = {lettre: v for lettre, v in par_lettre.items() if lettre in ac.RAYONS_LETTRE}

            if produits_pdf:
                jj, mm = dossier_jj_mm.split("_")
                aaaa = dossier_mm_aaaa.split("_")[1]
                date_complete = f"{jj}/{mm}/{aaaa}"
                ordre_chemin = ac._charger_ordre_chemin_prepa(drive_svc)
                chemin_pdf = ac._generer_pdf_rayons(produits_pdf, dossier_jj_mm, date_complete, ordre_chemin)
                if chemin_pdf:
                    try:
                        ap.deposer_fichier_jour_anticipation(drive_svc, chemin_pdf, dossier_mm_aaaa, dossier_jj_mm)
                    finally:
                        if os.path.exists(chemin_pdf):
                            os.remove(chemin_pdf)

    ac._retirer_commandes_fichier_anticipees(drive_svc, numeros_a_retirer, dossier_mm_aaaa, dossier_jj_mm)

    for file_id, _ in marqueurs:
        drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
    print(f"  {len(marqueurs)} marqueur(s) de retrait traite(s) et purge(s).")


if __name__ == "__main__":
    main()
