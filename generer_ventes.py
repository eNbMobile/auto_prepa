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
from datetime import date

# Importer les fonctions partagées depuis controle_stocks
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from controle_stocks import (
    WORK_DIR, BDC_DIR, TOKEN_FILE,
    telecharger_bdc_depuis_drive, extraire_ventes_pdf,
    charger_gencods_r1, upload_drive,
)


def main():
    # Restaurer le token Drive depuis l'env var (CI)
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

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
    gencods_r1 = charger_gencods_r1()

    ventes = {}
    libelles = {}
    for pdf in pdfs:
        pt = subprocess.run(["pdftotext", "-layout", os.path.join(bdc_subdir, pdf), "-"],
                            capture_output=True, text=True)
        if not pt.stdout.strip():
            continue
        v, l = extraire_ventes_pdf(pt.stdout, gencods_r1)
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

    upload_drive(chemin)


if __name__ == "__main__":
    main()
