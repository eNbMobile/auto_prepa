#!/usr/bin/env python3
"""
Stock consultable depuis l'application MobUDrive.

Dépose dans le dossier Drive des bons (MobUDrive_Bons, clé
« drive_bons_folder_id » de config.json) le fichier stock.xlsx, toujours
sous ce nom (le précédent est mis à la corbeille Drive, donc restaurable) :

  - contrôle de stocks : export du matin (j.xlsx) ;
  - routine du soir (Générer Ventes) : stock du matin du jour dont la
    colonne « Stock UC » est diminuée des ventes du jour (≈ stock du
    lendemain matin), même format que l'export.

Seuls les gencods rangés dans un classeur autre que DÉLOTAGE, LGV,
PRODUIT À ENLEVER et STOCK MAGASIN sont conservés (lignes sans classeur
retirées).
"""
import os
import re

import controle_stocks as cs

NOM_FICHIER = "stock.xlsx"
# Classeurs exclus (comparés normalisés : majuscules, sans accents ni *)
CLASSEURS_EXCLUS = ("DELOTAGE", "LGV", "PRODUIT A ENLEVER", "STOCK MAGASIN")
_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _gencod(valeur):
    """Gencod normalisé comme cs.lire_stock (13 chiffres), ou None."""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    texte = str(valeur if valeur is not None else "").strip()
    g = texte.lstrip('0').zfill(13) if texte.isdigit() else texte
    return g if re.match(r'^\d{5,}$', g) else None


def classeur_retenu(classeur):
    """Vrai si le classeur est renseigné et n'est pas un classeur exclu."""
    c = cs._normaliser_classeur(str(classeur or ""))
    return bool(c) and not any(x in c for x in CLASSEURS_EXCLUS)


def ecrire_stock(chemin_src, chemin_sortie, ventes=None):
    """Copie de l'export de stock limitée aux classeurs retenus, dont
    « Stock UC » est diminué des ventes si `ventes` est fourni."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin_src)
    ws = wb.worksheets[0]
    idx_g = idx_s = idx_c = None
    a_supprimer = []
    for num, row in enumerate(ws.iter_rows(), start=1):
        if idx_g is None:
            noms = [str(c.value or "").strip().lower() for c in row]
            if 'gencod' in noms:
                idx_g = noms.index('gencod')
                idx_s = next((i for i, h in enumerate(noms) if re.match(r'stock\s*uc', h)), None)
                idx_c = noms.index('classeur') if 'classeur' in noms else None
                if idx_s is None:
                    raise ValueError(f"Colonne 'Stock UC' introuvable dans {os.path.basename(chemin_src)}.")
                if idx_c is None:
                    raise ValueError(f"Colonne 'Classeur' introuvable dans {os.path.basename(chemin_src)}.")
            continue
        if not any(c.value not in (None, "") for c in row):
            continue
        classeur = row[idx_c].value if len(row) > idx_c else None
        if not classeur_retenu(classeur):
            a_supprimer.append(num)
            continue
        if not ventes or len(row) <= max(idx_g, idx_s):
            continue
        g = _gencod(row[idx_g].value)
        if not g or not ventes.get(g):
            continue
        cellule = row[idx_s]
        try:
            stock = float(str(cellule.value if cellule.value is not None else 0)
                          .replace(',', '.').replace(' ', '') or 0)
        except ValueError:
            continue
        nouveau = round(stock - ventes[g], 3)
        cellule.value = int(nouveau) if float(nouveau).is_integer() else nouveau
    if idx_g is None:
        raise ValueError(f"Colonne 'Gencod' introuvable dans {os.path.basename(chemin_src)}.")
    for num in reversed(a_supprimer):
        ws.delete_rows(num)
    wb.save(chemin_sortie)
    return chemin_sortie


def ecrire_stock_soir(chemin_matin, ventes, chemin_sortie):
    """Stock du matin (classeurs retenus) diminué des ventes du jour."""
    return ecrire_stock(chemin_matin, chemin_sortie, ventes)


def publier(chemin_local, dossier=None):
    """Dépose chemin_local sous le nom stock.xlsx dans MobUDrive_Bons, après
    avoir mis l'ancien à la corbeille. Retourne True si le dépôt a réussi.

    `dossier` : identifiant de MobUDrive_Bons. À fournir quand l'appelant est
    controle_stocks.py lancé en script : sa config est chargée dans
    __main__, pas dans le module controle_stocks importé ici."""
    from googleapiclient.http import MediaFileUpload

    dossier = dossier or cs.DRIVE_BONS_FOLDER_ID
    if not dossier:
        print("  Stock MobUDrive : clé « drive_bons_folder_id » absente de config.json.")
        return False
    # Filtré avant toute opération Drive : en cas d'erreur, l'ancien
    # stock.xlsx reste en place.
    os.makedirs(cs.WORK_DIR, exist_ok=True)
    filtre = ecrire_stock(chemin_local, os.path.join(cs.WORK_DIR, "stock_mobudrive.xlsx"))
    svc = cs._get_drive_service()
    if not svc:
        print("  Stock MobUDrive : Drive inaccessible.")
        return False
    res = svc.files().list(
        q=f"name='{NOM_FICHIER}' and '{dossier}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    existants = res.get("files", [])
    # L'ancien stock.xlsx va à la corbeille Drive (restaurable), pas écrasé.
    for f in existants:
        svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
    media = MediaFileUpload(filtre, mimetype=_MIME_XLSX, resumable=False)
    svc.files().create(body={"name": NOM_FICHIER, "parents": [dossier]},
                       media_body=media, fields="id").execute()
    print(f"  {NOM_FICHIER} → Drive MobUDrive_Bons OK")
    return True


def publier_soir(jour, ventes):
    """Routine du soir : stock du matin archivé de `jour` moins les ventes du jour."""
    nom_matin = cs.nom_archive_stock(jour, "matin")
    os.makedirs(cs.WORK_DIR, exist_ok=True)
    chemin = cs.telecharger_fichier_archive(
        "stocks", nom_matin, os.path.join(cs.WORK_DIR, nom_matin),
        root_id=cs.DRIVE_CONFIG_FOLDER_ID)
    if not chemin:
        raise FileNotFoundError(f"Archives/stocks/{nom_matin} introuvable sur Drive.")
    sortie = ecrire_stock_soir(chemin, ventes, os.path.join(cs.WORK_DIR, "stock_soir_mobudrive.xlsx"))
    return publier(sortie)
