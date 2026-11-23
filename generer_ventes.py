#!/usr/bin/env python3
"""
Génère les ventes du jour depuis les BDC PDFs.
Sauvegarde ventes_JJ_MM.csv et l'archive sur Drive, puis calcule la valeur
vendue au Drive (UVC vendues × prix du stock du matin) et l'inscrit dans
CA DRIVE AAAA.xlsx (onglet RÉALISATION), totale et restreinte aux classeurs
de commande (tableau VALEUR VENDUE DRIVE CLASSEURS CDE), et dépose dans
MobUDrive_Bons le stock du soir (stock du matin − ventes du jour) sous le
nom stock.xlsx, pour l'app.
Ne génère PAS de fichier de stock théorique.
"""
import csv
import os
import sys
from datetime import date

import controle_stocks as cs
import stock_mobudrive
import valeur_vendue_drive as vvd


def _signaler_echec(date_j1, motif):
    """Échec visible dans le log et en annotation GitHub (plus d'email
    d'alerte : un échec attendu, ex. ventes d'un jour à venir sans stock du
    matin pour la valeur vendue, ne doit pas générer de mail)."""
    print(f"::error::Générer Ventes du {date_j1.strftime('%d/%m/%Y')} : {motif}")


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
    try:
        ventes, libelles = cs.generer_ventes(date_j1)
    except Exception as e:
        _signaler_echec(date_j1, f"Exception pendant le calcul des ventes : {type(e).__name__}")
        raise

    if not ventes:
        _signaler_echec(date_j1, "Aucune vente trouvée (BDC introuvables ou dossier vide) — "
                                 "aucun fichier généré. Normal si jour de fermeture.")
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
    echec = False
    ok = cs.upload_to_archive(chemin_ventes, "ventes", root_id=cs.DRIVE_CONFIG_FOLDER_ID)
    if not ok:
        _signaler_echec(date_j1, f"{os.path.basename(chemin_ventes)} généré localement mais "
                                 "l'upload vers Drive Archives/ventes/ a échoué.")
        echec = True

    # Valeur vendue au Drive (UVC × prix du stock du matin) → CA DRIVE AAAA.xlsx
    try:
        vvd.traiter(date_j1, ventes)
    except Exception as e:
        print(f"  Valeur vendue au Drive : échec — {e}")
        _signaler_echec(date_j1, f"Valeur vendue au Drive non calculée ou non inscrite "
                                 f"dans CA DRIVE ({type(e).__name__})")
        echec = True

    # Stock du soir (stock du matin − ventes du jour) consultable dans l'app MobUDrive
    try:
        stock_mobudrive.publier_soir(date_j1, ventes)
    except Exception as e:
        print(f"  Stock MobUDrive (soir) non déposé : {type(e).__name__}")
        _signaler_echec(date_j1, f"Stock du soir non déposé dans MobUDrive_Bons ({type(e).__name__})")
        echec = True

    if echec:
        sys.exit(1)


if __name__ == "__main__":
    main()
