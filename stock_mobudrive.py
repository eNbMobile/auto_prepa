#!/usr/bin/env python3
"""
Stock consultable depuis l'application MobUDrive.

Dépose dans le dossier Drive des bons (MobUDrive_Bons, clé
« drive_bons_folder_id » de config.json) un CSV léger du stock :

  stock_JJ_MM_AAAA_matin.csv : export du matin (j.xlsx), déposé à chaque
                               contrôle de stocks ;
  stock_JJ_MM_AAAA_soir.csv  : stock du matin du jour moins les ventes du
                               jour (≈ stock du lendemain matin), déposé par
                               la routine du soir (Générer Ventes).

Un seul fichier est gardé dans le dossier : le plus récent (date, puis soir
après matin). L'application lit donc simplement le fichier stock_*.csv
présent : celui du matin s'il est déjà déposé, sinon celui de la veille au
soir.

Format : UTF-8 sans BOM, séparateur « ; », fins de ligne LF, en-tête
« gencod;stock;libelle ».
"""
import csv
import os
import re
from datetime import date

import controle_stocks as cs

_RE_NOM = re.compile(r"^stock_(\d{2})_(\d{2})_(\d{4})_(matin|soir)\.csv$")
_ORDRE_MOMENT = {"matin": 0, "soir": 1}


def nom_fichier(jour, moment):
    return f"stock_{jour.strftime('%d_%m_%Y')}_{moment}.csv"


def _cle(nom):
    """(date, rang du moment) d'un nom stock_JJ_MM_AAAA_{matin,soir}.csv, ou None."""
    m = _RE_NOM.match(nom)
    if not m:
        return None
    try:
        return (date(int(m.group(3)), int(m.group(2)), int(m.group(1))),
                _ORDRE_MOMENT[m.group(4)])
    except ValueError:
        return None


def stock_soir(stock_matin, ventes):
    """Stock du matin diminué des ventes du jour (gencods du stock uniquement)."""
    return {g: round(s - ventes.get(g, 0), 3) for g, s in stock_matin.items()}


def ecrire_csv(stock, libelles, chemin):
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["gencod", "stock", "libelle"])
        for g in sorted(stock):
            s = stock[g]
            w.writerow([g, int(s) if float(s).is_integer() else s, libelles.get(g, "")])
    return chemin


def publier(stock, libelles, jour, moment):
    """Écrit le CSV et le dépose dans le dossier des bons, puis retire les
    stock_*.csv plus anciens. Ne remplace pas un fichier plus récent déjà
    présent (ex. relance de la routine du soir d'un jour passé).
    Retourne True si le fichier a été déposé."""
    from googleapiclient.http import MediaFileUpload

    dossier = cs.DRIVE_BONS_FOLDER_ID
    if not dossier:
        print("  Stock MobUDrive : clé « drive_bons_folder_id » absente de config.json.")
        return False
    svc = cs._get_drive_service()
    if not svc:
        print("  Stock MobUDrive : Drive inaccessible.")
        return False

    nom_csv = nom_fichier(jour, moment)
    cle = _cle(nom_csv)
    res = svc.files().list(
        q=f"name contains 'stock_' and '{dossier}' in parents and trashed=false",
        fields="files(id,name)", pageSize=100,
    ).execute()
    existants = [(f, _cle(f["name"])) for f in res.get("files", [])]
    existants = [(f, k) for f, k in existants if k is not None]
    if any(k > cle for _, k in existants):
        print(f"  Stock MobUDrive : un stock plus récent que {nom_csv} est déjà déposé — inchangé.")
        return False

    os.makedirs(cs.WORK_DIR, exist_ok=True)
    chemin = ecrire_csv(stock, libelles, os.path.join(cs.WORK_DIR, nom_csv))
    media = MediaFileUpload(chemin, mimetype="text/csv", resumable=False)
    meme = [f for f, k in existants if k == cle]
    if meme:
        svc.files().update(fileId=meme[0]["id"], media_body=media).execute()
    else:
        svc.files().create(body={"name": nom_csv, "parents": [dossier]},
                           media_body=media, fields="id").execute()
    print(f"  {nom_csv} → Drive MobUDrive_Bons OK ({len(stock)} gencods)")

    for f, k in existants:
        if k < cle:
            try:
                svc.files().delete(fileId=f["id"]).execute()
                print(f"  {f['name']} retiré de MobUDrive_Bons.")
            except Exception as e:
                print(f"  Retrait de {f['name']} échoué : {type(e).__name__}")
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
    stock, libelles, _ = cs.lire_stock(chemin, classeur_requis=False)
    libelles.update(cs.charger_libelles_dict() or {})
    return publier(stock_soir(stock, ventes), libelles, jour, "soir")
