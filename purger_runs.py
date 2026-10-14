#!/usr/bin/env python3
"""Supprime les anciens runs GitHub Actions dont les logs peuvent contenir des
données de clients (noms, prénoms, emails).

Le dépôt est public, ses logs aussi. Depuis le merge de la PR #273
(14/10/2026 08:29 UTC), les scripts n'affichent plus que le n° de commande ;
les runs d'avant, eux, pouvaient afficher nom et prénom. Ce script supprime
(run + logs + artefacts) tous les runs créés avant AVANT, sauf ceux des
workflows qui ne manipulent aucune donnée client (WORKFLOWS_CONSERVES).

GitHub ne renvoie au plus que 1 000 runs par recherche : la recherche est donc
découpée jour par jour (puis heure par heure si un jour dépasse 1 000 runs).
La limite de l'API (5 000 requêtes/heure avec un token personnel) est
respectée : le script attend la remise à zéro quand il s'en approche, et
s'arrête proprement avant la limite de durée du job (le workflow se relance
alors tout seul). Relancer le script est sans risque : il ne fait que
supprimer ce qui reste.

Usage : purger_runs.py [--simulation]
Variables : GH_TOKEN (token avec droit Actions en écriture), GITHUB_REPOSITORY,
            AVANT (ISO 8601, défaut 2026-10-14T08:29:38Z), DUREE_MAX_MIN.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEPOT = os.environ.get("GITHUB_REPOSITORY", "eNbMobile/auto_prepa")
AVANT = datetime.fromisoformat(os.environ.get("AVANT", "2026-10-14T08:29:38+00:00").replace("Z", "+00:00"))
DEBUT = datetime(2026, 5, 1, tzinfo=timezone.utc)
DUREE_MAX = timedelta(minutes=int(os.environ.get("DUREE_MAX_MIN", "330")))

# Workflows dont les logs ne contiennent aucune donnée client : leur
# historique est conservé.
WORKFLOWS_CONSERVES = {
    "Contrôle Stocks", "Générer Ventes", "Analyse Mensuelle", "collecte_ean",
    "Cumul Ventes Semaine", "Différence Stocks", "RenseigneCA", "CreerCADriveAnnee",
    "Cumul Contrôle Stocks", "Deployer tableau de bord Cloudflare",
    "Comparer moteurs de prepa", "Adresses inconnues", "Gmail watch",
    "Classement Paniers", "Purger anciens runs",
}

_debut_execution = datetime.now(timezone.utc)


def api(methode, chemin):
    """Appel à l'API GitHub ; attend si la limite de requêtes approche.

    Marge de 500 requêtes : le token est partagé avec aut_prep, qui doit
    pouvoir continuer à appeler l'API pendant la purge."""
    req = urllib.request.Request(
        f"https://api.github.com{chemin}", method=methode,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "auto-prepa-purge"})
    for tentative in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as rep:
                restant = int(rep.headers.get("X-RateLimit-Remaining", "1000"))
                if restant < 500:
                    attente = max(0, int(rep.headers.get("X-RateLimit-Reset", "0")) - time.time()) + 5
                    print(f"  Limite API proche : pause de {int(attente)} s.", flush=True)
                    time.sleep(attente)
                corps = rep.read()
                return json.loads(corps) if corps else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # déjà supprimé
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                attente = (max(0, int(reset) - time.time()) + 5) if reset else 60 * (tentative + 1)
                print(f"  HTTP {e.code} (limite) : pause de {int(attente)} s.", flush=True)
                time.sleep(attente)
                continue
            if e.code >= 500:
                time.sleep(10 * (tentative + 1))
                continue
            raise
    raise RuntimeError(f"Échec répété : {methode} {chemin}")


def runs_entre(debut, fin):
    """(total, runs) des runs créés dans [debut, fin[."""
    plage = f"{debut.strftime('%Y-%m-%dT%H:%M:%SZ')}..{(fin - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    runs, page, total = [], 1, 0
    while True:
        rep = api("GET", f"/repos/{DEPOT}/actions/runs?per_page=100&page={page}&created={plage}")
        total = rep.get("total_count", 0)
        lot = rep.get("workflow_runs", [])
        runs += lot
        if len(lot) < 100 or len(runs) >= 1000:
            return total, runs
        page += 1


def compter(debut, fin):
    plage = f"{debut.strftime('%Y-%m-%dT%H:%M:%SZ')}..{(fin - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    return api("GET", f"/repos/{DEPOT}/actions/runs?per_page=1&created={plage}").get("total_count", 0)


def tranches(debut, fin):
    """Découpe [debut, fin[ en tranches de moins de 1 000 runs."""
    total = compter(debut, fin)
    if total == 0:
        return
    if total <= 1000 or fin - debut <= timedelta(minutes=10):
        yield runs_entre(debut, fin)[1]
        return
    milieu = debut + (fin - debut) / 2
    yield from tranches(debut, milieu)
    yield from tranches(milieu, fin)


def main():
    simulation = "--simulation" in sys.argv
    supprimes = conserves = 0
    jour = DEBUT
    while jour < AVANT:
        fin = min(jour + timedelta(days=1), AVANT)
        for runs in tranches(jour, fin):
            for run in runs:
                if run.get("name") in WORKFLOWS_CONSERVES:
                    conserves += 1
                    continue
                if not simulation:
                    api("DELETE", f"/repos/{DEPOT}/actions/runs/{run['id']}")
                supprimes += 1
                if datetime.now(timezone.utc) - _debut_execution > DUREE_MAX:
                    print(f"Durée maximale atteinte : {supprimes} run(s) supprimé(s) "
                          f"dans ce passage, reprise au prochain.")
                    _sortie(termine=False)
                    return
        print(f"{jour.strftime('%d/%m/%Y')} : {supprimes} supprimé(s) au total, "
              f"{conserves} conservé(s).", flush=True)
        jour = fin
    print(f"Terminé : {supprimes} run(s) {'à supprimer' if simulation else 'supprimé(s)'}, "
          f"{conserves} conservé(s) (workflows sans données client).")
    _sortie(termine=True)


def _sortie(termine):
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a") as fh:
            fh.write(f"termine={'true' if termine else 'false'}\n")


if __name__ == "__main__":
    main()
