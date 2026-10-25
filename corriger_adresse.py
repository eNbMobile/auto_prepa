#!/usr/bin/env python3
"""Corrige à la main l'adresse d'un gencod dans gencod_adresses.csv (Drive),
par exemple une adresse saisie incomplète (R1-TG-2 au lieu de R1-TG-2-1).

Usage : python3 bootstrap.py corriger_adresse.py <gencod> <adresse>

L'adresse attendue est au format du chemin de préparation
(chemin_prepa_ramasse.csv) : M1/M2/R1-ZONE-gondole-élément, ex. R1-TG-2-1.
Toutes les lignes du gencod sont corrigées ; un gencod absent est ajouté."""
import re
import sys

import controle_stocks as cs

RE_ADRESSE = re.compile(r"^[MR]\d-[A-Z]{2}-\d+-\d+$")


def _cle(gencod):
    gencod = gencod.strip()
    return gencod.lstrip("0").zfill(13) if gencod.isdigit() else gencod


def corriger(contenu, gencod, adresse):
    """Retourne (nouveau_contenu, anciennes_adresses) : chaque ligne
    'gencod;adresse' du gencod reçoit `adresse` (fins de ligne conservées) ;
    s'il n'y en a aucune, une ligne est ajoutée à la fin."""
    cle = _cle(gencod)
    lignes = contenu.splitlines(keepends=True)
    anciennes = []
    for i, ligne in enumerate(lignes):
        corps = ligne.rstrip("\r\n")
        champs = corps.split(";")
        if len(champs) >= 2 and _cle(champs[0]) == cle:
            anciennes.append(champs[1].strip())
            champs[1] = adresse
            lignes[i] = ";".join(champs) + ligne[len(corps):]
    if not anciennes:
        if lignes and not lignes[-1].endswith("\n"):
            lignes[-1] += "\n"
        lignes.append(f"{gencod};{adresse}\n")
    return "".join(lignes), anciennes


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    gencod, adresse = sys.argv[1].strip(), sys.argv[2].strip().upper()
    if not gencod.isdigit() or not RE_ADRESSE.match(adresse):
        print("ERREUR : gencod numérique et adresse complète (ex. R1-TG-2-1) attendus.")
        sys.exit(1)

    cs._charger_config()
    contenu = cs._lire_config_drive("gencod_adresses.csv")
    if contenu is None:
        print("ERREUR : gencod_adresses.csv introuvable sur Drive.")
        sys.exit(1)
    nouveau, anciennes = corriger(contenu, gencod, adresse)
    if anciennes and all(a == adresse for a in anciennes):
        print(f"{gencod} déjà à l'adresse {adresse} — rien à faire.")
        return
    if not cs.ecrire_config_drive("gencod_adresses.csv", nouveau):
        print("ERREUR : écriture de gencod_adresses.csv échouée.")
        sys.exit(1)
    if anciennes:
        print(f"{gencod} : {', '.join(anciennes)} → {adresse} dans gencod_adresses.csv.")
    else:
        print(f"{gencod};{adresse} ajouté à gencod_adresses.csv.")


if __name__ == "__main__":
    main()
