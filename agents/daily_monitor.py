#!/usr/bin/env python3
"""
Monitoring quotidien du workflow aut_prep.
- Vérifie les exécutions des 24 dernières heures
- Analyse les échecs via Claude API si disponible
- Applique des corrections au workflow si possible
- Crée un rapport sous forme de GitHub Issue
"""

import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path


REPO = os.environ.get("REPO", "eNbMobile/auto_prepa")
WORKFLOW_NAME = "aut_prep"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REPO_PATH = Path(os.environ.get("REPO_PATH", Path(__file__).parent.parent))
MAX_FAILURES_TO_ANALYZE = 5


# ── GitHub API ────────────────────────────────────────────────────────────────

def gh_request(path, method="GET", data=None):
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_runs_last_24h():
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_runs = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "created": f">={since}",
            "per_page": "100",
            "page": str(page),
        })
        data = gh_request(f"/repos/{REPO}/actions/runs?{params}")
        runs = data.get("workflow_runs", [])
        if not runs:
            break
        for r in runs:
            if r.get("name") == WORKFLOW_NAME or r.get("workflow_name") == WORKFLOW_NAME:
                all_runs.append(r)
        if len(runs) < 100:
            break
        page += 1
    return all_runs


def get_run_logs(run_id):
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/logs",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            parts = []
            for name in sorted(z.namelist()):
                try:
                    parts.append(f"=== {name} ===\n" + z.read(name).decode("utf-8", errors="replace"))
                except Exception:
                    pass
            text = "\n".join(parts)
        return text[-15000:] if len(text) > 15000 else text
    except Exception as e:
        return f"(Impossible de récupérer les logs : {e})"


def ensure_label(name, color, description=""):
    try:
        gh_request(f"/repos/{REPO}/labels", method="POST", data={
            "name": name, "color": color, "description": description,
        })
    except Exception:
        pass  # label existe déjà ou erreur non bloquante


def creer_issue(title, body, labels=None):
    data = {"title": title, "body": body}
    if labels:
        data["labels"] = labels
    return gh_request(f"/repos/{REPO}/issues", method="POST", data=data)


# ── Analyse Claude ────────────────────────────────────────────────────────────

def analyser_avec_claude(run, workflow_content, logs):
    if not ANTHROPIC_API_KEY:
        return False, "ANTHROPIC_API_KEY non configuré — analyse manuelle requise", None, None
    try:
        import anthropic
    except ImportError:
        return False, "Module anthropic non disponible", None, None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Tu es un expert DevOps spécialisé en GitHub Actions.

Le workflow **{WORKFLOW_NAME}** du dépôt `{REPO}` a échoué.

## Informations
- Run ID : {run['id']}
- Heure : {run.get('created_at', 'inconnue')}
- URL : {run.get('html_url', '')}

## Fichier workflow actuel (`auto_prepa.yml`)
```yaml
{workflow_content}
```

## Logs d'erreur
```
{logs}
```

## Mission
1. Identifie la cause exacte de l'échec.
2. Si c'est un bug dans le workflow YAML, propose le fichier corrigé complet.
3. Si c'est une erreur externe (secret manquant, API indisponible, réseau), indique-le sans corriger.

Réponds UNIQUEMENT avec un JSON valide :
{{
  "peut_corriger": true/false,
  "cause": "description courte",
  "correction": "description de la correction appliquée (ou null)",
  "workflow_corrige": "YAML complet corrigé (ou null)"
}}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in response.content if b.type == "text"), "{}")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return False, f"Réponse non parseable : {raw[:200]}", None, None
        result = json.loads(match.group())
        return (
            result.get("peut_corriger", False),
            result.get("cause", "Cause inconnue"),
            result.get("correction"),
            result.get("workflow_corrige"),
        )
    except Exception as e:
        return False, f"Erreur Claude API : {e}", None, None


# ── Correction git ────────────────────────────────────────────────────────────

def appliquer_correction(nouveau_contenu, run_id, cause, correction):
    yml_path = REPO_PATH / ".github" / "workflows" / "auto_prepa.yml"
    try:
        yml_path.write_text(nouveau_contenu, encoding="utf-8")
        msg = (
            f"fix(aut_prep): correction auto run #{run_id}\n\n"
            f"Cause: {cause[:200]}\n"
            f"Fix: {(correction or '')[:200]}"
        )
        subprocess.run(["git", "add", str(yml_path)], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
        subprocess.run(["git", "push"], check=True, capture_output=True)
        return True, None
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode() if e.stderr else str(e)
        subprocess.run(["git", "checkout", "--", str(yml_path)])
        return False, err


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    print(f"=== Monitoring aut_prep — {now.strftime('%Y-%m-%d %H:%M UTC')} ===")

    if not GITHUB_TOKEN:
        print("ERREUR : GITHUB_TOKEN manquant")
        sys.exit(1)

    ensure_label("monitoring", "0075ca", "Monitoring automatique")

    # Récupérer les runs des 24 dernières heures
    runs = get_runs_last_24h()
    success_runs = [r for r in runs if r.get("conclusion") == "success"]
    failed_runs  = [r for r in runs if r.get("conclusion") == "failure"]
    skipped_runs = [r for r in runs if r.get("conclusion") == "skipped"]
    other_runs   = [r for r in runs if r.get("conclusion") not in ("success", "failure", "skipped", None)]

    print(f"Runs (24h) : {len(runs)} total | {len(success_runs)} succès | {len(failed_runs)} échecs | {len(skipped_runs)} ignorés | {len(other_runs)} autres")

    # Aucune exécution → alerte
    if len(runs) == 0:
        issue = creer_issue(
            f"[aut_prep] ⚠️ Aucune exécution détectée — {date_str}",
            f"""## Rapport de monitoring — {date_str}

⚠️ **Aucune exécution du workflow `aut_prep` n'a été détectée dans les dernières 24 heures.**

Le workflow est planifié pour s'exécuter toutes les 5 minutes. L'absence totale de runs peut indiquer :
- Le scheduler GitHub est suspendu (arrive sur les dépôts peu actifs)
- Le workflow a été désactivé manuellement
- Un problème d'infrastructure GitHub

**Action :** Aller dans Actions → aut_prep → "Run workflow" pour relancer manuellement.

*Rapport généré automatiquement par le monitoring quotidien.*""",
            ["monitoring"],
        )
        print(f"Issue créée : #{issue.get('number')}")
        return

    # Aucun échec → pas de rapport
    if not failed_runs:
        print(f"✓ Aucun échec sur {len(runs)} exécutions — pas de rapport créé.")
        return

    # Analyser les échecs
    workflow_yml = REPO_PATH / ".github" / "workflows" / "auto_prepa.yml"
    workflow_content = workflow_yml.read_text(encoding="utf-8") if workflow_yml.exists() else ""

    corrections_ok = []
    corrections_ko = []

    for run in failed_runs[:MAX_FAILURES_TO_ANALYZE]:
        run_id  = run["id"]
        run_url = run.get("html_url", f"https://github.com/{REPO}/actions/runs/{run_id}")
        run_time = run.get("created_at", "")
        print(f"\n→ Analyse run #{run_id} ({run_time})")

        logs = get_run_logs(run_id)
        peut_corriger, cause, correction, nouveau_yml = analyser_avec_claude(run, workflow_content, logs)
        print(f"  Cause : {cause[:120]}")

        if peut_corriger and nouveau_yml:
            ok, err = appliquer_correction(nouveau_yml, run_id, cause, correction)
            if ok:
                workflow_content = nouveau_yml
                corrections_ok.append({
                    "run_id": run_id, "url": run_url, "time": run_time,
                    "cause": cause, "correction": correction or "voir diff",
                })
                print("  ✓ Correction appliquée et poussée")
            else:
                corrections_ko.append({
                    "run_id": run_id, "url": run_url, "time": run_time,
                    "cause": cause, "erreur": f"Échec push git : {err}",
                })
                print(f"  ✗ Impossible d'appliquer la correction : {err}")
        else:
            corrections_ko.append({
                "run_id": run_id, "url": run_url, "time": run_time,
                "cause": cause, "erreur": "Correction automatique non applicable",
            })

    # Construire le rapport
    lines = [
        f"## Rapport de monitoring aut_prep — {date_str}",
        "",
        "| Métrique | Valeur |",
        "|----------|--------|",
        f"| Période analysée | Dernières 24h |",
        f"| Total exécutions | {len(runs)} |",
        f"| ✅ Succès | {len(success_runs)} |",
        f"| ❌ Échecs | {len(failed_runs)} |",
        f"| ⏭️ Ignorés (pas de nouveaux emails) | {len(skipped_runs)} |",
        "",
    ]

    if corrections_ok:
        lines += ["### ✅ Corrections appliquées automatiquement", ""]
        for c in corrections_ok:
            lines += [
                f"**Run #{c['run_id']}** — {c['time']} — [voir logs]({c['url']})",
                f"- **Cause :** {c['cause']}",
                f"- **Correction :** {c['correction']}",
                "",
            ]

    if corrections_ko:
        lines += ["### ❌ Échecs nécessitant une intervention manuelle", ""]
        for e in corrections_ko:
            lines += [
                f"**Run #{e['run_id']}** — {e['time']} — [voir logs]({e['url']})",
                f"- **Cause :** {e['cause']}",
                f"- **Statut :** {e['erreur']}",
                "",
            ]

    remaining = len(failed_runs) - MAX_FAILURES_TO_ANALYZE
    if remaining > 0:
        lines.append(f"*{remaining} échec(s) supplémentaire(s) non analysé(s) — voir l'onglet Actions.*")
        lines.append("")

    lines.append("*Rapport généré automatiquement par le monitoring quotidien.*")

    titre = (
        f"[aut_prep] Rapport {date_str} — "
        f"{len(failed_runs)} échec(s), {len(corrections_ok)} correction(s) auto"
    )
    issue = creer_issue(titre, "\n".join(lines), ["monitoring"])
    print(f"\nRapport : Issue #{issue.get('number')} — {issue.get('html_url', '')}")


if __name__ == "__main__":
    main()
