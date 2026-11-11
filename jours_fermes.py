#!/usr/bin/env python3
"""Jours de fermeture du magasin (dimanches + dates de jours_fermes.txt).

Usage en ligne de commande :
  python3 jours_fermes.py --est-ferme [JJ/MM/AAAA]
      code retour 0 si le jour (aujourd'hui par défaut) est fermé, 1 sinon.
"""
import os
import sys
from datetime import date, datetime, timedelta

_FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jours_fermes.txt")


def charger_jours_fermes(chemin=_FICHIER):
    jours = set()
    try:
        with open(chemin, encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.split("#", 1)[0].strip()
                if ligne:
                    jours.add(datetime.strptime(ligne, "%d/%m/%Y").date())
    except FileNotFoundError:
        pass
    return jours


def est_ferme(d, jours_fermes=None):
    if jours_fermes is None:
        jours_fermes = charger_jours_fermes()
    return d.weekday() == 6 or d in jours_fermes


def dernier_jour_ventes(aujourdhui=None, jours_fermes=None):
    """Dernier jour ouvré avant aujourd'hui (hier, ou plus tôt si fermé)."""
    if jours_fermes is None:
        jours_fermes = charger_jours_fermes()
    d = (aujourdhui or date.today()) - timedelta(days=1)
    for _ in range(14):
        if not est_ferme(d, jours_fermes):
            return d
        d -= timedelta(days=1)
    return (aujourdhui or date.today()) - timedelta(days=1)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--est-ferme"]:
        jour = date.today()
        if len(args) > 1 and args[1]:
            jour = datetime.strptime(args[1], "%d/%m/%Y").date()
        ferme = est_ferme(jour)
        print(f"{jour.strftime('%d/%m/%Y')} : {'fermé' if ferme else 'ouvert'}")
        sys.exit(0 if ferme else 1)
    print(__doc__)
    sys.exit(2)
