#!/usr/bin/env python3
"""
Lit les BonDeCommande_*.pdf archives dans BDC/MM_AAAA/JJ_MM (a partir de
demain, puis les jours suivants tant qu'ils contiennent deja au moins une
commande) et note dans un fichier .txt le numero des commandes contenant au
moins un produit dont l'adresse (gencod_adresses.csv) commence par
ADRESSE_CIBLE_DEFAUT (defaut : 'M2-MM-2-12').

Usage :
    python3 commandes_par_adresse.py [--adresse M2-MM-2-12] [--sortie fichier.txt]

Pour tester sur toutes les commandes deja traitees (tout BDC_DIR, toutes
dates) plutot que seulement demain/jeudi/jours suivants :
    python3 commandes_par_adresse.py --toutes
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import date, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.environ.get("WORK_DIR", os.path.join(_BASE, "v 4.0.0"))
BDC_DIR  = os.environ.get("BDC_DIR",  os.path.join(_BASE, "BDC"))

ADRESSE_CIBLE_DEFAUT = "M2-MM-2-12"

# Meme regex que controle_stocks.extraire_ventes_pdf : les gencods sont
# imprimes tres indentes dans le pdftotext -layout des BonDeCommande.
_RE_GENCOD = re.compile(r'^\s{8,}(\d{8,13})(?!\d)')


def charger_gencods_adresse(chemin, prefixe):
    """Retourne l'ensemble des gencods (normalises sur 13 chiffres) dont
    l'adresse (gencod_adresses.csv, format 'gencod;adresse') commence par
    prefixe."""
    gencods = set()
    with open(chemin, encoding='utf-8-sig', errors='replace') as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            parts = ligne.split(';', 1)
            if len(parts) < 2:
                continue
            gencod, adresse = parts[0].strip(), parts[1].strip()
            if gencod.isdigit():
                gencod = gencod.lstrip('0').zfill(13)
            if adresse.startswith(prefixe):
                gencods.add(gencod)
    return gencods


def dossier_bdc_du_jour(jour):
    """Chemin du dossier BDC d'un jour donne : BDC/MM_AAAA/JJ_MM si ce
    sous-dossier mensuel existe, sinon BDC/JJ_MM (structure locale utilisee
    par auto_prepa.py quand aucun classement mensuel n'a ete cree)."""
    dossier_mm_aaaa = jour.strftime("%m_%Y")
    dossier_jj_mm   = jour.strftime("%d_%m")
    avec_mois = os.path.join(BDC_DIR, dossier_mm_aaaa, dossier_jj_mm)
    if os.path.isdir(avec_mois):
        return avec_mois
    return os.path.join(BDC_DIR, dossier_jj_mm)


def commandes_du_jour(jour):
    """Liste triee des chemins BonDeCommande_*.pdf du dossier BDC d'un jour."""
    dossier = dossier_bdc_du_jour(jour)
    if not os.path.isdir(dossier):
        return []
    return sorted(
        os.path.join(dossier, f) for f in os.listdir(dossier)
        if f.startswith("BonDeCommande_") and f.endswith(".pdf")
    )


def toutes_les_commandes():
    """Liste triee (dossier, chemin) de tous les BonDeCommande_*.pdf presents
    dans BDC_DIR, quelle que soit la date (pour tester sur les commandes deja
    traitees, pas seulement celles a venir)."""
    trouvees = []
    for racine, _dirs, fichiers in os.walk(BDC_DIR):
        for f in fichiers:
            if f.startswith("BonDeCommande_") and f.endswith(".pdf"):
                trouvees.append((os.path.relpath(racine, BDC_DIR), os.path.join(racine, f)))
    return sorted(trouvees)


def numero_commande(pdf_path):
    return os.path.basename(pdf_path).removeprefix("BonDeCommande_").removesuffix(".pdf")


def commande_contient_adresse(pdf_path, gencods_cibles):
    """Vrai si un des gencods lus dans le PDF (pdftotext -layout) fait partie
    de gencods_cibles."""
    pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                        capture_output=True, text=True)
    if not pt.stdout.strip():
        print(f"    ECHEC pdftotext : {pdf_path}")
        return False
    for ligne in pt.stdout.splitlines():
        m = _RE_GENCOD.match(ligne)
        if m and m.group(1).zfill(13) in gencods_cibles:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Liste les commandes des prochains jours contenant un "
                    "produit a une adresse donnee.")
    parser.add_argument("--adresse", default=ADRESSE_CIBLE_DEFAUT,
                        help=f"Prefixe d'adresse recherche (defaut : {ADRESSE_CIBLE_DEFAUT})")
    parser.add_argument("--gencod-adresses",
                        default=os.path.join(WORK_DIR, "gencod_adresses.csv"),
                        help="Chemin de gencod_adresses.csv")
    parser.add_argument("--sortie", default=None,
                        help="Fichier .txt de sortie (defaut : commandes_<adresse>.txt)")
    parser.add_argument("--toutes", action="store_true",
                        help="Teste sur toutes les commandes deja traitees (tout BDC_DIR, "
                             "toutes dates), au lieu de demain/jeudi/jours suivants seulement.")
    args = parser.parse_args()

    if not os.path.exists(args.gencod_adresses):
        print(f"ERREUR : {args.gencod_adresses} introuvable.")
        sys.exit(1)

    gencods_cibles = charger_gencods_adresse(args.gencod_adresses, args.adresse)
    print(f"{len(gencods_cibles)} gencod(s) a l'adresse '{args.adresse}'.")
    if not gencods_cibles:
        print("Aucun gencod a cette adresse, arret.")
        sys.exit(0)

    sortie = args.sortie or f"commandes_{args.adresse}.txt"

    commandes_trouvees = []
    nb_jours = 0
    nb_commandes = 0

    if args.toutes:
        par_dossier = toutes_les_commandes()
        if not par_dossier:
            print(f"Aucun BonDeCommande_*.pdf trouve sous {BDC_DIR}.")
        dossier_courant = None
        for dossier, pdf in par_dossier:
            if dossier != dossier_courant:
                dossier_courant = dossier
                nb_jours += 1
                print(f"\n{dossier} :")
            nb_commandes += 1
            numero = numero_commande(pdf)
            if commande_contient_adresse(pdf, gencods_cibles):
                print(f"  [{numero}] -> adresse '{args.adresse}' trouvee")
                commandes_trouvees.append(numero)
    else:
        jour = date.today() + timedelta(days=1)
        while True:
            pdfs = commandes_du_jour(jour)
            if not pdfs:
                break
            nb_jours += 1
            print(f"\n{jour.strftime('%d/%m/%Y')} : {len(pdfs)} commande(s)")
            for pdf in pdfs:
                nb_commandes += 1
                numero = numero_commande(pdf)
                if commande_contient_adresse(pdf, gencods_cibles):
                    print(f"  [{numero}] -> adresse '{args.adresse}' trouvee")
                    commandes_trouvees.append(numero)
            jour += timedelta(days=1)

    with open(sortie, "w", encoding="utf-8") as f:
        for numero in commandes_trouvees:
            f.write(numero + "\n")

    print(f"\n{len(commandes_trouvees)}/{nb_commandes} commande(s) sur {nb_jours} jour(s) "
          f"-> {sortie}")


if __name__ == "__main__":
    main()
