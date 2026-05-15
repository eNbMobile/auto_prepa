#!/usr/bin/env python3
"""
generer_ventes.py — Télécharge les BDC du jour et calcule les quantités vendues.
Écrit ventes_JJ_MM.csv dans WORK_DIR et l'uploade sur Drive.

Usage :
  python3 generer_ventes.py [--date JJ/MM/AAAA]
  (défaut : date du jour)
"""

import sys
import os
import csv
import subprocess
from datetime import date, timedelta

# Importer les fonctions partagées depuis controle_stocks
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from controle_stocks import (
    WORK_DIR, BDC_DIR, TOKEN_FILE,
    _charger_config,
    telecharger_bdc_depuis_drive, extraire_ventes_pdf,
    charger_gencods_r1, charger_libelles_dict, lire_stock,
    telecharger_fichier_controle,
    upload_to_archive,
)


def main():
    # Restaurer le token Drive depuis l'env var (CI)
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

    # Charger les IDs Drive depuis config.json, puis les CSVs de config
    _charger_config()

    # Date cible (défaut : aujourd'hui)
    date_cible = date.today()
    args = sys.argv[1:]
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                date_cible = date(int(a), int(m), int(j))
            except Exception:
                print(f"Format de date invalide : {args[i + 1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)

    dossier = date_cible.strftime("%d_%m")
    print(f"Génération ventes du {date_cible.strftime('%d/%m/%Y')} …")

    # Télécharger les BDC depuis Drive
    bdc_subdir = telecharger_bdc_depuis_drive(dossier) or os.path.join(BDC_DIR, dossier)

    if not os.path.isdir(bdc_subdir):
        print("  Aucun BDC disponible — arrêt.")
        sys.exit(1)

    pdfs = sorted(f for f in os.listdir(bdc_subdir)
                  if f.startswith("BonDeCommande_") and f.endswith(".pdf"))
    if not pdfs:
        print(f"  Aucun BonDeCommande dans {bdc_subdir} — arrêt.")
        sys.exit(1)

    print(f"  {len(pdfs)} BonDeCommande(s) …")

    ventes = {}
    libelles = {}
    for pdf in pdfs:
        pt = subprocess.run(["pdftotext", "-layout", os.path.join(bdc_subdir, pdf), "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            continue
        v, l = extraire_ventes_pdf(pt.stdout, None)
        for gencod, qty in v.items():
            ventes[gencod] = ventes.get(gencod, 0) + qty
            if gencod not in libelles and gencod in l:
                libelles[gencod] = l[gencod]

    print(f"  → {len(ventes)} gencods, {sum(ventes.values())} produits total")

    # Écrire le CSV
    nom = f"ventes_{dossier}.csv"
    chemin = os.path.join(WORK_DIR, nom)
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["gencod", "qty", "libelle"])
        for gencod in sorted(ventes):
            w.writerow([gencod, ventes[gencod], libelles.get(gencod, "")])
    print(f"  → {chemin} ({len(ventes)} lignes)")

    upload_to_archive(chemin, "ventes")

    # Calculer le théorique (j1 - ventes) et l'uploader
    print("\nTéléchargement j1.xlsx pour calcul théorique …")
    j1_path = telecharger_fichier_controle('j1.xlsx')
    if j1_path:
        veille = date_cible - timedelta(days=1)
        upload_to_archive(j1_path, "stocks", f"stock_{veille.strftime('%d_%m_%Y')}_j1.xlsx")
        stock_j1, libelles_j1 = lire_stock(j1_path)
        libelles_dict = charger_libelles_dict()
        gencods_r1    = charger_gencods_r1()
        tous = gencods_r1 if gencods_r1 is not None else set(stock_j1)

        def _fmt(v):
            v = float(v)
            return str(int(v)) if v == int(v) else f"{v:.3f}"

        nom_theo   = f"theo_{dossier}.csv"
        chemin_theo = os.path.join(WORK_DIR, nom_theo)
        nb_theo = 0
        with open(chemin_theo, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["gencod", "libelle", "stock_j1", "ventes", "stock_theo"])
            for gencod in sorted(tous):
                if gencod not in stock_j1:
                    continue
                s_j1_v  = float(stock_j1[gencod])
                v_val   = float(ventes.get(gencod, 0))
                s_theo  = s_j1_v - v_val
                lib     = (libelles_dict.get(gencod)
                           or libelles_j1.get(gencod)
                           or libelles.get(gencod, ''))
                w.writerow([gencod, lib, _fmt(s_j1_v), _fmt(v_val), _fmt(s_theo)])
                nb_theo += 1
        print(f"  → {chemin_theo} ({nb_theo} lignes)")
        upload_to_archive(chemin_theo, "théo")
    else:
        print("  j1.xlsx indisponible — théorique non calculé.")


if __name__ == "__main__":
    main()
