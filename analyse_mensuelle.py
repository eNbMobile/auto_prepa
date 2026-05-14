#!/usr/bin/env python3
"""
analyse_mensuelle.py — Analyse des ventes du mois précédent.

Produit deux fichiers CSV uploadés dans Drive Archives/analyses/ :
  produits_non_vendus_MM_AAAA.csv
      Produits adressés en R1 ayant généré < 4 ventes sur le mois.
  top_ventes_MM_AAAA.csv
      Top 200 produits ELDPH (nomenclature 01) hors R1, triés par ventes desc.

Usage :
  python3 analyse_mensuelle.py [--mois MM/AAAA]
  (défaut : mois précédent)
"""

import csv
import io
import os
import sys
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import controle_stocks
from controle_stocks import (
    WORK_DIR, TOKEN_FILE,
    _charger_config, _get_drive_service, _get_or_create_subfolder_drive,
    telecharger_config_depuis_drive, upload_to_archive,
    charger_libelles_dict,
)


# ─────────────────────────────────────────────────────────────────
# Helpers Drive
# ─────────────────────────────────────────────────────────────────

def _telecharger_contenu(svc, file_id):
    """Télécharge un fichier Drive et retourne son contenu texte."""
    from googleapiclient.http import MediaIoBaseDownload
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8-sig")


def _lister_ventes_mois(svc, folder_id, mois_2d):
    """Retourne [(file_id, name)] des ventes_DD_MM.csv du mois dans Archives/ventes/."""
    archives_id = _get_or_create_subfolder_drive(svc, folder_id, "Archives")
    if not archives_id:
        return []
    ventes_id = _get_or_create_subfolder_drive(svc, archives_id, "ventes")
    if not ventes_id:
        return []
    res = svc.files().list(
        q=f"'{ventes_id}' in parents and trashed=false",
        fields="files(id,name)",
        pageSize=100,
    ).execute()
    return [
        (f["id"], f["name"])
        for f in res.get("files", [])
        if f["name"].startswith("ventes_") and f["name"].endswith(f"_{mois_2d}.csv")
    ]


# ─────────────────────────────────────────────────────────────────
# Chargement config locale
# ─────────────────────────────────────────────────────────────────

def _charger_adresses():
    """Retourne {gencod: adresse} depuis gencod_adresses.csv (premier gencod wins)."""
    chemin = os.path.join(WORK_DIR, "gencod_adresses.csv")
    if not os.path.exists(chemin):
        print("  ATTENTION : gencod_adresses.csv absent — adresses inconnues.")
        return {}
    d = {}
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) >= 2:
                g = row[0].strip()
                if g.isdigit():
                    g = g.lstrip("0").zfill(13)
                if g not in d:
                    d[g] = row[1].strip()
    return d


def _charger_nomenclatures():
    """Retourne {gencod: code_nomenclature} depuis gencod_nomenclatures.csv."""
    chemin = os.path.join(WORK_DIR, "gencod_nomenclatures.csv")
    if not os.path.exists(chemin):
        print("  ATTENTION : gencod_nomenclatures.csv absent.")
        return {}
    d = {}
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) >= 2:
                g = row[0].strip()
                if g.isdigit():
                    g = g.lstrip("0").zfill(13)
                d[g] = row[1].strip()
    return d


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    # Auth Drive
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

    _charger_config()
    telecharger_config_depuis_drive()

    # Mois cible
    args = sys.argv[1:]
    if "--mois" in args:
        i = args.index("--mois")
        try:
            mm, aaaa = args[i + 1].split("/")
            annee, mois = int(aaaa), int(mm)
        except Exception:
            print(f"Format invalide : {args[i + 1]} (attendu MM/AAAA)")
            sys.exit(1)
    else:
        today = date.today()
        dernier_jour_mois_prec = today.replace(day=1) - timedelta(days=1)
        annee, mois = dernier_jour_mois_prec.year, dernier_jour_mois_prec.month

    mois_2d = f"{mois:02d}"
    label   = f"{mois_2d}_{annee}"
    print(f"Analyse des ventes {mois_2d}/{annee} …")

    svc = _get_drive_service()
    if not svc:
        print("ERREUR : service Drive indisponible.")
        sys.exit(1)

    folder_id = controle_stocks.DRIVE_CONTROLE_FOLDER_ID
    if not folder_id:
        print("ERREUR : DRIVE_CONTROLE_FOLDER_ID non configuré.")
        sys.exit(1)

    # 1. Agréger les ventes du mois depuis Drive
    fichiers = _lister_ventes_mois(svc, folder_id, mois_2d)
    if not fichiers:
        print(f"  Aucun fichier ventes trouvé pour {mois_2d}/{annee}.")
        sys.exit(1)
    print(f"  {len(fichiers)} fichier(s) ventes : {[n for _, n in fichiers]}")

    ventes   = {}  # gencod → qty total mois
    libelles = {}  # gencod → libelle
    for file_id, fname in sorted(fichiers, key=lambda x: x[1]):
        contenu = _telecharger_contenu(svc, file_id)
        for row in csv.reader(io.StringIO(contenu), delimiter=";"):
            if len(row) >= 2 and row[0] not in ("gencod", ""):
                g = row[0].strip()
                try:
                    ventes[g] = ventes.get(g, 0) + int(float(row[1]))
                    if len(row) >= 3 and row[2].strip() and g not in libelles:
                        libelles[g] = row[2].strip()
                except ValueError:
                    pass
        print(f"    {fname}")

    print(f"  → {len(ventes)} gencods vendus, {sum(ventes.values())} unités au total")

    # 2. Charger les référentiels
    adresses      = _charger_adresses()
    nomenclatures = _charger_nomenclatures()
    libelles_dict = charger_libelles_dict()

    def _lib(g):
        return (libelles.get(g) or libelles_dict.get(g) or "")

    os.makedirs(WORK_DIR, exist_ok=True)

    # 3. Produits non vendus : R1, < 4 ventes
    r1_gencods = {g: a for g, a in adresses.items() if a.startswith("R1")}
    non_vendus = [
        (g, _lib(g), adresse, ventes.get(g, 0))
        for g, adresse in sorted(r1_gencods.items(), key=lambda x: x[1])
        if ventes.get(g, 0) < 4
    ]

    nom_nv    = f"produits_non_vendus_{label}.csv"
    chemin_nv = os.path.join(WORK_DIR, nom_nv)
    with open(chemin_nv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["gencod", "libelle", "adresse", "ventes_mois"])
        w.writerows(non_vendus)
    print(f"\n  Produits non vendus : {len(non_vendus)} (sur {len(r1_gencods)} en R1)")
    print(f"  → {nom_nv}")
    upload_to_archive(chemin_nv, "analyses")

    # 4. Top ventes ELDPH hors R1 (nomenclature 01, top 200)
    top = []
    for g, qty in ventes.items():
        adresse = adresses.get(g, "")
        if adresse.startswith("R1"):
            continue
        nom_nomen = nomenclatures.get(g, "")
        if not nom_nomen.startswith("01"):
            continue
        top.append((g, _lib(g), adresse, qty, nom_nomen))

    top.sort(key=lambda x: x[3], reverse=True)
    top = top[:200]

    nom_tv    = f"top_ventes_{label}.csv"
    chemin_tv = os.path.join(WORK_DIR, nom_tv)
    with open(chemin_tv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["gencod", "libelle", "adresse", "ventes_mois", "nomenclature"])
        w.writerows(top)
    print(f"  Top ventes ELDPH hors R1 : {len(top)} produits")
    print(f"  → {nom_tv}")
    upload_to_archive(chemin_tv, "analyses")

    print("\nAnalyse terminée.")


if __name__ == "__main__":
    main()
