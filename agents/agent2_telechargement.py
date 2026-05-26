#!/usr/bin/env python3
"""
Agent 2 - Téléchargement des visuels depuis coursesu.com
Se base sur ~/visuels_ean.db (rempli par agent1) pour savoir quels EAN traiter.
Utilise les cookies Firefox pour s'authentifier.
Tourne la nuit (cron ou boucle interne).
"""

import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

DB_PATH = os.path.expanduser("~/visuels_ean.db")
VISUELS_DIR = Path(os.environ.get("VISUELS_DIR", os.path.expanduser("~/visuels")))
BASE_URL = os.environ.get("COURSESU_URL", "https://www.coursesu.com")
DELAY_ENTRE_TELECHARGEMENTS = float(os.environ.get("DELAY_DL", "1.5"))  # secondes
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))


# ──────────────────────────────────────────────────────────────────
# SQLite
# ──────────────────────────────────────────────────────────────────

def _init_db_visuels(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS visuels_ean (
            id           INTEGER PRIMARY KEY,
            ean          TEXT NOT NULL,
            bdc_numero   TEXT,
            date_bdc     TEXT,
            drive_file_id TEXT,
            date_ajout   TEXT DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ean_fichier
            ON visuels_ean(ean, drive_file_id);
        CREATE TABLE IF NOT EXISTS visuels_telechargements (
            ean         TEXT PRIMARY KEY,
            statut      TEXT,       -- 'ok', 'absent', 'erreur'
            chemin      TEXT,
            url         TEXT,
            tente_le    TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _eans_a_traiter(conn, batch_size):
    """Retourne les EAN pas encore téléchargés."""
    rows = conn.execute("""
        SELECT DISTINCT v.ean
        FROM visuels_ean v
        LEFT JOIN visuels_telechargements t ON t.ean = v.ean
        WHERE t.ean IS NULL
           OR t.statut = 'erreur'
        LIMIT ?
    """, (batch_size,)).fetchall()
    return [r[0] for r in rows]


def _enregistrer_resultat(conn, ean, statut, chemin=None, url=None):
    conn.execute("""
        INSERT INTO visuels_telechargements(ean, statut, chemin, url, tente_le)
        VALUES(?, ?, ?, ?, datetime('now'))
        ON CONFLICT(ean) DO UPDATE SET
            statut=excluded.statut,
            chemin=excluded.chemin,
            url=excluded.url,
            tente_le=excluded.tente_le
    """, (ean, statut, chemin, url))
    conn.commit()


# ──────────────────────────────────────────────────────────────────
# Cookies Firefox
# ──────────────────────────────────────────────────────────────────

def _get_session_avec_cookies():
    """Crée une session requests avec les cookies Firefox pour coursesu.com."""
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
        print(f"  Cookies Firefox chargés pour coursesu.com")
    except Exception as e:
        print(f"  Avertissement : impossible de charger les cookies Firefox : {e}")
        print("  Les téléchargements publics continueront sans authentification.")
    return session


# ──────────────────────────────────────────────────────────────────
# Téléchargement du visuel
# ──────────────────────────────────────────────────────────────────

_PATTERNS_VISUELS = [
    "/media/catalog/product/{e0}/{e1}/{ean}.jpg",
    "/media/catalog/product/{e0}/{e1}/{ean}.png",
    "/media/catalog/product/{e0}/{e1}/{ean}_1.jpg",
    "/img/produits/{ean}.jpg",
]


def _url_candidats(ean):
    """Génère les URLs candidates pour un EAN."""
    e0, e1 = ean[0], ean[1]
    urls = []
    for pattern in _PATTERNS_VISUELS:
        urls.append(
            BASE_URL.rstrip("/") + pattern.format(ean=ean, e0=e0, e1=e1)
        )
    return urls


def telecharger_visuel(session, ean, dest_dir):
    """
    Essaie de télécharger le visuel d'un EAN.
    Retourne (statut, chemin_local, url_utilisée).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for url in _url_candidats(ean):
        try:
            resp = session.get(url, timeout=15, allow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 500:
                ext = ".jpg" if "jpeg" in resp.headers.get("Content-Type", "") or url.endswith(".jpg") else ".png"
                dest = dest_dir / f"{ean}{ext}"
                dest.write_bytes(resp.content)
                return "ok", str(dest), url
        except Exception:
            continue
    return "absent", None, None


# ──────────────────────────────────────────────────────────────────
# Boucle principale
# ──────────────────────────────────────────────────────────────────

def traiter_batch(conn, session):
    eans = _eans_a_traiter(conn, BATCH_SIZE)
    if not eans:
        return 0

    print(f"  {len(eans)} EAN à traiter…")
    ok = absent = erreurs = 0

    for ean in eans:
        statut, chemin, url = telecharger_visuel(session, ean, VISUELS_DIR)
        _enregistrer_resultat(conn, ean, statut, chemin, url)
        if statut == "ok":
            print(f"    ✓ {ean} → {chemin}")
            ok += 1
        else:
            print(f"    ✗ {ean} → introuvable")
            absent += 1
        time.sleep(DELAY_ENTRE_TELECHARGEMENTS)

    print(f"  Résultat : {ok} ok, {absent} absents, {erreurs} erreurs")
    return ok + absent + erreurs


def main():
    print(f"=== Agent 2 - Téléchargement visuels ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    VISUELS_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    _init_db_visuels(conn)

    try:
        session = _get_session_avec_cookies()
    except ImportError:
        return

    try:
        while True:
            debut = time.time()
            try:
                n = traiter_batch(conn, session)
                if n == 0:
                    print("  Aucun EAN en attente.")
            except Exception as e:
                print(f"  Erreur : {e}")
            elapsed = time.time() - debut
            # Attente jusqu'à la prochaine heure ronde (ou 1h par défaut)
            prochaine = 3600 - (elapsed % 3600)
            print(f"  Prochain passage dans {int(prochaine // 60)}min.")
            time.sleep(prochaine)
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
