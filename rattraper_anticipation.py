#!/usr/bin/env python3
"""
Script de rattrapage a usage unique (execute une fois via le workflow
"Anticipation - Rattrapage", puis peut etre relance manuellement en cas de
besoin similaire) : reconstruit bon_anticipation_JJ_MM.txt et le PDF
brouillon anticipation_JJ_MM.pdf pour chaque jour a venir (aujourd'hui ou
plus tard) du dossier Drive GITHUB/Anticipation/ ayant au moins un
bon_anticipation_NUMERO.txt deja present — notamment les commandes tombees
avant la mise en place de l'assemblage au fil de l'eau
(assembler_anticipation.py), jamais integrees depuis.

Pour chaque jour concerne, reconstruit l'assemblage a partir de TOUS les
bon_anticipation_NUMERO.txt actuellement presents dans son dossier (les
fichiers individuels ne sont jamais supprimes, cf. archiver_anticipation_drive)
et ecrase bon_anticipation_JJ_MM.txt + anticipation_JJ_MM.pdf en consequence
— operation idempotente, sans risque a relancer.
"""

import os
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

import auto_prepa as ap
import anticipation_commandes as ac

_TZ = ZoneInfo("Europe/Paris")

_RE_JOUR = re.compile(r'^(\d{2})_(\d{2})$')
_RE_MOIS = re.compile(r'^(\d{2})_(\d{4})$')
_RE_BON_ANTICIPATION_CDE = re.compile(r'^bon_anticipation_(\d+)\.txt$')


def _sous_dossier(drive_svc, parent_id, nom):
    if not parent_id:
        return None
    res = drive_svc.files().list(
        q=(f"name='{nom}' and '{parent_id}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _lister_sous_dossiers(drive_svc, parent_id):
    """Retourne [(id, name), ...] des sous-dossiers directs de parent_id."""
    res = drive_svc.files().list(
        q=(f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' "
           f"and trashed=false"),
        fields="files(id,name)",
        pageSize=1000,
    ).execute()
    return [(f["id"], f["name"]) for f in res.get("files", [])]


def _lister_bons_commande(drive_svc, jour_id):
    """Retourne [(file_id, numero), ...] des bon_anticipation_NUMERO.txt
    (fichiers individuels par commande, jamais supprimes) presents dans ce
    dossier jour — distincts de bon_anticipation_JJ_MM.txt (l'assemblage)."""
    res = drive_svc.files().list(
        q=(f"'{jour_id}' in parents and trashed=false "
           f"and name contains 'bon_anticipation_'"),
        fields="files(id,name)",
        pageSize=1000,
    ).execute()
    resultat = []
    for f in res.get("files", []):
        m = _RE_BON_ANTICIPATION_CDE.match(f["name"])
        if m:
            resultat.append((f["id"], m.group(1)))
    return resultat


def _reconstruire_jour(drive_svc, mois_name, jour_name, bons, ordre_chemin):
    """Reconstruit bon_anticipation_JJ_MM.txt + anticipation_JJ_MM.pdf pour un
    jour donne, a partir de tous les bon_anticipation_NUMERO.txt fournis."""
    blocs = []
    for file_id, numero in sorted(bons, key=lambda t: ac._cle_tri_commande(t[1])):
        contenu = ac._telecharger_texte(drive_svc, file_id)
        if not contenu.strip():
            continue
        blocs.append(f"#CDE:{numero}\n{contenu.rstrip(chr(10))}\n")
    contenu_jour = "".join(blocs)
    if not contenu_jour.strip():
        print(f"  {jour_name}/{mois_name} : aucun contenu exploitable, ignore.")
        return

    nom_jour = f"bon_anticipation_{jour_name}.txt"
    chemin_local_txt = os.path.join(ap.WORK_DIR, nom_jour)
    with open(chemin_local_txt, "w", encoding="utf-8") as f:
        f.write(contenu_jour)
    try:
        ap.deposer_fichier_jour_anticipation(drive_svc, chemin_local_txt, mois_name, jour_name)
    finally:
        os.remove(chemin_local_txt)
    print(f"  {nom_jour} reconstruit ({len(bons)} commande(s)) => Drive OK")

    produits = ac._parser_lignes_anticipation_jour(contenu_jour)
    par_lettre = {}
    for p in produits:
        par_lettre.setdefault(p["lettre"], []).append(p)
    produits_pdf = {lettre: v for lettre, v in par_lettre.items() if lettre in ac.RAYONS_LETTRE}

    commandes_anticipees = sorted(
        {p["commande"] for produits_l in produits_pdf.values() for p in produits_l},
        key=ac._cle_tri_commande)
    ac._maj_fichier_commandes_anticipees(drive_svc, commandes_anticipees, mois_name, jour_name)

    if not produits_pdf:
        print(f"  {jour_name}/{mois_name} : aucun produit avec rayon defini, pas de PDF.")
        return

    jj, mm = jour_name.split('_')
    aaaa = mois_name.split('_')[1]
    date_complete = f"{jj}/{mm}/{aaaa}"
    chemin_pdf = ac._generer_pdf_rayons(produits_pdf, jour_name, date_complete, ordre_chemin)
    if chemin_pdf:
        try:
            ap.deposer_fichier_jour_anticipation(drive_svc, chemin_pdf, mois_name, jour_name)
        finally:
            if os.path.exists(chemin_pdf):
                os.remove(chemin_pdf)


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)

    aujourdhui = datetime.now(_TZ).date()

    github_id = _sous_dossier(drive_svc, "root", "GITHUB")
    anticipation_id = _sous_dossier(drive_svc, github_id, "Anticipation")
    if not anticipation_id:
        print("Dossier GITHUB/Anticipation/ introuvable sur Drive.")
        return

    ordre_chemin = ac._charger_ordre_chemin_prepa(drive_svc)

    nb_jours_traites = 0
    mois_folders = sorted(_lister_sous_dossiers(drive_svc, anticipation_id), key=lambda t: t[1])
    for mois_id, mois_name in mois_folders:
        m_mois = _RE_MOIS.match(mois_name)
        if not m_mois:
            continue  # ex. "archives", pas un dossier MM_AAAA
        mm, aaaa = m_mois.groups()

        jour_folders = sorted(_lister_sous_dossiers(drive_svc, mois_id), key=lambda t: t[1])
        for jour_id, jour_name in jour_folders:
            m_jour = _RE_JOUR.match(jour_name)
            if not m_jour:
                continue
            jj, mm_jour = m_jour.groups()
            try:
                date_dossier = date(int(aaaa), int(mm_jour), int(jj))
            except ValueError:
                continue
            if date_dossier < aujourdhui:
                continue  # jour deja passe, hors perimetre du rattrapage

            bons = _lister_bons_commande(drive_svc, jour_id)
            if not bons:
                continue

            print(f"\n{jour_name}/{mois_name} ({date_dossier.strftime('%d/%m/%Y')}) : "
                  f"{len(bons)} bon(s) individuel(s) trouve(s), reconstruction ...")
            _reconstruire_jour(drive_svc, mois_name, jour_name, bons, ordre_chemin)
            nb_jours_traites += 1

    if nb_jours_traites == 0:
        print("\nAucun jour a venir avec un bon d'anticipation individuel a rattraper.")
    else:
        print(f"\n{nb_jours_traites} jour(s) reconstruit(s).")


if __name__ == "__main__":
    main()
