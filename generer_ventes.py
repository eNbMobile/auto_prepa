#!/usr/bin/env python3
"""
Génère les ventes du jour depuis les BDC PDFs.
Sauvegarde ventes_JJ_MM.csv et l'archive sur Drive.
Ne génère PAS de fichier de stock théorique.
"""
import csv
import os
import sys
from datetime import date

import controle_stocks as cs


def main():
    args = sys.argv[1:]
    date_j1 = date.today()
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                date_j1 = date(int(a), int(m), int(j))
            except Exception:
                print(f"Format de date invalide : {args[i + 1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)

    cs._charger_config()

    print(f"\nGénération ventes du {date_j1.strftime('%d/%m/%Y')} …")
    ventes, libelles = cs.generer_ventes(date_j1)

    if not ventes:
        print("Aucune vente trouvée — aucun fichier généré.")
        sys.exit(1)

    dossier = date_j1.strftime("%d_%m")
    os.makedirs(cs.WORK_DIR, exist_ok=True)
    chemin_ventes = os.path.join(cs.WORK_DIR, f"ventes_{dossier}.csv")

    with open(chemin_ventes, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["gencod", "qty", "libelle"])
        for gencod, qty in sorted(ventes.items()):
            writer.writerow([gencod, qty, libelles.get(gencod, "")])

    print(f"Ventes sauvegardées : {chemin_ventes} ({len(ventes)} gencods)")
    cs.upload_to_archive(chemin_ventes, "ventes")


if __name__ == "__main__":
    main()
