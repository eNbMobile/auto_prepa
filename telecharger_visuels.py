#!/usr/bin/env python3
"""
Télécharge les visuels produits depuis coursesu.com dans le dossier local visuels_produits/.

Les EAN sont lus depuis visuels_ean_liste.json (fichier local ou sur Drive).
Les EAN déjà présents sur enbmobile.nl/mobUDrive/visuels/ sont automatiquement ignorés.

Usage :
    python3 telecharger_visuels.py [chemin/visuels_ean_liste.json]

    Sans argument : cherche visuels_ean_liste.json dans le dossier courant,
    puis sur Drive (DRIVE_CONFIG_FOLDER_ID).

Variables optionnelles :
    DRIVE_CONFIG_FOLDER_ID  ID du dossier Drive (si lecture depuis Drive)
    GOOGLE_TOKEN_JSON       Token OAuth Google (si lecture depuis Drive)
    VISUELS_DIR             Dossier de destination (défaut: visuels_produits)
    BATCH_SIZE              Nombre d'EAN par exécution (défaut: 0 = tous)
    DELAY_DL                Délai entre téléchargements en secondes (défaut: 2)
    NAVIGATEUR              firefox ou chrome (défaut: firefox)
    TAILLE_IMAGE            Taille des images en px (défaut: 400)
"""

import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Flush immédiat pour les logs en temps réel
sys.stdout.reconfigure(line_buffering=True)

VISUELS_DIR  = Path(os.environ.get("VISUELS_DIR", "visuels_produits"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE", "0"))
DELAY        = float(os.environ.get("DELAY_DL", "2"))
NAVIGATEUR   = os.environ.get("NAVIGATEUR", "firefox")
TAILLE_IMAGE = int(os.environ.get("TAILLE_IMAGE", "400"))

URL_VERIF       = "https://enbmobile.nl/mobUDrive/visuels/{gencod}.png"
FICHIER_IGNORES = "gencods_ignores.txt"

PHRASES_AUCUN_RESULTAT = [
    "nous n'avons rien trouvé pour",
    "aucun résultat",
    "no results",
    "ces produits pourraient vous plaire",
]


# ── Chargement de la liste EAN ────────────────────────────────────

def _charger_local(chemin):
    with open(chemin, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        print(f"ERREUR : {chemin} doit être une liste JSON.")
        sys.exit(1)
    return data


def _charger_drive():
    token_file = os.path.expanduser("~/.auto_prepa_token.json")
    folder_id  = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")
    if not folder_id:
        return None

    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_json:
        with open(token_file, "w") as f:
            f.write(token_json)
    if not os.path.exists(token_file):
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload

        creds = Credentials.from_authorized_user_file(
            token_file, ["https://www.googleapis.com/auth/drive.readonly"])
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)

        q = (f"name='visuels_ean_liste.json' and '{folder_id}' in parents"
             " and trashed=false")
        files = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if not files:
            return None

        buf = io.BytesIO()
        dl  = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        return json.loads(buf.getvalue())
    except Exception as e:
        print(f"  Avertissement Drive : {e}")
        return None


def charger_eans(chemin_arg=None):
    if chemin_arg:
        print(f"Lecture {chemin_arg} …")
        return _charger_local(chemin_arg)

    local = Path("visuels_ean_liste.json")
    if local.exists():
        print(f"Lecture {local} (local) …")
        return _charger_local(local)

    print("visuels_ean_liste.json non trouvé localement, tentative Drive …")
    data = _charger_drive()
    if data is None:
        print("ERREUR : visuels_ean_liste.json introuvable (local ni Drive).")
        sys.exit(1)
    print("  Chargé depuis Drive.")
    return data


# ── Session HTTP avec cookies navigateur ─────────────────────────

def _get_session():
    try:
        import browser_cookie3
    except ImportError:
        print("ERREUR : pip install browser_cookie3")
        sys.exit(1)

    session = requests.Session()
    try:
        if NAVIGATEUR == "firefox":
            cookies = browser_cookie3.firefox(domain_name="coursesu.com")
        else:
            cookies = browser_cookie3.chrome(domain_name="coursesu.com")
        session.cookies = cookies
        print(f"  Cookies {NAVIGATEUR} chargés pour coursesu.com")
    except Exception as e:
        print(f"  Avertissement cookies : {e}")
    return session


# ── Vérification enbmobile ───────────────────────────────────────

def deja_sur_enbmobile(gencod):
    """Retourne True si le visuel est déjà sur enbmobile.nl (destination finale)."""
    url = URL_VERIF.format(gencod=gencod)
    try:
        resp = requests.head(url, timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


# ── Recherche image sur coursesu ─────────────────────────────────

def _ajuster_taille(url):
    url = re.sub(r'sw=\d+', f'sw={TAILLE_IMAGE}', url)
    url = re.sub(r'sh=\d+', f'sh={TAILLE_IMAGE}', url)
    return url


def _nettoyer_url(url):
    if url.count("https://") > 1:
        url = url.split("https://", 1)[1]
        url = "https://" + url.split("https://")[0]
    match = re.search(r'(.*?sm=fit)', url)
    if match:
        url = match.group(1)
    return url


def _aucun_resultat(soup):
    texte = soup.get_text().lower()
    return any(phrase in texte for phrase in PHRASES_AUCUN_RESULTAT)


def chercher_image(gencod, session):
    """Scrape la page de recherche coursesu et retourne l'URL image, 'AUCUN_RESULTAT', ou None."""
    url = f"https://www.coursesu.com/recherche?q={gencod}"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.coursesu.com/",
    }
    resp = session.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"  ⚠️  Status HTTP : {resp.status_code}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    if _aucun_resultat(soup):
        return "AUCUN_RESULTAT"

    for img in soup.find_all("img"):
        for attr in ["src", "data-src", "data-lazy-src"]:
            src = img.get(attr, "")
            if "static.coursesu.com" in src and "demandware" in src:
                return _ajuster_taille(_nettoyer_url(src))

    for img in soup.find_all("img"):
        srcset = img.get("srcset", "")
        if "static.coursesu.com" in srcset:
            premiere = srcset.split(",")[0].strip().split(" ")[0]
            return _ajuster_taille(_nettoyer_url(premiere))

    matches = re.findall(r'https://static\.coursesu\.com[^"\'>\s]+demandware[^"\'>\s]+', resp.text)
    if matches:
        return _ajuster_taille(_nettoyer_url(matches[0]))

    return None


# ── Téléchargement de l'image ────────────────────────────────────

def telecharger_image(url_image, chemin, session):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.coursesu.com/",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Connection": "keep-alive",
    }
    resp = session.get(url_image, headers=headers, timeout=15, stream=True)
    if resp.status_code == 403:
        raise Exception("403 Forbidden (anti-bot détecté)")
    resp.raise_for_status()
    with open(chemin, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)


# ── Pipeline principal ────────────────────────────────────────────

def main():
    from datetime import datetime
    chemin_arg = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"=== Téléchargement visuels ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

    tous_eans = charger_eans(chemin_arg)
    print(f"  {len(tous_eans)} EAN chargés")

    batch = tous_eans[:BATCH_SIZE] if BATCH_SIZE > 0 else tous_eans
    print(f"  Lot : {len(batch)} EAN\n")

    VISUELS_DIR.mkdir(parents=True, exist_ok=True)
    session = _get_session()

    resultats = {"deja_present": [], "succes": [], "ignore": [], "echec": []}

    for i, ean in enumerate(batch, 1):
        gencod_sans_zeros = ean.lstrip("0") or ean
        a_des_zeros = gencod_sans_zeros != ean
        dernier_est_deja_0 = ean.endswith("0")

        if a_des_zeros:
            print(f"[{i}/{len(batch)}] {ean} → sans zéros : {gencod_sans_zeros}")
        else:
            print(f"[{i}/{len(batch)}] {ean}")

        # 1. Déjà sur enbmobile.nl → ignorer
        if deja_sur_enbmobile(ean):
            print("    ⏭️  Déjà présent sur enbmobile.nl — ignoré")
            resultats["deja_present"].append(ean)
            continue

        # 2. Construire les variantes à essayer
        variantes = [gencod_sans_zeros]
        if a_des_zeros:
            variantes.append(ean)
        if not dernier_est_deja_0:
            variantes.append(gencod_sans_zeros[:-1] + "0")
            if a_des_zeros:
                variantes.append(ean[:-1] + "0")
        variantes = list(dict.fromkeys(variantes))

        url_image = None
        for variante in variantes:
            print(f"    🔍 Essai avec {variante}...", end=" ", flush=True)
            try:
                resultat = chercher_image(variante, session)
            except Exception as e:
                print(f"❌ Erreur : {e}")
                time.sleep(DELAY)
                continue

            if resultat and resultat != "AUCUN_RESULTAT":
                url_image = resultat
                print("✅ Trouvé !")
                break
            elif resultat == "AUCUN_RESULTAT":
                print("⛔ Aucun résultat")
            else:
                print("❌ Image non trouvée")

            time.sleep(DELAY)

        if not url_image:
            print("    ⛔ Aucun résultat après toutes les variantes — ignoré")
            with open(FICHIER_IGNORES, "a") as f:
                f.write(ean + "\n")
            resultats["ignore"].append(ean)
            continue

        # 3. Télécharger — nom fichier = EAN original
        chemin = VISUELS_DIR / f"{ean}.png"
        try:
            telecharger_image(url_image, chemin, session)
            taille_ko = chemin.stat().st_size // 1024
            print(f"    ✅ Téléchargé ({taille_ko} Ko) → {ean}.png")
            resultats["succes"].append(ean)
        except Exception as e:
            print(f"    ❌ Erreur téléchargement : {e}")
            resultats["echec"].append(ean)

        time.sleep(DELAY)

    print(f"\n── Résultat ───────────────────────────")
    print(f"  Déjà sur enbmobile (ignorés) : {len(resultats['deja_present'])}")
    print(f"  Téléchargés                  : {len(resultats['succes'])}")
    print(f"  Introuvables (ignorés)       : {len(resultats['ignore'])}")
    print(f"  Erreurs                      : {len(resultats['echec'])}")
    if resultats["ignore"]:
        print(f"\n  EAN ignorés enregistrés dans : {FICHIER_IGNORES}")
    if resultats["echec"]:
        print(f"\n  EAN en échec :")
        for g in resultats["echec"]:
            print(f"    • {g}  → https://www.coursesu.com/recherche?q={g}")
    print(f"\n  Images dans : {VISUELS_DIR.resolve()}/")


if __name__ == "__main__":
    main()
