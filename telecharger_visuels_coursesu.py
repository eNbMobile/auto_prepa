#!/usr/bin/env python3
"""Telecharge les visuels produits manquants depuis coursesu.com.

Pour chaque gencod present dans visuels_ean.json (cf. collecte_ean.yml), le
script verifie d'abord si le visuel existe deja sur enbmobile.nl (si oui, on
ne retelecharge pas) puis, sinon, recherche le produit sur
coursesu.com/recherche?q=<gencod> et, s'il est trouve, telecharge sa photo
en PNG 400x400 dans le dossier de sortie (nommee <gencod>.png). Quand la
recherche ne trouve rien, coursesu.com affiche quand meme un "produit
similaire" a ignorer : ce cas est detecte via le message "nous n'avons rien
trouve pour ..." et le gencod est simplement saute.

A executer EN LOCAL : coursesu.com bloque au niveau pare-feu les IP de
datacenter (GitHub Actions, environnements cloud), seule une connexion
"normale" passe.

Usage :
    python3 telecharger_visuels_coursesu.py visuels_ean.json
    python3 telecharger_visuels_coursesu.py visuels_ean.json --sortie /chemin/vers/dossier
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

_RECHERCHE_URL = "https://www.coursesu.com/recherche?q={gencod}"
_TAILLE_IMAGE = "sw=400&sh=400&sm=fit"

# Visuels deja en ligne sur l'application (cf. anticipation_commandes.py) :
# si l'un des deux existe, inutile d'aller le chercher sur coursesu.com.
_VISUELS_ENBMOBILE_URL = "http://enbmobile.nl/mobUDrive/visuels/"
_PHOTO_EXTENSIONS = (".jpg", ".png")
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Present uniquement quand coursesu.com n'a rien trouve pour le gencod (il
# affiche alors un faux resultat "produit similaire" qu'il faut ignorer).
_RE_INTROUVABLE = re.compile(r"avons rien trouv", re.IGNORECASE)

# Chaque fiche produit porte data-item-ean="<gencod>" ; sa photo est juste
# apres, dans data-image-source="<url>?sw=..&sh=..&..." (on ignore les
# parametres de taille d'origine pour les remplacer par les notres).
_RE_IMAGE = re.compile(r'data-image-source="(https://static\.coursesu\.com/[^"?]+)')

DOSSIER_SORTIE_DEFAUT = Path.home() / "Téléchargements" / "visuels_produits"
FICHIER_INTROUVABLES = "introuvables.json"


def _charger_gencods(chemin_json):
    donnees = json.loads(Path(chemin_json).read_text(encoding="utf-8"))
    vus = set()
    gencods = []
    for entree in donnees:
        ean = str(entree.get("ean", "")).strip()
        if ean and ean not in vus:
            vus.add(ean)
            gencods.append(ean)
    return gencods


def _requete_texte(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _requete_binaire(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _visuel_existe_sur_enbmobile(gencod):
    """True si le visuel du gencod est deja en ligne sur enbmobile.nl."""
    for ext in _PHOTO_EXTENSIONS:
        url = f"{_VISUELS_ENBMOBILE_URL}{gencod}{ext}"
        req = urllib.request.Request(url, headers=_HEADERS, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=10):
                return True
        except urllib.error.URLError:
            continue
    return False


def _url_image_produit(gencod, html_resultats):
    """Retourne l'URL (400x400) de la photo du gencod dans la page de
    resultats, ou None si coursesu.com n'a rien trouve pour ce gencod."""
    if _RE_INTROUVABLE.search(html_resultats):
        return None
    for segment in html_resultats.split('data-item-ean="')[1:]:
        if not segment.startswith(gencod + '"'):
            continue
        m = _RE_IMAGE.search(segment[:4000])
        if m:
            return f"{m.group(1)}?{_TAILLE_IMAGE}"
    return None


def telecharger_visuel(gencod, dossier_sortie):
    """Recherche puis telecharge le visuel d'un gencod.

    Retourne "ok", "introuvable", ou "erreur:<detail>"."""
    try:
        html_resultats = _requete_texte(_RECHERCHE_URL.format(gencod=gencod))
    except (urllib.error.URLError, TimeoutError) as e:
        return f"erreur:{e}"

    url_image = _url_image_produit(gencod, html_resultats)
    if url_image is None:
        return "introuvable"

    try:
        image = _requete_binaire(url_image)
    except (urllib.error.URLError, TimeoutError) as e:
        return f"erreur:{e}"

    (Path(dossier_sortie) / f"{gencod}.png").write_bytes(image)
    return "ok"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("visuels_ean_json", help="Chemin vers visuels_ean.json")
    parser.add_argument("--sortie", default=str(DOSSIER_SORTIE_DEFAUT),
                         help=f"Dossier de sortie des PNG (defaut : {DOSSIER_SORTIE_DEFAUT})")
    parser.add_argument("--pause", type=float, default=1.0,
                         help="Pause en secondes entre deux gencods (defaut : 1.0)")
    parser.add_argument("--reessayer-introuvables", action="store_true",
                         help="Retente les gencods deja marques introuvables lors d'un run precedent")
    args = parser.parse_args()

    dossier_sortie = Path(args.sortie)
    dossier_sortie.mkdir(parents=True, exist_ok=True)

    chemin_etat = dossier_sortie / FICHIER_INTROUVABLES
    introuvables = set(json.loads(chemin_etat.read_text(encoding="utf-8"))) if chemin_etat.exists() else set()

    gencods = _charger_gencods(args.visuels_ean_json)
    print(f"{len(gencods)} gencod(s) a traiter.")

    nb_ok = nb_deja = nb_deja_enbmobile = nb_introuvable = nb_erreur = 0
    for i, gencod in enumerate(gencods, 1):
        if (dossier_sortie / f"{gencod}.png").exists():
            nb_deja += 1
            continue
        if gencod in introuvables and not args.reessayer_introuvables:
            nb_introuvable += 1
            continue
        if _visuel_existe_sur_enbmobile(gencod):
            nb_deja_enbmobile += 1
            print(f"[{i}/{len(gencods)}] {gencod} : deja present sur enbmobile.nl, ignore")
            continue

        resultat = telecharger_visuel(gencod, dossier_sortie)
        if resultat == "ok":
            nb_ok += 1
            introuvables.discard(gencod)
            print(f"[{i}/{len(gencods)}] {gencod} : visuel telecharge")
        elif resultat == "introuvable":
            nb_introuvable += 1
            introuvables.add(gencod)
            print(f"[{i}/{len(gencods)}] {gencod} : introuvable sur coursesu.com")
        else:
            nb_erreur += 1
            print(f"[{i}/{len(gencods)}] {gencod} : {resultat}")

        chemin_etat.write_text(json.dumps(sorted(introuvables), ensure_ascii=False, indent=2),
                                encoding="utf-8")
        time.sleep(args.pause)

    print(f"\nTermine : {nb_ok} telecharge(s), {nb_deja} deja present(s) localement, "
          f"{nb_deja_enbmobile} deja present(s) sur enbmobile.nl, "
          f"{nb_introuvable} introuvable(s), {nb_erreur} erreur(s).")


if __name__ == "__main__":
    main()
