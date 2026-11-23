#!/usr/bin/env python3
"""
Stock consultable depuis l'application MobUDrive.

Dépose dans le dossier Drive des bons (MobUDrive_Bons, clé
« drive_bons_folder_id » de config.json) le fichier stock.xlsx, toujours
sous ce nom (le précédent est écrasé) :

  - contrôle de stocks : export du matin (j.xlsx) tel quel ;
  - routine du soir (Générer Ventes) : stock du matin du jour dont la
    colonne « Stock UC » est diminuée des ventes du jour (≈ stock du
    lendemain matin), même format que l'export.
"""
import os
import re

import controle_stocks as cs

NOM_FICHIER = "stock.xlsx"
_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _gencod(valeur):
    """Gencod normalisé comme cs.lire_stock (13 chiffres), ou None."""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    texte = str(valeur if valeur is not None else "").strip()
    g = texte.lstrip('0').zfill(13) if texte.isdigit() else texte
    return g if re.match(r'^\d{5,}$', g) else None


def ecrire_stock_soir(chemin_matin, ventes, chemin_sortie):
    """Copie de l'export du matin dont « Stock UC » est diminué des ventes."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin_matin)
    ws = wb.worksheets[0]
    idx_g = idx_s = None
    for row in ws.iter_rows():
        if idx_g is None:
            noms = [str(c.value or "").strip().lower() for c in row]
            if 'gencod' in noms:
                idx_g = noms.index('gencod')
                idx_s = next((i for i, h in enumerate(noms) if re.match(r'stock\s*uc', h)), None)
                if idx_s is None:
                    raise ValueError(f"Colonne 'Stock UC' introuvable dans {os.path.basename(chemin_matin)}.")
            continue
        if len(row) <= max(idx_g, idx_s):
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
        raise ValueError(f"Colonne 'Gencod' introuvable dans {os.path.basename(chemin_matin)}.")
    wb.save(chemin_sortie)
    return chemin_sortie


def publier(chemin_local):
    """Dépose chemin_local sous le nom stock.xlsx dans MobUDrive_Bons (écrase
    le fichier existant). Retourne True si le dépôt a réussi."""
    from googleapiclient.http import MediaFileUpload

    dossier = cs.DRIVE_BONS_FOLDER_ID
    if not dossier:
        print("  Stock MobUDrive : clé « drive_bons_folder_id » absente de config.json.")
        return False
    svc = cs._get_drive_service()
    if not svc:
        print("  Stock MobUDrive : Drive inaccessible.")
        return False
    res = svc.files().list(
        q=f"name='{NOM_FICHIER}' and '{dossier}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    existants = res.get("files", [])
    media = MediaFileUpload(chemin_local, mimetype=_MIME_XLSX, resumable=False)
    if existants:
        svc.files().update(fileId=existants[0]["id"], media_body=media).execute()
    else:
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
