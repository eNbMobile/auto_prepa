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
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "0"))  # 0 = pas de limite, traite tout à chaque passage
TRAITES_CACHE = Path(os.path.expanduser("~/.agent2_traites.json"))
IMAGE_SIZE = int(os.environ.get("IMAGE_SIZE", "400"))
URL_VERIF = os.environ.get("URL_VERIF", "https://enbmobile.nl/mobUDrive/visuels/{ean}.png")


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
# coursesu.com tourne sur Salesforce Commerce Cloud : il n'y a pas
# d'URL d'image prévisible à partir de l'EAN seul, il faut passer par
# la recherche du site et en extraire l'URL réelle sur static.coursesu.com.

_IMG_RE = re.compile(r'https://static\.coursesu\.com[^"\'>\s]+demandware[^"\'>\s]+')
_MSG_AUCUNE_CORRESPONDANCE = "produits similaires à votre recherche"


def _base_et_cle(ean):
    """Famille produit (6 chiffres après le 0 de tête) et clé de contrôle
    EAN-13 recalculée pour le code générique famille+000000+clé."""
    base = ean[1:7]
    radical = "0" + base + "00000"
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(radical))
    cle = (10 - total % 10) % 10
    return base, cle


def _est_poids_variable(ean):
    return len(ean) == 13 and ean.startswith("0")


def _codes_recherche(ean):
    """Les EAN poids variable (13 chiffres, préfixe 0) encodent un prix/poids
    variable dans les positions 8-12 : ça ne correspond à aucun produit sur
    coursesu.com. Il faut interroger le code générique de la famille produit :
    préfixe 0 retiré, positions 7-11 remises à 0. Selon les produits, le code
    de référence stocké chez coursesu.com se termine soit par des zéros, soit
    par une vraie clé de contrôle EAN-13 recalculée — pas de règle fixe, donc
    on essaie les deux variantes dans l'ordre.
    Ex : 0253082080037 → 253082000000 puis 253082000004."""
    if _est_poids_variable(ean):
        base, cle = _base_et_cle(ean)
        return [base + "000000", base + "00000" + str(cle)]
    return [ean]


def _ean_normalise(ean):
    """EAN canonique à utiliser pour le stockage/la déduplication d'un
    produit poids variable : préfixe 0 conservé, positions médianes à 0,
    clé de contrôle EAN-13 réelle en dernière position (pas la variante
    tout-à-zéro, qui n'est qu'un artefact de recherche côté coursesu.com).
    Ex : 0253071051437 → 0253071000008."""
    if _est_poids_variable(ean):
        base, cle = _base_et_cle(ean)
        return "0" + base + "00000" + str(cle)
    return ean


def deja_sur_enbmobile(session, ean):
    url = URL_VERIF.format(ean=ean)
    try:
        r = session.head(url, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def _nettoyer_url(url):
    if url.count("https://") > 1:
        url = url.split("https://", 1)[1]
        url = "https://" + url.split("https://")[0]
    m = re.search(r'(.*?sm=fit)', url)
    if m:
        url = m.group(1)
    return url.replace("&amp;", "&")


def _ajuster_taille(url):
    url = re.sub(r'sw=\d+', f'sw={IMAGE_SIZE}', url)
    url = re.sub(r'sh=\d+', f'sh={IMAGE_SIZE}', url)
    return url


def _chercher_avec_code(session, code):
    url = f"{BASE_URL.rstrip('/')}/recherche?q={code}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": BASE_URL.rstrip("/") + "/",
    }
    try:
        r = session.get(url, headers=headers, timeout=15)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    if _MSG_AUCUNE_CORRESPONDANCE in r.text.lower():
        # coursesu affiche des suggestions sans rapport quand le code exact
        # n'est pas trouvé — pas de résultat exploitable.
        return None

    for brut in _IMG_RE.findall(r.text):
        candidat = _ajuster_taille(_nettoyer_url(brut))
        # Le nom de fichier commence par le code recherché (avec ou sans le
        # zéro de tête, selon le produit) : filtre les suggestions résiduelles
        # sans rapport.
        nom_fichier = candidat.rsplit("/", 1)[-1]
        if nom_fichier.startswith(code) or nom_fichier.startswith("0" + code):
            return candidat
    return None


def chercher_image(session, ean):
    for code in _codes_recherche(ean):
        url_image = _chercher_avec_code(session, code)
        if url_image:
            return url_image
    return None


def telecharger_visuel(session, ean):
    # Pour un produit poids variable, l'image doit être stockée/recherchée
    # sous l'EAN générique de la famille, pas sous l'EAN de l'instance
    # scannée (qui varie selon le poids/prix).
    cle_stockage = _ean_normalise(ean)

    if deja_sur_enbmobile(session, cle_stockage):
        return "deja_present", None, URL_VERIF.format(ean=cle_stockage)

    url_image = chercher_image(session, ean)
    if not url_image:
        return "absent", None, None

    headers = {
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": BASE_URL.rstrip("/") + "/",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    try:
        r = session.get(url_image, headers=headers, timeout=15)
    except Exception:
        return "absent", None, None
    if r.status_code != 200 or len(r.content) < 500:
        return "absent", None, None

    dest = VISUELS_DIR / f"{cle_stockage}.png"
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(r.content)) as img:
            img.convert("RGBA").save(dest, "PNG")
    except Exception:
        return "absent", None, None
    return "ok", str(dest), url_image


# ──────────────────────────────────────────────────────────────────
# Boucle principale
# ──────────────────────────────────────────────────────────────────

def traiter_batch(service, session):
    tous_eans = charger_eans_drive(service)
    if not tous_eans:
        return 0

    traites = _charger_traites()
    a_traiter = [e for e in tous_eans if e["ean"] not in traites]
    if BATCH_SIZE > 0:
        a_traiter = a_traiter[:BATCH_SIZE]

    if not a_traiter:
        return 0

    print(f"  {len(a_traiter)} EAN à traiter (sur {len(tous_eans)} au total)")
    VISUELS_DIR.mkdir(parents=True, exist_ok=True)
    ok = deja = absent = 0

    for item in a_traiter:
        ean = item["ean"]
        statut, chemin, url = telecharger_visuel(session, ean)
        traites[ean] = {"statut": statut, "chemin": chemin, "bdc": item.get("bdc_numero")}
        _sauvegarder_traites(traites)  # à chaque EAN : un Ctrl+C ne perd que l'EAN en cours
        if statut == "ok":
            print(f"    ✓ {ean} → {chemin}")
            ok += 1
        elif statut == "deja_present":
            print(f"    ⏭ {ean} → déjà présent sur enbmobile.nl")
            deja += 1
            continue  # pas de requête coursesu.com, pas besoin de temporiser
        else:
            print(f"    ✗ {ean} → introuvable")
            absent += 1
        time.sleep(DELAY)

    print(f"  Résultat : {ok} ok, {deja} déjà présents, {absent} absents")
    return ok + deja + absent


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
