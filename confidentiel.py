"""Protection des donnees confidentielles dans les logs GitHub Actions.

Le depot est public : les logs de ses workflows sont lisibles par n'importe
qui. Aucun nom de client, adresse email ou identifiant de classeur/dossier ne
doit donc y apparaitre en clair.

Deux protections complementaires :
- les scripts n'impriment plus ces donnees (seulement le n° de commande) ;
- filet de securite : chaque valeur confidentielle connue (valeurs de
  config.json et gmail_filters.json, nom/prenom des clients lus dans les bons
  ou les classeurs) est declaree a GitHub par la commande ``::add-mask::``.
  GitHub remplace alors toute occurrence de cette valeur par ``***`` dans la
  suite du log, meme si un message oublie de la retirer.

Hors GitHub Actions (tests, execution locale), rien n'est imprime.
"""
import os
import sys

# En dessous de cette longueur, masquer une valeur remplacerait des morceaux
# de mots ordinaires partout dans le log (ex. un prenom de 2 lettres).
LONGUEUR_MIN = 4

_deja_masques = set()


def _sur_github_actions():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def masquer(*valeurs):
    """Declare chaque valeur (et chaque mot d'une valeur composee, ex.
    "DUPONT Jean") comme secret pour le log GitHub Actions."""
    if not _sur_github_actions():
        return
    for valeur in valeurs:
        if valeur is None:
            continue
        texte = str(valeur).strip()
        candidats = {texte, texte.upper(), texte.lower(), texte.title()}
        for mot in texte.replace("-", " ").split():
            candidats.update({mot, mot.upper(), mot.lower(), mot.title()})
        for c in candidats:
            if len(c) < LONGUEUR_MIN or "\n" in c or c in _deja_masques:
                continue
            _deja_masques.add(c)
            print(f"::add-mask::{c}", flush=True)
    sys.stdout.flush()


def masquer_config(cfg):
    """Masque toutes les valeurs texte d'un dictionnaire de configuration
    (config.json, gmail_filters.json...), listes et sous-dictionnaires
    compris. Les valeurs composees (ex. un sujet d'email) ne sont pas
    decoupees en mots : seule la valeur entiere est masquee."""
    if not _sur_github_actions():
        return cfg
    pile = [cfg]
    while pile:
        v = pile.pop()
        if isinstance(v, dict):
            pile.extend(v.values())
        elif isinstance(v, (list, tuple)):
            pile.extend(v)
        elif isinstance(v, (str, int)) and not isinstance(v, bool):
            texte = str(v).strip()
            # Un petit nombre (annee, seuil...) n'est pas confidentiel et
            # masquerait ce nombre partout dans le log.
            if isinstance(v, int) and len(texte) < 5:
                continue
            if len(texte) >= LONGUEUR_MIN and "\n" not in texte and texte not in _deja_masques:
                _deja_masques.add(texte)
                print(f"::add-mask::{texte}", flush=True)
    return cfg


def cle_obligatoire(cfg, cle):
    """Valeur non vide de ``cle`` dans config.json, ou arret explicite.
    Remplace les anciennes valeurs par defaut ecrites en dur dans le code
    (identifiants de classeurs visibles de tous dans un depot public)."""
    valeur = str(cfg.get(cle, "") or "").strip()
    if not valeur:
        print(f"ERREUR : cle « {cle} » absente ou vide dans config.json (Drive).")
        sys.exit(1)
    return valeur
