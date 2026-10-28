#!/usr/bin/env python3
"""Rattrapage Jeudi Plus : relève après coup les produits suivis des bons
déjà générés pour un jour de retrait/livraison (cf. jeudi_plus.py).

Usage : python3 bootstrap.py rattrapage_jeudi_plus.py [--date JJ/MM/AAAA] [--dossier ID_DRIVE]

Lit les bon_prepa_NUMERO.txt du dossier des bons (config.json :
drive_bons_folder_id), ceux déposés à la main dans GITHUB/JeudiPlus/Bons_prepa
et, si --dossier est donné, ceux de ce dossier Drive.
Seuls les bons dont la date de retrait est --date (défaut : demain) sont
relevés ; les commandes du registre des annulations sont écartées. Le
récapitulatif du jour (GITHUB/JeudiPlus/jeudi_plus_AAAA-MM-JJ.csv) est
réécrit même si aucun bon ne contient de produit suivi, et sa version PDF
(jeudi_plus_AAAA-MM-JJ.pdf, mise en page du contrôle de stocks) déposée à côté.
"""
import argparse
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta

import jeudi_plus as jp

_RE_BON = re.compile(r"^bon_prepa_(\d+)")
DOSSIER_DEPOT = "Bons_prepa"
_MIME_GDOC = "application/vnd.google-apps.document"


def lister_bons(drive_svc, dossier_id):
    """[(numéro, file_id, date de création, mimeType)] des bon_prepa d'un
    dossier (copies « bon_prepa_N (1).txt » et fichiers convertis en Google
    Docs compris)."""
    bons, page = [], None
    while True:
        res = drive_svc.files().list(
            q=f"'{dossier_id}' in parents and name contains 'bon_prepa_' and trashed=false",
            fields="nextPageToken, files(id,name,createdTime,mimeType)", pageSize=1000, pageToken=page,
        ).execute()
        for f in res.get("files", []):
            m = _RE_BON.match(f["name"])
            if m:
                bons.append((m.group(1), f["id"], f.get("createdTime", ""), f.get("mimeType", "")))
        page = res.get("nextPageToken")
        if not page:
            return bons


def lire_bon(drive_svc, file_id, mime):
    if mime == _MIME_GDOC:
        contenu = drive_svc.files().export(fileId=file_id, mimeType="text/plain").execute()
        return contenu.decode("utf-8-sig") if isinstance(contenu, bytes) else contenu
    return jp._telecharger_texte(drive_svc, file_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--dossier", default="")
    args = ap.parse_args()
    cible = (datetime.strptime(args.date, "%d/%m/%Y").date() if args.date.strip()
             else datetime.now(jp._TZ).date() + timedelta(days=1))
    cible_txt = cible.strftime("%d/%m/%Y")

    import auto_prepa as ap_
    import controle_stocks as cs
    drive_svc = cs._get_drive_service()
    if not drive_svc:
        print("ERREUR : Drive inaccessible.")
        sys.exit(1)
    if not jp.charger_eans(drive_svc):
        print(f"ERREUR : liste {jp.DOSSIER}/{jp.FICHIER_EANS} absente ou vide.")
        sys.exit(1)
    ap_._charger_config(drive_svc)
    annulees = {str(n) for n in cs.numeros_annules_registre()}

    depot_id = jp._sous_dossier(drive_svc, jp.dossier_jeudi_plus(drive_svc), DOSSIER_DEPOT, creer=False)
    dossiers = [d for d in (ap_.DRIVE_BONS_FOLDER_ID, depot_id, args.dossier.strip()) if d]
    bons = {}
    for dossier_id in dossiers:
        trouves = lister_bons(drive_svc, dossier_id)
        print(f"  dossier {'des bons' if dossier_id == ap_.DRIVE_BONS_FOLDER_ID else DOSSIER_DEPOT if dossier_id == depot_id else dossier_id} : {len(trouves)} bon(s)")
        for numero, file_id, cree, mime in trouves:
            bons.setdefault(numero, (file_id, cree, mime))
    print(f"{len(bons)} bon(s) trouvé(s) — retrait visé : {cible_txt}")

    commandes, ignores = [], 0
    for numero, (file_id, cree, mime) in sorted(bons.items()):
        if numero in annulees:
            ignores += 1
            continue
        lignes = lire_bon(drive_svc, file_id, mime).splitlines(keepends=True)
        if jp.date_retrait_bon(lignes) != cible_txt:
            continue
        recu = datetime.fromisoformat(cree.replace("Z", "+00:00")).astimezone(jp._TZ).date() \
            if cree else datetime.now(jp._TZ).date()
        commandes.append((numero, lignes, cible_txt, recu))

    articles = jp.noter_commandes(drive_svc, commandes, jours=[cible.strftime("%Y-%m-%d")])
    for numero, nb in articles.items():
        if nb:
            print(f"  cde {numero} : {nb} article(s) Jeudi Plus")
    total = sum(articles.values())
    fichier_recap = f"{jp.PREFIXE_RECAP}{cible:%Y-%m-%d}.csv"
    print(f"\n{len(commandes)} commande(s) pour le {cible_txt} ({ignores} annulée(s) écartée(s)), "
          f"{sum(1 for n in articles.values() if n)} avec des produits Jeudi Plus, "
          f"{total} article(s) au total.\nRécapitulatif : {jp.DOSSIER_GITHUB}/{jp.DOSSIER}/{fichier_recap}")

    dossier_id = jp.dossier_jeudi_plus(drive_svc)
    recap = jp._telecharger_texte(drive_svc, jp._trouver(drive_svc, dossier_id, fichier_recap))
    with tempfile.TemporaryDirectory() as tmp:
        pdf = jp.generer_pdf_recap(recap, cible, os.path.join(tmp, f"{jp.PREFIXE_RECAP}{cible:%Y-%m-%d}.pdf"))
        if pdf:
            with open(pdf, "rb") as f:
                jp.ecrire_texte(drive_svc, dossier_id, os.path.basename(pdf), f.read(),
                                mimetype="application/pdf")
            print(f"PDF : {jp.DOSSIER_GITHUB}/{jp.DOSSIER}/{os.path.basename(pdf)}")

    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write(f"## Jeudi Plus — retrait du {cible_txt}\n\n"
                    f"{len(commandes)} commande(s), {total} article(s)\n\n"
                    "| EAN | Libellé | Quantité | Commandes |\n|---|---|---|---|\n")
            for ligne in recap.splitlines()[1:]:
                ean, libelle, qte, nb = ligne.split(";")
                if qte != "0":
                    f.write(f"| {ean} | {libelle} | {qte} | {nb} |\n")


if __name__ == "__main__":
    main()
