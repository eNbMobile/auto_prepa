#!/usr/bin/env python3
"""
Génère les ventes du jour depuis les BDC PDFs.
Sauvegarde ventes_JJ_MM.csv et l'archive sur Drive.
Ne génère PAS de fichier de stock théorique.
"""
import base64
import csv
import os
import sys
from datetime import date
from email.mime.text import MIMEText

import controle_stocks as cs


def _alerter_echec(date_j1, motif):
    """Email d'alerte Gmail : ce workflow n'a ni retry ni seuil comme aut_prep,
    donc sans ça un échec (ou un upload Drive raté) passe inaperçu."""
    try:
        svc = cs._get_gmail_service()
        if not svc or not cs.EMAIL_DESTINATAIRE:
            print(f"  Alerte non envoyée (Gmail/destinataire indisponible) : {motif}")
            return
        msg = MIMEText(
            f"Générer Ventes du {date_j1.strftime('%d/%m/%Y')} en échec :\n\n{motif}\n\n"
            "Les ventes de ce jour sont absentes ou incomplètes sur Drive."
        )
        msg["To"] = cs.EMAIL_DESTINATAIRE
        if cs.EMAIL_COPIE_STOCK:
            msg["Cc"] = cs.EMAIL_COPIE_STOCK
        msg["Subject"] = f"[Générer Ventes] Échec du {date_j1.strftime('%d/%m/%Y')}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print("  Email d'alerte envoyé.")
    except Exception as e:
        print(f"  Email d'alerte échoué : {e}")


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
        _alerter_echec(date_j1, f"Exception pendant le calcul des ventes : {e}")
        raise

    if not ventes:
        _alerter_echec(date_j1, "Aucune vente trouvée (BDC introuvables ou dossier vide) — "
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
    ok = cs.upload_to_archive(chemin_ventes, "ventes", root_id=cs.DRIVE_CONFIG_FOLDER_ID)
    if not ok:
        _alerter_echec(date_j1, f"{os.path.basename(chemin_ventes)} généré localement mais "
                                 "l'upload vers Drive Archives/ventes/ a échoué.")
        sys.exit(1)


if __name__ == "__main__":
    main()
