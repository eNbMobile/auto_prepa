#!/usr/bin/env python3
"""
build_libelles.py — Construit un dictionnaire gencod→libellé complet.

PRÉREQUIS :
  pip install curl-cffi browser-cookie3 beautifulsoup4

AVANT DE LANCER :
  Ouvre le site dans Firefox et navigue sur au moins une page produit
  (pour avoir un cf_clearance valide), puis laisse Firefox ouvert.

UTILISATION :
  DRIVE_CONFIG_FOLDER_ID=<id> python3 build_libelles.py

RÉSULTAT :
  v 4.0.0/libelles_dict.csv  (gencod;libelle, reprise automatique si interrompu)
  Uploadé automatiquement dans le dossier config Drive.
"""

import os
import re
import csv
import io
import json
import sys
import time
import random
import tempfile
from urllib.parse import urlparse

from curl_cffi.requests import Session as CurlSession
from bs4 import BeautifulSoup

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import controle_stocks
from controle_stocks import (
    WORK_DIR, _charger_config, _lire_config_drive, _get_drive_service,
)

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

OUTPUT_CSV = os.path.join(WORK_DIR, "libelles_dict.csv")

DELAI_MIN  = 1.0   # secondes entre requêtes (min)
DELAI_MAX  = 2.0   # secondes entre requêtes (max)
SAVE_EVERY = 20    # sauvegarder toutes les N entrées

# ─────────────────────────────────────────────────────────────────


def _charger_scraper_config():
    """Charge scraper_config.json depuis Drive. Retourne le dict ou quitte."""
    contenu = _lire_config_drive("scraper_config.json")
    if not contenu:
        print("ERREUR : scraper_config.json introuvable dans le dossier config Drive.")
        sys.exit(1)
    return json.loads(contenu)


def lire_gencods_r1():
    contenu = _lire_config_drive("gencod_adresses.csv")
    if not contenu:
        print("ERREUR : gencod_adresses.csv introuvable dans le dossier config Drive.")
        sys.exit(1)
    gencods = []
    for line in contenu.splitlines():
        p = line.strip().split(";", 1)
        if len(p) == 2 and p[1].strip().startswith("R1"):
            gencods.append(p[0].strip())
    return gencods


def get_cookies(domain):
    try:
        import browser_cookie3
        return {c.name: c.value for c in browser_cookie3.firefox(domain_name=domain)}
    except Exception as e:
        print(f"  ERREUR cookies Firefox : {e}")
        print(f"  → Ouvre le site dans Firefox avant de relancer.")
        return {}


def chercher_libelle(session, gencod, search_url, headers, tag, css_class):
    """Retourne le libellé via le moteur de recherche du site, ou '' si introuvable."""
    url = f"{search_url}{gencod}"
    try:
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.find(tag, class_=css_class)
        if el:
            txt = el.get_text(separator=" ", strip=True)
            return re.sub(r'\s+', ' ', txt).strip()
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
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        for g, lib in resultats.items():
            w.writerow([g, lib])


def upload_libelles():
    """Uploade libelles_dict.csv dans le dossier config Drive."""
    from googleapiclient.http import MediaFileUpload
    svc = _get_drive_service()
    if not svc or not controle_stocks.DRIVE_CONFIG_FOLDER_ID:
        return
    folder_id = controle_stocks.DRIVE_CONFIG_FOLDER_ID
    existing = svc.files().list(
        q=f"'{folder_id}' in parents and name='libelles_dict.csv' and trashed=false",
        fields="files(id)",
    ).execute().get("files", [])
    media = MediaFileUpload(OUTPUT_CSV, mimetype="text/csv")
    if existing:
        svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        svc.files().create(
            body={"name": "libelles_dict.csv", "parents": [folder_id]},
            media_body=media, fields="id",
        ).execute()
    print(f"  libelles_dict.csv uploadé sur Drive.")


def main():
    _charger_config()
    scfg = _charger_scraper_config()

    base_url    = scfg["base_url"].rstrip("/")
    search_url  = base_url + scfg["search_path"]
    domain      = urlparse(base_url).hostname
    tag         = scfg.get("product_tag",   "h2")
    css_class   = scfg.get("product_class", "product-name")

    headers = {
        "User-Agent":      "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer":         base_url + "/",
    }

    gencods = lire_gencods_r1()
    print(f"{len(gencods)} gencods R1 à traiter")

    deja = charger_dict_existant()
    if deja:
        print(f"{len(deja)} libellés déjà en cache (reprise)")

    manquants = [g for g in gencods if g not in deja]
    print(f"{len(manquants)} à récupérer …\n")

    if not manquants:
        print("Rien à faire — dictionnaire déjà complet.")
        upload_libelles()
        return

    cookies = get_cookies(domain)
    if not cookies:
        return

    session = CurlSession(impersonate="firefox")
    session.cookies.update(cookies)

    resultats = dict(deja)
    erreurs_consec = 0

    for i, gencod in enumerate(manquants, 1):
        libelle = chercher_libelle(session, gencod, search_url, headers, tag, css_class)

        if libelle is None:
            erreurs_consec += 1
            print(f"  [{i}/{len(manquants)}] {gencod} → ERREUR (réessai dans 5s)")
            time.sleep(5)
            libelle = chercher_libelle(session, gencod, search_url, headers, tag, css_class) or ""
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
    upload_libelles()


if __name__ == "__main__":
    main()
