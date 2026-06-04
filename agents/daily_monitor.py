#!/usr/bin/env python3
"""
Surveillance quotidienne du workflow aut_prep.
Vérifie les 24 dernières heures, analyse les échecs via Claude, applique des corrections.
"""

import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = os.environ.get("REPO", "eNbMobile/auto_prepa")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
WORKFLOW_NAME = "aut_prep"
WINDOW_HEURES = 24
REPO_PATH = Path(os.environ.get("REPO_PATH", Path(__file__).parent.parent))


# ──────────────────────────────────────────────────────────────────
# GitHub API
# ──────────────────────────────────────────────────────────────────

def _gh(path, method="GET", data=None, accept="application/vnd.github.v3+json"):
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": accept,
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GH API {method} {path} → {e.code}: {e.read().decode()[:300]}") from e


def lister_tous_les_runs_24h():
    """Pagine l'API GitHub jusqu'à couvrir les WINDOW_HEURES dernières heures."""
    limite = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HEURES)
    runs = []
    page = 1
    while True:
        params = urllib.parse.urlencode({"per_page": 100, "page": page})
        data = _gh(f"/repos/{REPO}/actions/runs?{params}")
        batch = data.get("workflow_runs", [])
        if not batch:
            break
        # Filtrer sur le nom du workflow
        pour_nous = [r for r in batch if r.get("name") == WORKFLOW_NAME or r.get("workflow_name") == WORKFLOW_NAME]
        runs.extend(pour_nous)
        # Vérifier si on est sorti de la fenêtre 24h
        plus_ancien = batch[-1].get("created_at", "")
        if plus_ancien:
            ts = datetime.fromisoformat(plus_ancien.replace("Z", "+00:00"))
            if ts < limite:
                break
        # Si la page est incomplète, c'est la dernière
        if len(batch) < 100:
            break
        page += 1

    # Filtrer strictement sur la fenêtre
    dans_fenetre = []
    for r in runs:
        ts_str = r.get("created_at", "")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= limite:
                dans_fenetre.append(r)
    return dans_fenetre


def telecharger_logs(run_id):
    """Télécharge et extrait les logs texte d'un run (tronqué à 20 000 caractères)."""
    try:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/logs",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                parts = []
                for name in sorted(z.namelist()):
                    try:
                        parts.append(f"=== {name} ===\n" + z.read(name).decode("utf-8", errors="replace"))
                    except Exception:
                        pass
                texte = "\n".join(parts)
        except Exception:
            texte = raw.decode("utf-8", errors="replace")
        return texte[-20000:] if len(texte) > 20000 else texte
    except Exception as e:
        return f"(Logs indisponibles : {e})"


def _assurer_labels(labels):
    """Crée les labels s'ils n'existent pas encore sur le dépôt."""
    couleurs = {"surveillance": "0075ca", "bug": "d73a4a", "auto-fix": "e4e669"}
    for label in labels:
        try:
            _gh(f"/repos/{REPO}/labels/{urllib.parse.quote(label)}")
        except RuntimeError:
            try:
                _gh(f"/repos/{REPO}/labels", method="POST", data={
                    "name": label,
                    "color": couleurs.get(label, "ededed"),
                })
            except Exception:
                pass


def creer_issue(titre, corps, labels=None):
    labels = labels or ["surveillance"]
    _assurer_labels(labels)
    return _gh(f"/repos/{REPO}/issues", method="POST", data={
        "title": titre,
        "body": corps,
        "labels": labels,
    })


def lire_workflow():
    yml_path = REPO_PATH / ".github" / "workflows" / "auto_prepa.yml"
    if yml_path.exists():
        return yml_path.read_text(encoding="utf-8"), yml_path
    return None, None


# ──────────────────────────────────────────────────────────────────
# Analyse via Claude
# ──────────────────────────────────────────────────────────────────

def analyser_echec(run, logs, workflow_content):
    """Interroge Claude pour diagnostiquer et proposer un correctif."""
    try:
        import anthropic
    except ImportError:
        return False, None, "Package anthropic non installé."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Tu es un expert DevOps spécialisé en GitHub Actions.

Le workflow **{WORKFLOW_NAME}** du dépôt `{REPO}` a échoué.

## Contexte de l'échec
- Run ID : {run['id']}
- Heure : {run.get('created_at', 'inconnue')}
- URL : {run.get('html_url', '')}
- Conclusion : {run.get('conclusion', 'failure')}

## Contenu du workflow (`auto_prepa.yml`)
```yaml
{workflow_content}
```

## Logs (extrait final)
```
{logs}
```

## Instructions
1. Identifie la cause exacte de l'échec (ligne de log concernée).
2. Propose une correction minimale du fichier workflow YAML.
3. Si l'échec est externe (réseau, secret manquant, API tierce), indique `peut_corriger: false`.

## Format de réponse (JSON strict, rien d'autre)
{{
  "peut_corriger": true,
  "cause": "Description courte et précise de la cause",
  "explication": "Explication détaillée et correctif proposé",
  "workflow_corrige": "contenu YAML complet corrigé ou null"
}}"""

    try:
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in resp.content if b.type == "text"), "{}")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return False, None, f"Réponse non parseable : {raw[:200]}"
        result = json.loads(match.group())
        return (
            result.get("peut_corriger", False),
            result.get("workflow_corrige"),
            result.get("cause", "") + "\n\n" + result.get("explication", ""),
        )
    except Exception as e:
        return False, None, f"Erreur Claude API : {e}"


# ──────────────────────────────────────────────────────────────────
# Application des corrections
# ──────────────────────────────────────────────────────────────────

def appliquer_correction(yml_path, contenu_corrige, run_id, explication):
    """Commit et push la correction sur une branche dédiée, crée une PR."""
    branche = f"fix/aut-prep-run-{run_id}"
    try:
        # Configurer git
        subprocess.run(["git", "-C", str(REPO_PATH), "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "-C", str(REPO_PATH), "config", "user.name", "github-actions[bot]"], check=True)

        # Créer la branche depuis HEAD
        subprocess.run(["git", "-C", str(REPO_PATH), "checkout", "-b", branche], check=True, capture_output=True)

        # Écrire et committer le correctif
        yml_path.write_text(contenu_corrige, encoding="utf-8")
        subprocess.run(["git", "-C", str(REPO_PATH), "add", str(yml_path)], check=True)
        msg = f"fix(workflow): correction auto aut_prep run #{run_id}\n\n{explication[:400]}"
        subprocess.run(["git", "-C", str(REPO_PATH), "commit", "-m", msg], check=True, capture_output=True)

        # Push
        remote_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{REPO}.git"
        subprocess.run(
            ["git", "-C", str(REPO_PATH), "push", remote_url, branche],
            check=True, capture_output=True,
        )

        # Créer la PR
        pr = _gh(f"/repos/{REPO}/pulls", method="POST", data={
            "title": f"fix(aut_prep): correction auto – run #{run_id}",
            "head": branche,
            "base": "main",
            "body": (
                f"## Correction automatique\n\n"
                f"**Run échoué :** [{run_id}](https://github.com/{REPO}/actions/runs/{run_id})\n\n"
                f"**Analyse :**\n{explication}\n\n"
                f"*Généré automatiquement par daily_monitor.py*"
            ),
            "draft": True,
        })
        pr_url = pr.get("html_url", "")
        print(f"    ✓ PR créée : {pr_url}")
        return True, pr_url
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        print(f"    ✗ Erreur git/push : {stderr[:200]}")
        # Revenir sur main
        subprocess.run(["git", "-C", str(REPO_PATH), "checkout", "main", "--force"], capture_output=True)
        return False, None
    except Exception as e:
        print(f"    ✗ Erreur inattendue : {e}")
        return False, None


# ──────────────────────────────────────────────────────────────────
# Rapport
# ──────────────────────────────────────────────────────────────────

def generer_rapport(runs, details_echecs):
    maintenant = datetime.now(timezone.utc)
    limite = maintenant - timedelta(hours=WINDOW_HEURES)

    succes = [r for r in runs if r.get("conclusion") == "success"]
    echecs = [r for r in runs if r.get("conclusion") not in ("success", None)]
    en_cours = [r for r in runs if r.get("conclusion") is None]

    lignes = [
        f"## Rapport de surveillance — {maintenant.strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"**Fenêtre analysée :** {limite.strftime('%Y-%m-%d %H:%M UTC')} → {maintenant.strftime('%H:%M UTC')}",
        f"",
        f"### Résumé",
        f"| Statut | Nombre |",
        f"|--------|--------|",
        f"| ✅ Succès | {len(succes)} |",
        f"| ❌ Échecs | {len(echecs)} |",
        f"| ⏳ En cours | {len(en_cours)} |",
        f"| **Total** | **{len(runs)}** |",
        f"",
    ]

    if not echecs:
        lignes += [
            f"### Résultat",
            f"**Tout fonctionne correctement.** Aucun échec détecté sur les {WINDOW_HEURES} dernières heures.",
        ]
    else:
        lignes += [f"### Détail des échecs", ""]
        for run in echecs:
            run_id = run["id"]
            ts = run.get("created_at", "")
            url = run.get("html_url", f"https://github.com/{REPO}/actions/runs/{run_id}")
            conclusion = run.get("conclusion", "failure")

            lignes.append(f"#### Run #{run_id} — {ts} — `{conclusion}`")
            lignes.append(f"[Voir le run]({url})")

            if run_id in details_echecs:
                d = details_echecs[run_id]
                lignes.append(f"")
                lignes.append(f"**Analyse :** {d['analyse'][:600]}")
                if d.get("pr_url"):
                    lignes.append(f"")
                    lignes.append(f"**Correctif appliqué :** PR → {d['pr_url']}")
                elif d.get("peut_corriger") is False:
                    lignes.append(f"")
                    lignes.append(f"**Correction impossible** (erreur externe ou manque de contexte)")
            lignes.append("")

    lignes += [
        "",
        "---",
        "*Généré automatiquement par `daily_monitor.py`*",
    ]
    return "\n".join(lignes)


# ──────────────────────────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────────────────────────

def main():
    print(f"=== Surveillance quotidienne aut_prep — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} ===")

    if not GITHUB_TOKEN:
        print("ERREUR : GITHUB_TOKEN non défini")
        sys.exit(1)

    # 1. Récupérer tous les runs des 24 dernières heures
    print(f"\n1. Récupération des runs des {WINDOW_HEURES} dernières heures...")
    runs = lister_tous_les_runs_24h()
    print(f"   → {len(runs)} run(s) trouvé(s)")

    succes = [r for r in runs if r.get("conclusion") == "success"]
    echecs = [r for r in runs if r.get("conclusion") not in ("success", None)]
    print(f"   → {len(succes)} succès, {len(echecs)} échec(s)")

    # 2. Analyser chaque échec
    details_echecs = {}
    if echecs and ANTHROPIC_API_KEY:
        print(f"\n2. Analyse des {len(echecs)} échec(s) via Claude...")
        workflow_content, yml_path = lire_workflow()

        for run in echecs:
            run_id = run["id"]
            print(f"\n   → Run #{run_id} ({run.get('created_at', '')})")

            logs = telecharger_logs(run_id)
            print(f"      Logs récupérés ({len(logs)} caractères)")

            if workflow_content:
                peut_corriger, contenu_corrige, analyse = analyser_echec(run, logs, workflow_content)
                print(f"      Cause : {analyse[:120]}")

                pr_url = None
                if peut_corriger and contenu_corrige:
                    print(f"      Application de la correction...")
                    ok, pr_url = appliquer_correction(yml_path, contenu_corrige, run_id, analyse)
                    if ok:
                        workflow_content = contenu_corrige  # Mettre à jour pour les suivants

                details_echecs[run_id] = {
                    "analyse": analyse,
                    "peut_corriger": peut_corriger,
                    "pr_url": pr_url,
                }
            else:
                details_echecs[run_id] = {
                    "analyse": "Fichier workflow introuvable.",
                    "peut_corriger": False,
                    "pr_url": None,
                }
    elif echecs and not ANTHROPIC_API_KEY:
        print(f"\n2. ANTHROPIC_API_KEY non défini — analyse Claude ignorée")
        for run in echecs:
            details_echecs[run["id"]] = {
                "analyse": "Analyse impossible (ANTHROPIC_API_KEY manquant).",
                "peut_corriger": False,
                "pr_url": None,
            }

    # 3. Générer le rapport
    print(f"\n3. Génération du rapport...")
    rapport = generer_rapport(runs, details_echecs)
    print(rapport)

    # 4. Créer une issue GitHub si échecs ou toujours (résumé journalier)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if echecs:
        titre = f"[Surveillance] ❌ {len(echecs)} échec(s) aut_prep — {date_str}"
        labels = ["surveillance", "bug"]
    else:
        titre = f"[Surveillance] ✅ Tout OK aut_prep — {date_str}"
        labels = ["surveillance"]

    try:
        issue = creer_issue(titre, rapport, labels)
        print(f"\n4. Issue créée : {issue.get('html_url', '')}")
    except Exception as e:
        print(f"\n4. Impossible de créer l'issue : {e}")

    print("\n=== Surveillance terminée ===")
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
