#!/usr/bin/env python3
"""Collecte les EAN-13 des produits Jeudi Plus et les dépose sur Drive
(GITHUB/JeudiPlus/jeudi_plus_eans.csv), liste lue par jeudi_plus.py à chaque
commande.

Usage :
  python3 bootstrap.py collecte_jeudi_plus.py --url <page coursesu.com> [--ajouter]
  python3 bootstrap.py collecte_jeudi_plus.py --eans "<EAN séparés par espaces, virgules ou lignes>" [--ajouter]

--url : la page de l'opération (ex. Jeudi Plus whisky et rhum) est ouverte
dans Chromium (Playwright), la bannière cookies acceptée et la liste
déroulée jusqu'au bout (défilement, boutons « voir plus »). L'EAN de chaque
produit est celui que porte l'URL de sa photo (ce qu'on lit dans la barre
d'adresse en ouvrant l'image dans un nouvel onglet) ; à défaut, celui du lien
vers la fiche produit.
--eans : liste collée à la main (EAN non valides écartés).
--ajouter : complète la liste existante au lieu de la remplacer.
"""
import argparse
import os
import re
import sys

import jeudi_plus as jp

_RE_13 = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_RE_BOUTON_PLUS = re.compile(r"(voir|afficher|charger)\s+(plus|la suite)|plus de produits", re.I)
_RE_COOKIES = re.compile(r"tout accepter|accepter( et fermer)?|j'accepte|ok pour moi", re.I)


def eans_dans_url(url):
    """EAN-13 valides d'une URL, le dernier segment du chemin d'abord (c'est
    lui qui nomme l'image ou la fiche produit)."""
    chemin = url.split("?", 1)[0]
    candidats = _RE_13.findall(chemin.rsplit("/", 1)[-1]) + _RE_13.findall(url)
    vus = []
    for c in candidats:
        if jp.ean13_valide(c) and c not in vus:
            vus.append(c)
    return vus


def eans_des_produits(produits):
    """{ean: libellé} depuis [(urls_images, urls_liens, libellé)] (une entrée
    par vignette produit), dans l'ordre de la page."""
    eans = {}
    for urls_images, urls_liens, libelle in produits:
        trouve = None
        for url in list(urls_images) + list(urls_liens):
            codes = eans_dans_url(url)
            if codes:
                trouve = codes[0]
                break
        if trouve:
            eans.setdefault(trouve, (libelle or "").strip())
    return eans


def eans_du_texte(texte):
    return {c: "" for c in _RE_13.findall(texte or "") if jp.ean13_valide(c)}


# Extrait, dans la page, une entrée par vignette produit : les URLs de ses
# images (src, data-src, srcset...) et de ses liens, et son libellé. Repli
# sur toutes les images de la page si aucune vignette n'est reconnue.
_JS_PRODUITS = r"""
() => {
  const urlsImg = (img) => {
    const out = [];
    for (const a of ['currentSrc', 'src']) if (img[a]) out.push(img[a]);
    for (const a of ['data-src', 'data-original', 'data-lazy', 'srcset', 'data-srcset']) {
      const v = img.getAttribute(a);
      if (v) for (const p of v.split(',')) out.push(p.trim().split(/\s+/)[0]);
    }
    return out;
  };
  const tuiles = Array.from(document.querySelectorAll(
    '.product-tile, [data-pid], .product, .grid-tile, article'))
    .filter(t => t.querySelector('img'));
  const racines = tuiles.filter(t => !tuiles.some(u => u !== t && u.contains(t)));
  const liste = racines.length ? racines : Array.from(document.querySelectorAll('img'));
  return liste.map(t => {
    const imgs = t.tagName === 'IMG' ? [t] : Array.from(t.querySelectorAll('img, source'));
    const liens = t.tagName === 'IMG' ? [] : Array.from(t.querySelectorAll('a[href]')).map(a => a.href);
    const titre = t.querySelector ? t.querySelector('.product-name, .pdp-link, h2, h3, a[title]') : null;
    const lib = (titre && (titre.getAttribute('title') || titre.textContent))
             || (imgs[0] && imgs[0].getAttribute('alt')) || '';
    return [imgs.flatMap(urlsImg), liens, lib.replace(/\s+/g, ' ').trim()];
  });
}
"""


def collecter_page(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # CHROMIUM_PATH : navigateur déjà installé (hors GitHub Actions).
        nav = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = nav.new_page(locale="fr-FR", viewport={"width": 1400, "height": 1000},
                            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/124.0 Safari/537.36"))
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        try:
            page.get_by_role("button", name=_RE_COOKIES).first.click(timeout=5000)
        except Exception:
            pass
        precedent, stable = -1, 0
        while stable < 3:
            page.mouse.wheel(0, 20000)
            page.wait_for_timeout(1500)
            try:
                bouton = page.get_by_role("button", name=_RE_BOUTON_PLUS).first
                if bouton.is_visible():
                    bouton.click(timeout=5000)
                    page.wait_for_timeout(2500)
            except Exception:
                pass
            nb = page.evaluate("document.querySelectorAll('img').length")
            stable = stable + 1 if nb == precedent else 0
            precedent = nb
        produits = page.evaluate(_JS_PRODUITS)
        print(f"Page : {page.title()} — {len(produits)} vignette(s) produit")
        nav.close()
    return eans_des_produits(produits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--eans", default="")
    ap.add_argument("--ajouter", action="store_true")
    args = ap.parse_args()
    if not args.url and not args.eans:
        print(__doc__)
        sys.exit(1)

    eans = {}
    if args.url:
        eans.update(collecter_page(args.url))
    eans.update({c: l for c, l in eans_du_texte(args.eans).items() if c not in eans})
    if not eans:
        print("ERREUR : aucun EAN-13 trouvé — liste Drive inchangée.")
        sys.exit(1)

    import controle_stocks as cs
    cs._charger_config()
    drive_svc = cs._get_drive_service()
    if not drive_svc:
        print("ERREUR : Drive inaccessible.")
        sys.exit(1)
    if args.ajouter:
        existants = jp.charger_eans(drive_svc)
        eans = {**existants, **{c: l for c, l in eans.items() if jp.cle_ean(c) not in existants}}

    contenu = "ean;libelle\n" + "".join(f"{c};{l.replace(';', ' ')}\n" for c, l in eans.items())
    dossier_id = jp.dossier_jeudi_plus(drive_svc)
    jp.ecrire_texte(drive_svc, dossier_id, jp.FICHIER_EANS, contenu)
    print(contenu, end="")
    print(f"\n{len(eans)} EAN déposé(s) dans {jp.DOSSIER_GITHUB}/{jp.DOSSIER}/{jp.FICHIER_EANS}")

    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write(f"## Jeudi Plus : {len(eans)} EAN\n\n| EAN | Libellé |\n|---|---|\n")
            f.writelines(f"| {c} | {l} |\n" for c, l in eans.items())


if __name__ == "__main__":
    main()
