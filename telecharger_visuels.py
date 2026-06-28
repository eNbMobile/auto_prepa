#!/usr/bin/env python3
"""
Télécharge les visuels produits depuis coursesu.com dans le dossier local visuels_produits/.

Les EAN sont lus depuis visuels_ean_liste.json (fichier local ou sur Drive).
Les EAN déjà présents dans visuels_produits/ sont automatiquement ignorés.

Usage :
    python3 telecharger_visuels.py [chemin/visuels_ean_liste.json]

    Sans argument : cherche visuels_ean_liste.json dans le dossier courant,
    puis sur Drive (DRIVE_CONFIG_FOLDER_ID).

Variables optionnelles :
    DRIVE_CONFIG_FOLDER_ID  ID du dossier Drive (si lecture depuis Drive)
    GOOGLE_TOKEN_JSON       Token OAuth Google (si lecture depuis Drive)
    VISUELS_DIR             Dossier de destination (défaut: visuels_produits)
    COURSESU_URL            URL de base coursesu (défaut: https://www.coursesu.com)
    BATCH_SIZE              Nombre d'EAN par exécution (défaut: 0 = tous)
    DELAY_DL                Délai entre téléchargements en secondes (défaut: 0.5)
"""

import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# Flush immédiat pour les logs en temps réel
sys.stdout.reconfigure(line_buffering=True)

VISUELS_DIR   = Path(os.environ.get("VISUELS_DIR", "visuels_produits"))
BASE_URL      = os.environ.get("COURSESU_URL", "https://www.coursesu.com")
ENBMOBILE_URL = os.environ.get("ENBMOBILE_URL", "http://enbmobile.nl/MobUDrive/visuels")
BATCH_SIZE    = int(os.environ.get("BATCH_SIZE", "0"))
DELAY         = float(os.environ.get("DELAY_DL", "0.5"))

_PATTERNS = [
    "/media/catalog/product/{e0}/{e1}/{ean}.jpg",
    "/media/catalog/product/{e0}/{e1}/{ean}.png",
    "/media/catalog/product/{e0}/{e1}/{ean}_1.jpg",
    "/media/catalog/product/{e0}/{e1}/{ean}_2.jpg",
    "/img/produits/{ean}.jpg",
    "/img/produits/{ean}.png",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


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


# ── EAN déjà téléchargés ─────────────────────────────────────────

def eans_presents():
    if not VISUELS_DIR.exists():
        return set()
    return {
        re.sub(r'\.[a-zA-Z0-9]+$', '', f.name)
        for f in VISUELS_DIR.iterdir()
        if f.is_file()
    }


# ── Session HTTP avec cookies Firefox ────────────────────────────

def _get_session():
    try:
        import browser_cookie3
        import requests
    except ImportError:
        print("ERREUR : pip install browser_cookie3 requests")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        cookies = browser_cookie3.firefox(domain_name=".coursesu.com")
        session.cookies.update(cookies)
        print("  Cookies Firefox chargés pour coursesu.com")
    except Exception as e:
        print(f"  Avertissement cookies Firefox : {e}")
    return session


# ── Vérification enbmobile ───────────────────────────────────────

def deja_sur_enbmobile(ean):
    """Retourne True si le visuel est déjà présent sur enbmobile.nl (destination finale)."""
    base = ENBMOBILE_URL.rstrip("/")
    for ext in (".jpg", ".png"):
        url = f"{base}/{ean}{ext}"
        try:
            req = urllib.request.Request(url, method="HEAD", headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            continue
    return False


# ── Téléchargement depuis coursesu ───────────────────────────────

def telecharger_visuel(session, ean):
    """Retourne (data_bytes, extension) ou (None, None) si introuvable."""
    e0, e1 = ean[0], ean[1]
    for pattern in _PATTERNS:
        url = BASE_URL.rstrip("/") + pattern.format(ean=ean, e0=e0, e1=e1)
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200 and len(r.content) > 500:
                ct  = r.headers.get("Content-Type", "")
                ext = ".jpg" if "jpeg" in ct.lower() or url.endswith(".jpg") else ".png"
                return r.content, ext
        except Exception:
            continue
    return None, None


# ── Pipeline principal ────────────────────────────────────────────

def main():
    from datetime import datetime
    chemin_arg = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"=== Téléchargement visuels ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

    tous_eans = charger_eans(chemin_arg)
    print(f"  {len(tous_eans)} EAN chargés")

    deja = eans_presents()
    print(f"  {len(deja)} visuels déjà présents dans {VISUELS_DIR}/")

    a_traiter = [ean for ean in tous_eans if ean not in deja]
    if not a_traiter:
        print("Tous les visuels sont déjà téléchargés.")
        return

    batch = a_traiter[:BATCH_SIZE] if BATCH_SIZE > 0 else a_traiter
    print(f"  {len(a_traiter)} EAN manquants — téléchargement de {len(batch)}\n")

    VISUELS_DIR.mkdir(parents=True, exist_ok=True)

    session = _get_session()
    ok = absent = enbmobile_ok = erreur = 0

    for i, ean in enumerate(batch, 1):
        prefix = f"  [{i}/{len(batch)}] {ean}"

        # 1. Vérifier si déjà présent sur enbmobile.nl (destination finale → ignorer)
        if deja_sur_enbmobile(ean):
            print(f"{prefix} ↷ déjà sur enbmobile")
            enbmobile_ok += 1
            continue

        # 2. Télécharger depuis coursesu.com
        data, ext = telecharger_visuel(session, ean)
        if data is None:
            e0, e1 = ean[0], ean[1]
            exemple_url = (BASE_URL.rstrip("/")
                           + f"/media/catalog/product/{e0}/{e1}/{ean}.jpg")
            print(f"{prefix} ✗ introuvable  (ex: {exemple_url})")
            absent += 1
        else:
            dest = VISUELS_DIR / f"{ean}{ext}"
            try:
                dest.write_bytes(data)
                print(f"{prefix} ✓ coursesu ({len(data):,} o)")
                ok += 1
            except Exception as e:
                print(f"{prefix} ✗ erreur écriture : {e}")
                erreur += 1

        if i < len(batch):
            time.sleep(DELAY)

    print(f"\n── Résultat ───────────────────────────")
    if enbmobile_ok:
        print(f"  Déjà sur enbmobile (ignorés) : {enbmobile_ok}")
    print(f"  Téléchargés depuis coursesu : {ok}")
    print(f"  Introuvables : {absent}")
    if erreur:
        print(f"  Erreurs     : {erreur}")
    if BATCH_SIZE > 0 and len(a_traiter) > BATCH_SIZE:
        print(f"  Restants    : {len(a_traiter) - BATCH_SIZE}")


if __name__ == "__main__":
    main()
