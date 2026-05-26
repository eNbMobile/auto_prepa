#!/usr/bin/env python3
import json
import os
import pickle
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

CREDENTIALS_FILE = os.path.expanduser("~/.credentials_drive.json")
TOKEN_FILE = os.path.expanduser("~/.drive_token.pkl")
DRIVE_CONFIG_FOLDER_ID = os.environ.get("DRIVE_CONFIG_FOLDER_ID", "")
VISUELS_DIR = Path(os.environ.get("VISUELS_DIR", os.path.expanduser("~/visuels")))
BASE_URL = os.environ.get("COURSESU_URL", "https://www.coursesu.com")
DELAY = float(os.environ.get("DELAY_DL", "1.5"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))
TRAITES_CACHE = Path(os.path.expanduser("~/.agent2_traites.json"))


# ──────────────────────────────────────────────────────────────────
# Auth Google Drive (OAuth2 local)
# ──────────────────────────────────────────────────────────────────

def _build_drive_service():
    import pickle as _p
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if Path(TOKEN_FILE).exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = _p.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE,
                ["https://www.googleapis.com/auth/drive.readonly"],
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            _p.dump(creds, f)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ──────────────────────────────────────────────────────────────────
# Lecture des EAN depuis Drive (data/visuels_ean.json)
# ──────────────────────────────────────────────────────────────────

def _lire_json_drive(service, folder_id, filename):
    q = (f"name='{filename}' and '{folder_id}' in parents"
         " and mimeType='application/json' and trashed=false")
    result = service.files().list(q=q, fields="files(id)").execute()
    files = result.get("files", [])
    if not files:
        return None
    from googleapiclient.http import MediaIoBaseDownload
    import io
    fh = io.BytesIO()
    dl = MediaIoBaseDownload(fh, service.files().get_media(fileId=files[0]["id"]))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return json.loads(fh.getvalue())


def charger_eans_drive(service):
    """Charge data/visuels_ean.json depuis le dossier config Drive."""
    if not DRIVE_CONFIG_FOLDER_ID:
        print("DRIVE_CONFIG_FOLDER_ID non défini.")
        return []
    # Chercher le sous-dossier data/
    q = (f"name='data' and '{DRIVE_CONFIG_FOLDER_ID}' in parents"
         " and mimeType='application/vnd.google-apps.folder' and trashed=false")
    folders = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if not folders:
        print("Dossier data/ introuvable sur Drive (agent1 n'a pas encore tourné ?).")
        return []
    data = _lire_json_drive(service, folders[0]["id"], "visuels_ean.json")
    if data is None:
        print("visuels_ean.json introuvable sur Drive.")
        return []
    return data  # liste de {ean, bdc_numero, date_bdc, drive_file_id}


# ──────────────────────────────────────────────────────────────────
# Suivi des EAN déjà téléchargés (cache local JSON)
# ──────────────────────────────────────────────────────────────────

def _charger_traites():
    if TRAITES_CACHE.exists():
        try:
            return json.loads(TRAITES_CACHE.read_text())
        except Exception:
            pass
    return {}


def _sauvegarder_traites(traites):
    TRAITES_CACHE.write_text(json.dumps(traites))


# ──────────────────────────────────────────────────────────────────
# Cookies Firefox + session requests
# ──────────────────────────────────────────────────────────────────

def _get_session():
    try:
        import browser_cookie3
        import requests
    except ImportError as e:
        print(f"Dépendance manquante : {e}\npip install browser_cookie3 requests")
        raise
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    })
    try:
        cookies = browser_cookie3.firefox(domain_name=".coursesu.com")
        session.cookies.update(cookies)
        print("  Cookies Firefox chargés.")
    except Exception as e:
        print(f"  Avertissement cookies : {e}")
    return session


# ──────────────────────────────────────────────────────────────────
# Téléchargement visuel
# ──────────────────────────────────────────────────────────────────

_PATTERNS = [
    "/media/catalog/product/{e0}/{e1}/{ean}.jpg",
    "/media/catalog/product/{e0}/{e1}/{ean}.png",
    "/media/catalog/product/{e0}/{e1}/{ean}_1.jpg",
    "/img/produits/{ean}.jpg",
]


def telecharger_visuel(session, ean):
    e0, e1 = ean[0], ean[1]
    for pattern in _PATTERNS:
        url = BASE_URL.rstrip("/") + pattern.format(ean=ean, e0=e0, e1=e1)
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200 and len(r.content) > 500:
                ext = ".jpg" if "jpeg" in r.headers.get("Content-Type", "").lower() else ".png"
                dest = VISUELS_DIR / f"{ean}{ext}"
                dest.write_bytes(r.content)
                return "ok", str(dest), url
        except Exception:
            continue
    return "absent", None, None


# ──────────────────────────────────────────────────────────────────
# Boucle principale
# ──────────────────────────────────────────────────────────────────

def traiter_batch(service, session):
    tous_eans = charger_eans_drive(service)
    if not tous_eans:
        return 0

    traites = _charger_traites()
    a_traiter = [e for e in tous_eans if e["ean"] not in traites][:BATCH_SIZE]

    if not a_traiter:
        return 0

    print(f"  {len(a_traiter)} EAN à traiter (sur {len(tous_eans)} au total)")
    VISUELS_DIR.mkdir(parents=True, exist_ok=True)
    ok = absent = 0

    for item in a_traiter:
        ean = item["ean"]
        statut, chemin, url = telecharger_visuel(session, ean)
        traites[ean] = {"statut": statut, "chemin": chemin, "bdc": item.get("bdc_numero")}
        if statut == "ok":
            print(f"    ✓ {ean} → {chemin}")
            ok += 1
        else:
            print(f"    ✗ {ean} → introuvable")
            absent += 1
        time.sleep(DELAY)

    _sauvegarder_traites(traites)
    print(f"  Résultat : {ok} ok, {absent} absents")
    return ok + absent


def main():
    print(f"=== Agent 2 - Téléchargement visuels ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

    try:
        service = _build_drive_service()
    except Exception as e:
        print(f"Erreur auth Drive : {e}")
        return

    try:
        session = _get_session()
    except ImportError:
        return

    try:
        while True:
            debut = time.time()
            try:
                n = traiter_batch(service, session)
                if n == 0:
                    print("  Aucun EAN en attente.")
            except Exception as e:
                print(f"  Erreur : {e}")
            elapsed = time.time() - debut
            prochaine = 3600 - (elapsed % 3600)
            print(f"  Prochain passage dans {int(prochaine // 60)} min.")
            time.sleep(prochaine)
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
