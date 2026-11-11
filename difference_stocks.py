#!/usr/bin/env python3
"""
Différence de stocks du jour : stock du matin (archive
stock_JJ_MM_AAAA_matin.xlsx) comparé au J1 (j1.xlsx du dossier Drive du
contrôle de stocks), sur les gencods R1.

Lancé par la routine du soir, le mardi et le mercredi uniquement. Envoie le
PDF des différences au premier destinataire (email_destinataire) s'il y en a
au moins une ; sinon, aucun mail.

Usage : python3 difference_stocks.py [--date JJ/MM/AAAA]
  --date : jour du stock du matin (défaut : aujourd'hui, heure de Paris).
"""
import base64
import os
import sys
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import controle_stocks as cs

JOURS_ACTIFS = (1, 2)  # mardi, mercredi (date.weekday())


def calculer_differences(stock_matin, stock_j1, gencods_r1, libelles):
    """Lignes (format _construire_pdf_tableau, diff=True) des gencods R1 dont
    le stock J1 diffère du stock du matin, triées par |différence| décroissante."""
    rows = []
    for g in sorted(gencods_r1):
        if g not in stock_matin and g not in stock_j1:
            continue
        a, b = stock_matin.get(g, 0.0), stock_j1.get(g, 0.0)
        diff = b - a
        if abs(diff) < 0.001:
            continue
        rows.append((g, a, 0, 0, b, diff, "ECART", libelles.get(g, '')))
    rows.sort(key=lambda r: abs(r[5]), reverse=True)
    return rows


def envoyer_email(pdf, jour, nb):
    svc = cs._get_gmail_service()
    if not svc or not cs.EMAIL_DESTINATAIRE:
        print("  Email non envoyé (Gmail/destinataire indisponible).")
        return
    jour_txt = jour.strftime('%d/%m/%Y')
    msg = MIMEMultipart()
    msg['To'] = cs.EMAIL_DESTINATAIRE
    msg['Subject'] = (f"Différence de stocks {jour_txt} matin → J1 — "
                      f"{nb} différence{'s' if nb > 1 else ''}")
    msg.attach(MIMEText(
        f"Différence de stocks entre le stock du {jour_txt} matin et le J1 "
        f"(j1.xlsx du dossier Contrôle Stock) : {nb} produit{'s' if nb > 1 else ''}.\n\n"
        "Détail en pièce jointe.", 'plain', 'utf-8'))
    with open(pdf, 'rb') as f:
        part = MIMEApplication(f.read(), 'pdf')
    part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf))
    msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId='me', body={'raw': raw}).execute()
    print("  Email envoyé.")


def main():
    args = sys.argv[1:]
    jour = datetime.now(cs._TZ).date()
    if "--date" in args:
        i = args.index("--date")
        try:
            jour = datetime.strptime(args[i + 1], "%d/%m/%Y").date()
        except (IndexError, ValueError):
            print("Format de date invalide (attendu JJ/MM/AAAA).")
            sys.exit(1)

    if jour.weekday() not in JOURS_ACTIFS:
        print("Différence de stocks : uniquement le mardi et le mercredi — ignorée.")
        return

    cs._charger_config()

    nom_matin = cs.nom_archive_stock(jour, "matin")
    print(f"Téléchargement {nom_matin} (Archives/stocks) …")
    f_matin = cs.telecharger_fichier_archive("stocks", nom_matin, dest="stock_matin.xlsx",
                                             root_id=cs.DRIVE_CONFIG_FOLDER_ID)
    if not f_matin:
        print(f"ERREUR : {nom_matin} introuvable — différence impossible.")
        sys.exit(1)
    print("Téléchargement j1.xlsx (dossier contrôle) …")
    f_j1 = cs.telecharger_fichier_controle("j1.xlsx", dest="j1_soir.xlsx")
    if not f_j1:
        print("ERREUR : j1.xlsx introuvable — différence impossible.")
        sys.exit(1)

    stock_matin, lib_matin, _ = cs.lire_stock(f_matin, classeur_requis=False)
    stock_j1, lib_j1, _ = cs.lire_stock(f_j1, classeur_requis=False)
    print(f"  → matin : {len(stock_matin)} gencods, J1 : {len(stock_j1)} gencods")

    gencods_r1 = cs.charger_gencods_r1()
    if gencods_r1 is None:
        gencods_r1 = set(stock_matin) | set(stock_j1)
    libelles = {**lib_matin, **lib_j1, **cs.charger_libelles_dict()}

    rows = calculer_differences(stock_matin, stock_j1, gencods_r1, libelles)
    print(f"\n{len(rows)} différence(s).")
    if not rows:
        print("Aucune différence : pas d'email.")
        return

    nom_pdf = f"difference_stocks_{jour.strftime('%Y%m%d')}.pdf"
    titre = (f"<b>Différence de stocks — {jour.strftime('%d/%m/%Y')} matin → J1</b>"
             f"&nbsp;&nbsp;({len(rows)} écart{'s' if len(rows) > 1 else ''})")
    pdf = cs._construire_pdf_tableau(rows, titre, nom_pdf, diff=True)
    if pdf:
        envoyer_email(pdf, jour, len(rows))


if __name__ == "__main__":
    main()
