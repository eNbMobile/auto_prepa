#!/usr/bin/env python3
"""Exclut à la main des commandes du relevé Jeudi Plus (cf. jeudi_plus.py) :
elles disparaissent du récapitulatif et du PDF de leur jour de retrait, et ne
sont plus jamais relevées, même régénérées ou reprises par le rattrapage.

Usage : python3 bootstrap.py exclure_jeudi_plus.py <n° commande> [<n° commande> ...]
        (numéros séparés par des espaces ou des virgules)
"""
import re
import sys

import jeudi_plus as jp


def main():
    numeros = [n for n in re.split(r"[\s,;]+", " ".join(sys.argv[1:])) if n]
    if not numeros or not all(n.isdigit() for n in numeros):
        print(__doc__)
        sys.exit(1)

    import controle_stocks as cs
    drive_svc = cs._get_drive_service()
    if not drive_svc:
        print("ERREUR : Drive inaccessible.")
        sys.exit(1)
    for numero, articles in jp.exclure_commandes(drive_svc, numeros).items():
        print(f"cde {numero} exclue ({articles} article(s) Jeudi Plus retiré(s) du relevé)")
    print(f"Liste : {jp.DOSSIER_GITHUB}/{jp.DOSSIER}/{jp.FICHIER_EXCLUES}")


if __name__ == "__main__":
    main()
