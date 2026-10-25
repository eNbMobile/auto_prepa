#!/usr/bin/env python3
"""Ajoute à la main un gencod dans gencod_nomenclatures.csv (Drive), par
exemple après un email d'arbitrage fruits/légumes.

Usage : python3 bootstrap.py ajouter_nomenclature.py <gencod> <code_nomenclature>

Le code de nomenclature (18 chiffres) se trouve dans chemin_prepa_ramasse.csv
(ex. 026500000000000000 pour la poissonnerie). Un gencod déjà présent n'est
pas ajouté une seconde fois."""
import sys

import controle_stocks as cs


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    gencod, code = sys.argv[1].strip(), sys.argv[2].strip()
    if not gencod.isdigit() or not code.isdigit() or len(code) != 18:
        print("ERREUR : gencod numérique et code de nomenclature à 18 chiffres attendus.")
        sys.exit(1)

    cs._charger_config()
    nomenclatures = cs.charger_gencod_nomenclatures()
    cle = gencod.lstrip("0").zfill(13)
    if cle in nomenclatures:
        print(f"{gencod} déjà présent dans gencod_nomenclatures.csv "
              f"(code {nomenclatures[cle]}) — rien à faire.")
        return
    if not cs.ajouter_lignes_config_drive("gencod_nomenclatures.csv", [f"{gencod};{code}"]):
        print("ERREUR : ajout à gencod_nomenclatures.csv échoué.")
        sys.exit(1)
    print(f"{gencod};{code} ajouté à gencod_nomenclatures.csv.")


if __name__ == "__main__":
    main()
