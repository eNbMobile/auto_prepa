#!/usr/bin/env python3
"""
Stocks insuffisants prévisionnels : stock J1 (export du dossier Drive du
contrôle de stocks, j1.xlsx par défaut) moins les ventes d'un ou plusieurs
jours (BDC du Drive, mêmes règles que generer_ventes : commandes annulées
écartées, gencods R1 uniquement).

Un produit est en stock insuffisant si le stock restant est <=
SEUIL_STOCK_BAS, comme dans le contrôle de stocks : les produits du
classeur « PRODUIT A ENLEVER » sont exclus, ceux du classeur « DÉLOTAGE »
aussi (traités par le délotage). Le PDF (même format que le PDF « Stocks
insuffisant Drive » du contrôle, trié selon le chemin de préparation) est
déposé dans le dossier Drive du contrôle de stocks, à côté du J1. Aucun mail.

Usage :
  python3 calculer_stocks_insuffisants.py --dates "16/11/2026 17/11/2026" [--j1 j1.xlsx]
"""
import os
import re
import sys
from datetime import date, datetime

import controle_stocks as cs


def parser_dates(texte):
    """« 16/11/2026 17/11/2026 » (séparateurs espace, virgule ou point-virgule)
    → liste de dates triées, sans doublon. ValueError si vide ou invalide."""
    morceaux = [m for m in re.split(r'[\s,;]+', texte or '') if m]
    if not morceaux:
        raise ValueError("aucune date de ventes")
    jours = set()
    for m in morceaux:
        try:
            jours.add(datetime.strptime(m, "%d/%m/%Y").date())
        except ValueError:
            raise ValueError(f"date invalide : {m} (attendu JJ/MM/AAAA)")
    return sorted(jours)


def calculer_stock_insuffisant(stock_j1, classeurs, ventes_jours, gencods_r1, libelles):
    """Lignes (format _construire_pdf_tableau : gencod, s_j1, ventes, 0,
    restant, 0, '', libellé) des gencods R1 présents au J1 dont le stock
    restant après les ventes est <= SEUIL_STOCK_BAS."""
    enlever  = cs._normaliser_classeur(cs.CLASSEUR_A_ENLEVER)
    delotage = cs._normaliser_classeur(cs.CLASSEUR_DELOTAGE)
    rows = []
    for g in sorted(stock_j1):
        if gencods_r1 is not None and g not in gencods_r1:
            continue
        classeur = cs._normaliser_classeur(classeurs.get(g, ''))
        if classeur in (enlever, delotage):
            continue
        vendu = sum(v.get(g, 0) for v in ventes_jours)
        restant = stock_j1[g] - vendu
        if restant <= cs.SEUIL_STOCK_BAS:
            rows.append((g, stock_j1[g], vendu, 0, restant, 0, '', libelles.get(g, '')))
    return rows


def deposer_dans_dossier_controle(chemin):
    """Dépose (ou remplace) le PDF dans le dossier Drive du contrôle de stocks."""
    from googleapiclient.http import MediaFileUpload
    svc = cs._get_drive_service()
    if not svc or not cs.DRIVE_CONTROLE_FOLDER_ID:
        return False
    nom_fichier = os.path.basename(chemin)
    existants = svc.files().list(
        q=f"name='{nom_fichier}' and '{cs.DRIVE_CONTROLE_FOLDER_ID}' in parents and trashed=false",
        fields="files(id)",
    ).execute().get("files", [])
    media = MediaFileUpload(chemin, mimetype="application/pdf", resumable=False)
    if existants:
        svc.files().update(fileId=existants[0]["id"], media_body=media).execute()
    else:
        svc.files().create(body={"name": nom_fichier, "parents": [cs.DRIVE_CONTROLE_FOLDER_ID]},
                           media_body=media, fields="id").execute()
    print(f"  {nom_fichier} déposé dans le dossier Drive du contrôle de stocks.")
    return True


def _option(args, nom, defaut=None):
    if nom in args:
        i = args.index(nom)
        if i + 1 < len(args):
            return args[i + 1]
    return defaut


def main():
    args = sys.argv[1:]
    try:
        jours = parser_dates(_option(args, "--dates", ""))
    except ValueError as e:
        print(f"ERREUR : {e}")
        sys.exit(1)
    nom_j1 = (_option(args, "--j1") or "j1.xlsx").strip()

    cs._charger_config()
    os.makedirs(cs.WORK_DIR, exist_ok=True)

    print(f"Téléchargement {nom_j1} (dossier contrôle) …")
    f_j1 = cs.telecharger_fichier_controle(nom_j1, dest=os.path.join(cs.WORK_DIR, "j1_stock.xlsx"))
    if not f_j1:
        print(f"ERREUR : {nom_j1} introuvable dans le dossier du contrôle de stocks.")
        sys.exit(1)
    stock_j1, libelles, classeurs = cs.lire_stock(f_j1, classeur_requis=False)
    print(f"  → {len(stock_j1)} gencods")

    ventes_jours = []
    for d in jours:
        print(f"\nVentes du {d.strftime('%d/%m/%Y')} …")
        v, l = cs.generer_ventes(d)
        ventes_jours.append(v)
        for g, lib in l.items():
            libelles.setdefault(g, lib)
    libelles.update(cs.charger_libelles_dict())

    rows = calculer_stock_insuffisant(stock_j1, classeurs, ventes_jours,
                                      cs.charger_gencods_r1(), libelles)
    print(f"\n{len(rows)} produit(s) en stock insuffisant (restant <= {cs.SEUIL_STOCK_BAS}).")
    if not rows:
        print("Aucun stock insuffisant : pas de PDF.")
        return

    rows.sort(key=cs.cle_tri_chemin_prepa(cs.charger_adresses_magasin(),
                                          cs.charger_gencod_nomenclatures(),
                                          cs.charger_ordre_chemin_prepa()))
    vms_map = cs.calculer_vms([r[0] for r in rows], date.today())

    dates_txt = " & ".join(d.strftime('%d/%m/%Y') for d in jours)
    nom_pdf = os.path.join(cs.WORK_DIR, "stock_insuffisant_"
                           + "_".join(d.strftime('%Y%m%d') for d in jours) + ".pdf")
    titre = (f"<b>Stocks insuffisant Drive - {nom_j1} - ventes du {dates_txt}</b>"
             f"&nbsp;&nbsp;({len(rows)} produit{'s' if len(rows) > 1 else ''})")
    pdf = cs._construire_pdf_tableau(rows, titre, nom_pdf, complet=False, vms_map=vms_map)
    if not pdf or not deposer_dans_dossier_controle(pdf):
        print("ERREUR : PDF non généré ou non déposé sur Drive.")
        sys.exit(1)


if __name__ == "__main__":
    main()
