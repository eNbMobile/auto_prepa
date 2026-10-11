#!/usr/bin/env python3
"""
Classe les commandes Drive par tranche de montant, semaine par semaine.

Source : les BonDeCommande_xxx.pdf du dossier Drive BDC/MM_AAAA/JJ_MM de chaque
jour de retrait / livraison de la période (hors commandes annulées /
remplacées, comme les ventes du jour). Le montant retenu est le "Montant
initial" du bon (frais de livraison compris).

Tranches :
  1. 30,00 € → 49,99 €
  2. 50,00 € → 79,99 €
  3. 80,00 € → 99,99 €
  4. 100,00 € → 120,00 €
  5. plus de 120 €
(les commandes de moins de 30 € sont comptées à part.)

Le tableau est affiché dans le log et, sur GitHub Actions, dans le résumé du run.

Usage : classement_paniers.py --du JJ/MM/AAAA --au JJ/MM/AAAA
"""
import os
import re
import subprocess
import sys
from datetime import date, timedelta

import controle_stocks as cs

TRANCHES = [
    ("Moins de 30 €",         None,  30.00),
    ("1. 30 € – 49,99 €",     30.00, 50.00),
    ("2. 50 € – 79,99 €",     50.00, 80.00),
    ("3. 80 € – 99,99 €",     80.00, 100.00),
    ("4. 100 € – 120 €",      100.00, 120.005),
    ("5. Plus de 120 €",      120.005, None),
]

_RE_MONTANT = re.compile(r"Montant\s+initial\s+(\d+(?:[.,]\d+)?)", re.I)


def montant_bon(texte):
    """Montant initial d'un bon (texte pdftotext), ou None si introuvable."""
    m = _RE_MONTANT.search(texte)
    return float(m.group(1).replace(",", ".")) if m else None


def tranche(montant):
    """Index de la tranche du montant dans TRANCHES."""
    montant = round(montant, 2)
    for i, (_, bas, haut) in enumerate(TRANCHES):
        if (bas is None or montant >= bas) and (haut is None or montant < haut):
            return i
    raise ValueError(montant)


def montants_du_jour(jour, annulees):
    """(montants, illisibles) des bons du jour, ou None si le dossier est absent."""
    bdc_dir = cs.telecharger_bdc_depuis_drive(jour)
    if not bdc_dir or not os.path.isdir(bdc_dir):
        return None
    montants, illisibles = [], []
    for pdf in sorted(os.listdir(bdc_dir)):
        if not (pdf.startswith("BonDeCommande_") and pdf.endswith(".pdf")):
            continue
        numero = pdf.removeprefix("BonDeCommande_").removesuffix(".pdf")
        if numero in annulees:
            continue
        pt = subprocess.run(["pdftotext", "-layout", os.path.join(bdc_dir, pdf), "-"],
                            capture_output=True, text=True)
        m = montant_bon(pt.stdout)
        if m is None:
            illisibles.append(numero)
        else:
            montants.append(m)
    return montants, illisibles


def _lire_date(txt):
    j, m, a = txt.split("/")
    return date(int(a), int(m), int(j))


def _eur(x):
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def tableau(semaines):
    """Tableau Markdown : une ligne par tranche, deux colonnes par semaine."""
    entete = "| Tranche |" + "".join(f" {s} (nb) | {s} (%) |" for s in semaines) + "\n"
    entete += "|---|" + "---:|---:|" * len(semaines) + "\n"
    lignes = []
    for i, (nom, _, _) in enumerate(TRANCHES):
        cellules = ""
        for s in semaines.values():
            total = len(s["montants"])
            n = s["compte"][i]
            cellules += f" {n} | {100 * n / total:.1f} % |" if total else " 0 | – |"
        lignes.append(f"| {nom} |{cellules}")
    tot = "| **Total** |" + "".join(
        f" **{len(s['montants'])}** | 100 % |" for s in semaines.values())
    ca = "| CA / panier moyen |" + "".join(
        f" {_eur(sum(s['montants']))} | {_eur(sum(s['montants']) / len(s['montants'])) if s['montants'] else '–'} |"
        for s in semaines.values())
    return entete + "\n".join(lignes + [tot, ca]) + "\n"


def main():
    args = sys.argv[1:]
    try:
        du = _lire_date(args[args.index("--du") + 1])
        au = _lire_date(args[args.index("--au") + 1])
    except (ValueError, IndexError):
        print(__doc__)
        sys.exit(1)

    cs._charger_config()
    annulees = cs.numeros_annules_registre()

    semaines = {}
    jour = du
    while jour <= au:
        if jour.weekday() != 6:  # pas de drive le dimanche
            lundi = jour - timedelta(days=jour.weekday())
            cle = f"S{jour.isocalendar()[1]:02d} ({lundi:%d/%m}→{lundi + timedelta(days=5):%d/%m})"
            s = semaines.setdefault(cle, {"montants": [], "compte": [0] * len(TRANCHES)})
            res = montants_du_jour(jour, annulees)
            if res is None:
                print(f"  {jour:%d/%m/%Y} : aucun bon.")
            else:
                montants, illisibles = res
                print(f"  {jour:%d/%m/%Y} : {len(montants)} commande(s)"
                      + (f", montant illisible : {', '.join(illisibles)}" if illisibles else ""))
                for m in montants:
                    s["montants"].append(m)
                    s["compte"][tranche(m)] += 1
        jour += timedelta(days=1)

    md = (f"### Commandes Drive par tranche de montant ({du:%d/%m/%Y} → {au:%d/%m/%Y})\n\n"
          + tableau(semaines))
    print("\n" + md)
    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
