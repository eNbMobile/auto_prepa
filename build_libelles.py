#!/usr/bin/env python3
"""
build_libelles.py — Construit un dictionnaire gencod→libellé complet via coursesu.com
=======================================================================================
PRÉREQUIS :
  pip install curl-cffi browser-cookie3 beautifulsoup4

AVANT DE LANCER :
  Ouvre coursesu.com dans Firefox et navigue sur au moins une page produit
  (pour avoir un cf_clearance valide), puis laisse Firefox ouvert.

UTILISATION :
  python3 build_libelles.py

RÉSULTAT :
  v 4.0.0/libelles_dict.csv  (gencod;libelle, reprise automatique si interrompu)
"""

import os
import re
import csv
import time
import random

from curl_cffi.requests import Session as CurlSession
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

_BASE    = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(_BASE, "v 4.0.0")

ADRESSES_CSV = os.path.join(WORK_DIR, "gencod_adresses.csv")
OUTPUT_CSV   = os.path.join(WORK_DIR, "libelles_dict.csv")

DELAI_MIN = 1.0   # secondes entre requêtes (min)
DELAI_MAX = 2.0   # secondes entre requêtes (max)
SAVE_EVERY = 20   # sauvegarder toutes les N entrées

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.coursesu.com/",
}

# ─────────────────────────────────────────────────────────────────

def lire_gencods_r1():
    gencods = []
    with open(ADRESSES_CSV, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            p = line.strip().split(";", 1)
            if len(p) == 2 and p[1].strip().startswith("R1"):
                gencods.append(p[0].strip())
    return gencods


def get_cookies():
    try:
        import browser_cookie3
        return {c.name: c.value for c in browser_cookie3.firefox(domain_name="coursesu.com")}
    except Exception as e:
        print(f"  ERREUR cookies Firefox : {e}")
        print("  → Ouvre coursesu.com dans Firefox avant de relancer.")
        return {}


def chercher_libelle(session, gencod):
    """Retourne le libellé depuis coursesu.com, ou '' si introuvable."""
    url = f"https://www.coursesu.com/recherche?q={gencod}"
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None  # None = erreur réseau, à réessayer
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.find("h2", class_="product-name")
        if el:
            # get_text avec séparateur pour ajouter un espace entre marque et nom
            txt = el.get_text(separator=" ", strip=True)
            # Supprimer les espaces multiples
            return re.sub(r'\s+', ' ', txt).strip()
        # Aucun résultat sur coursesu
        return ""
    except Exception as e:
        print(f"    ERREUR réseau {gencod}: {e}")
        return None


def charger_dict_existant():
    if not os.path.exists(OUTPUT_CSV):
        return {}
    d = {}
    with open(OUTPUT_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) >= 2:
                d[row[0]] = row[1]
    return d


def sauvegarder(resultats):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        for g, lib in resultats.items():
            w.writerow([g, lib])


def main():
    gencods = lire_gencods_r1()
    print(f"{len(gencods)} gencods R1 à traiter")

    deja = charger_dict_existant()
    if deja:
        print(f"{len(deja)} libellés déjà en cache (reprise)")

    manquants = [g for g in gencods if g not in deja]
    print(f"{len(manquants)} à récupérer sur coursesu.com …\n")

    if not manquants:
        print("Rien à faire — dictionnaire déjà complet.")
        return

    cookies = get_cookies()
    if not cookies:
        return

    session = CurlSession(impersonate="firefox")
    session.cookies.update(cookies)

    resultats = dict(deja)
    erreurs_consec = 0

    for i, gencod in enumerate(manquants, 1):
        libelle = chercher_libelle(session, gencod)

        if libelle is None:
            # Erreur réseau — on réessaie avec un délai plus long
            erreurs_consec += 1
            print(f"  [{i}/{len(manquants)}] {gencod} → ERREUR (réessai dans 5s)")
            time.sleep(5)
            libelle = chercher_libelle(session, gencod) or ""
            if erreurs_consec >= 5:
                print("  Trop d'erreurs consécutives — arrêt.")
                sauvegarder(resultats)
                return
        else:
            erreurs_consec = 0

        resultats[gencod] = libelle
        statut = libelle[:60] if libelle else "— introuvable"
        print(f"  [{i}/{len(manquants)}] {gencod} → {statut}")

        if i % SAVE_EVERY == 0:
            sauvegarder(resultats)
            print(f"  ↳ Sauvegarde ({len(resultats)} entrées)")

        time.sleep(random.uniform(DELAI_MIN, DELAI_MAX))

    sauvegarder(resultats)
    trouves = sum(1 for v in resultats.values() if v)
    print(f"\nDictionnaire complet : {OUTPUT_CSV}")
    print(f"  {trouves} libellés trouvés / {len(resultats)} gencods")


if __name__ == "__main__":
    main()
