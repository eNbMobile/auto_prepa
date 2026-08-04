#!/usr/bin/env python3
"""
Cumule les ventes de la semaine en cours (lundi → date donnée, dimanche par défaut).
Sauvegarde ventes_SXX.csv (XX = numéro de semaine sur 2 chiffres) et l'archive
sur Drive dans Controles Stock > Archives > VMS.
"""
import csv
import os
import sys
from datetime import date, timedelta

import controle_stocks as cs


def main():
    args = sys.argv[1:]
    date_fin = date.today()
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                date_fin = date(int(a), int(m), int(j))
            except Exception:
                print(f"Format de date invalide : {args[i + 1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)

    cs._charger_config()

    lundi = date_fin - timedelta(days=date_fin.weekday())
    jours = [lundi + timedelta(days=i) for i in range(7) if lundi + timedelta(days=i) <= date_fin]

    numero_semaine = date_fin.isocalendar()[1]
    print(f"\nCumul des ventes semaine {numero_semaine:02d} "
          f"({jours[0].strftime('%d/%m/%Y')} → {jours[-1].strftime('%d/%m/%Y')}) …")

    ventes = {}
    libelles = {}
    for jour in jours:
        print(f"  {jour.strftime('%d/%m/%Y')} :")
        v_jour, l_jour = cs.generer_ventes(jour)
        for gencod, qty in v_jour.items():
            ventes[gencod] = ventes.get(gencod, 0) + qty
            if gencod not in libelles and gencod in l_jour:
                libelles[gencod] = l_jour[gencod]

    if not ventes:
        print("Aucune vente trouvée sur la semaine — aucun fichier généré.")
        sys.exit(1)

    os.makedirs(cs.WORK_DIR, exist_ok=True)
    chemin_ventes = os.path.join(cs.WORK_DIR, f"ventes_S{numero_semaine:02d}.csv")

    with open(chemin_ventes, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["gencod", "qty", "libelle"])
        for gencod, qty in sorted(ventes.items()):
            writer.writerow([gencod, qty, libelles.get(gencod, "")])

    print(f"\nCumul semaine {numero_semaine:02d} sauvegardé : {chemin_ventes} "
          f"({len(ventes)} gencods, {sum(ventes.values())} produits)")
    cs.upload_to_archive(chemin_ventes, "VMS")


if __name__ == "__main__":
    main()
