#!/usr/bin/env python3
"""
Assemble, a chaque commande anticipable traitee par auto_prepa.py, le
bon_anticipation_NUMERO.txt de cette commande dans le fichier du jour
bon_anticipation_JJ_MM.txt (Drive GITHUB/Anticipation/MM_AAAA/JJ_MM/), met a
jour commandes_anticipées_JJ_MM.txt (utilise par auto_prepa.py pour alerter
si une commande annulee faisait partie de l'anticipation), puis regenere le
PDF brouillon anticipation_JJ_MM.pdf correspondant (memes dossier/fichier,
ecrases a chaque appel).

Declenche en fire-and-forget par auto_prepa.py (repository_dispatch) : cet
assemblage (telechargement/reupload Drive, generation PDF avec photos et
codes-barres) tourne dans ce workflow separe pour ne jamais retarder le cron
toutes les minutes d'aut_prep. Le WF Anticipation, lui, ne fait plus aucun
calcul : il recupere directement ce brouillon deja a jour, l'archive et
l'envoie par mail (cf. anticipation_commandes.py).
"""

import os
import sys

from googleapiclient.discovery import build

import auto_prepa as ap
import anticipation_commandes as ac


def _telecharger_texte_dossier(drive_svc, folder_id, filename):
    res = drive_svc.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    if not files:
        return None
    return ac._telecharger_texte(drive_svc, files[0]["id"])


def _commandes_deja_assemblees(contenu_jour):
    """Numeros de commande deja marques '#CDE:NUMERO' dans bon_anticipation_JJ_MM.txt."""
    marqueurs = set()
    for ligne in contenu_jour.splitlines():
        m = ac._RE_MARQUEUR_CDE.match(ligne.strip())
        if m:
            marqueurs.add(m.group(1))
    return marqueurs


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

    folder_id = ap._dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm)
    if not folder_id:
        print("ERREUR : dossier Drive GITHUB/Anticipation introuvable/impossible a creer.")
        sys.exit(1)

    nom_jour = f"bon_anticipation_{dossier_jj_mm}.txt"

    contenu_jour = _telecharger_texte_dossier(drive_svc, folder_id, nom_jour) or ""
    deja_assemblees = _commandes_deja_assemblees(contenu_jour)

    # Ne se fie pas uniquement a --numero : le concurrency group GitHub
    # Actions de ce workflow (anticipation_assemble, cancel-in-progress:
    # false) ne conserve qu'un seul run "pending" a la fois. Quand plusieurs
    # commandes sont dispatchees en rafale (meme minute de cron aut_prep),
    # un run peut se faire silencieusement annuler/remplacer par le suivant
    # dans la queue sans jamais s'executer, faisant disparaitre l'integration
    # de sa commande sans aucune erreur visible (cf. commande 54216286 du
    # 28/08/2026, dont le run assembleur avait ete ainsi annule). On reprend
    # donc ici, a chaque run, TOUTES les commandes dont le
    # bon_anticipation_NUMERO.txt est present sur Drive mais pas encore
    # integre dans bon_anticipation_JJ_MM.txt — pas seulement celle qui a
    # declenche ce run — pour que le run suivant (n'importe quelle commande)
    # rattrape automatiquement celles perdues en route.
    bons_dossier = {num: file_id for file_id, num in ac._lister_bons_commande(drive_svc, folder_id)}
    if numero not in bons_dossier and numero not in deja_assemblees:
        print(f"ERREUR : bon_anticipation_{numero}.txt introuvable dans Drive "
              f"GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}/.")
        sys.exit(1)

    a_integrer = sorted(
        (num for num in bons_dossier if num not in deja_assemblees),
        key=ac._cle_tri_commande)
    if not a_integrer:
        print(f"Commande {numero} deja assemblee dans {nom_jour}, rien a faire.")
        return

    if contenu_jour and not contenu_jour.endswith("\n"):
        contenu_jour += "\n"
    for num in a_integrer:
        contenu_cde = ac._telecharger_texte(drive_svc, bons_dossier[num])
        if not contenu_cde.strip():
            continue
        contenu_jour += f"#CDE:{num}\n{contenu_cde.rstrip(chr(10))}\n"

    chemin_local_txt = os.path.join(ap.WORK_DIR, nom_jour)
    with open(chemin_local_txt, "w", encoding="utf-8") as f:
        f.write(contenu_jour)
    try:
        ap.deposer_fichier_jour_anticipation(drive_svc, chemin_local_txt, dossier_mm_aaaa, dossier_jj_mm)
    finally:
        os.remove(chemin_local_txt)
    print(f"  {nom_jour} mis a jour ({len(a_integrer)} commande(s) integree(s) : {', '.join(a_integrer)})")

    produits = ac._parser_lignes_anticipation_jour(contenu_jour)
    par_lettre = {}
    for p in produits:
        par_lettre.setdefault(p["lettre"], []).append(p)
    produits_pdf = {lettre: v for lettre, v in par_lettre.items() if lettre in ac.RAYONS_LETTRE}

    commandes_anticipees = sorted(
        {p["commande"] for produits_l in produits_pdf.values() for p in produits_l},
        key=ac._cle_tri_commande)
    ac._maj_fichier_commandes_anticipees(drive_svc, commandes_anticipees, dossier_mm_aaaa, dossier_jj_mm)

    if not produits_pdf:
        print("  Aucun produit avec rayon defini, pas de PDF brouillon a generer.")
        return

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


if __name__ == "__main__":
    main()
