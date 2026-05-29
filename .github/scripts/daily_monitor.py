#!/usr/bin/env python3
"""
Surveillance quotidienne du workflow aut_prep.
Vérifie les 24 dernières heures, détecte les échecs, analyse avec Claude,
applique les corrections possibles et crée un rapport via GitHub Issues.
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
from datetime import datetime, timedelta, timezone

REPO          = os.environ.get("REPO", "eNbMobile/auto_prepa")
GH_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
WORKFLOW_NAME = "aut_prep"
WORKFLOW_FILE = ".github/workflows/auto_prepa.yml"
AUTO_FIX      = os.environ.get("AUTO_FIX", "true").lower() == "true"


# ─── GitHub API ───────────────────────────────────────────────────────────────

def gh(path, method="GET", data=None):
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {method} {path} → {e.code}: {e.read().decode()[:300]}")


def ensure_labels():
    needed = [
        {"name": "monitoring",        "color": "0075ca", "description": "Surveillance automatique"},
        {"name": "rapport-quotidien", "color": "e4e669", "description": "Rapport journalier aut_prep"},
        {"name": "auto-fix",          "color": "d93f0b", "description": "Correction automatique appliquée"},
    ]
    try:
        existing = {l["name"] for l in gh(f"/repos/{REPO}/labels")}
        for lbl in needed:
            if lbl["name"] not in existing:
                gh(f"/repos/{REPO}/labels", method="POST", data=lbl)
    except Exception:
        pass  # Labels are cosmetic, don't block execution


def get_workflow_id():
    data = gh(f"/repos/{REPO}/actions/workflows")
    for wf in data.get("workflows", []):
        if wf.get("name") == WORKFLOW_NAME:
            return wf["id"]
    return None


def get_runs(wf_id, since_hours=24):
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = urllib.parse.urlencode({"per_page": "100", "created": f">={since}"})
    data = gh(f"/repos/{REPO}/actions/workflows/{wf_id}/runs?{params}")
    return data.get("workflow_runs", [])


def get_logs(run_id):
    """Downloads run logs (ZIP) and returns truncated plain text."""
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/logs",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            parts = []
            for name in sorted(z.namelist()):
                try:
                    content = z.read(name).decode("utf-8", errors="replace")
                    parts.append(f"=== {name} ===\n{content}")
                except Exception:
                    pass
            text = "\n".join(parts)
        return text[-10000:] if len(text) > 10000 else text
    except Exception as e:
        return f"(Impossible de récupérer les logs : {e})"


def create_issue(title, body, labels=None):
    data = {"title": title, "body": body}
    if labels:
        data["labels"] = labels
    try:
        return gh(f"/repos/{REPO}/issues", method="POST", data=data)
    except Exception:
        data.pop("labels", None)
        return gh(f"/repos/{REPO}/issues", method="POST", data=data)


# ─── Claude Analysis ──────────────────────────────────────────────────────────

def analyze_with_claude(failures, workflow_content):
    """
    Sends failure context to Claude for analysis and fix suggestion.
    Returns dict with keys: analyse_globale, corrections_possibles,
                            workflow_corrige, rapport
    """
    failures_text = "\n\n".join(
        f"### Run #{r['id']} ({r.get('created_at', '')[:19]})\n"
        f"URL : {r.get('html_url', '')}\n"
        f"**Logs (extrait) :**\n```\n{r.get('logs', '(non disponible)')[-4000:]}\n```"
        for r in failures
    )

    prompt = f"""Tu es un expert DevOps spécialisé en GitHub Actions et Python.

Le workflow GitHub Actions **{WORKFLOW_NAME}** du dépôt `{REPO}` a eu des échecs dans les dernières 24 heures.

## Contenu actuel du workflow (`{WORKFLOW_FILE}`)
```yaml
{workflow_content}
```

## Runs échoués avec leurs logs
{failures_text}

## Mission
1. Identifie la cause exacte de chaque échec en analysant les logs.
2. Si la cause est corrigeable dans le fichier workflow YAML, propose une correction minimale.
3. Si la cause est externe (secret manquant, service tiers en panne, réseau, etc.), explique-le clairement.
4. Rédige un rapport complet en markdown pour une GitHub Issue.

## Format de réponse (JSON strict, sans texte autour)
{{
  "analyse_globale": "Résumé en 2-3 phrases de la situation",
  "corrections_possibles": true,
  "workflow_corrige": "contenu YAML complet corrigé (ou null si aucun changement nécessaire)",
  "rapport": "Rapport détaillé en markdown (cause, impact, correction appliquée ou recommandations)"
}}
"""

    req_data = json.dumps({
        "model": "claude-opus-4-8",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_data,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read())
        raw = resp["content"][0]["text"]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"  Erreur Claude API : {e}")
    return None


# ─── Fix Application ──────────────────────────────────────────────────────────

def apply_fix(new_content, explanation):
    """Writes, commits and pushes the corrected workflow file."""
    with open(WORKFLOW_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    subprocess.run(["git", "config", "user.email", "monitor-bot@auto-prepa.noreply"], check=True)
    subprocess.run(["git", "config", "user.name", "Auto-Prepa Monitor"], check=True)
    subprocess.run(["git", "add", WORKFLOW_FILE], check=True)

    msg = (
        f"fix(workflow): correction automatique {WORKFLOW_NAME}\n\n"
        f"{explanation[:400]}"
    )
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if "nothing to commit" in (result.stdout + result.stderr):
            return False, "Aucun changement à commettre (workflow déjà à jour ?)"
        return False, result.stderr.strip()

    push = subprocess.run(["git", "push"], capture_output=True, text=True)
    if push.returncode != 0:
        return False, push.stderr.strip()
    return True, "Correction commitée et poussée avec succès."


# ─── Report Builder ───────────────────────────────────────────────────────────

def build_report(today, runs, failures, successes, skipped, cancelled, in_progress,
                 analysis, fix_ok, fix_msg):
    total = len(runs)

    # Stats table
    stats = (
        f"| Statut | Nombre |\n|--------|--------|\n"
        f"| ✅ Succès | {len(successes)} |\n"
        f"| ❌ Échec | {len(failures)} |\n"
        f"| ⏭️ Ignoré (pas de mail) | {len(skipped)} |\n"
        f"| ✕ Annulé | {len(cancelled)} |\n"
        f"| 🔄 En cours / En attente | {len(in_progress)} |\n"
        f"| **Total** | **{total}** |"
    )

    # Claude analysis section
    claude_section = ""
    if analysis:
        claude_section = (
            f"\n\n## 🤖 Analyse Claude\n\n"
            f"{analysis.get('rapport') or analysis.get('analyse_globale', '(analyse non disponible)')}"
        )

    # Fix section
    fix_section = ""
    if fix_ok:
        fix_section = (
            f"\n\n## 🔧 Correction appliquée automatiquement\n\n"
            f"> {fix_msg}\n\n"
            f"Le fichier `{WORKFLOW_FILE}` a été corrigé et poussé. "
            f"La prochaine exécution utilisera la version corrigée."
        )
    elif fix_msg:
        fix_section = f"\n\n## ⚠️ Tentative de correction\n\n> {fix_msg}"

    # Failure details (max 5)
    failure_details = ""
    for r in failures[:5]:
        logs_excerpt = (r.get("logs") or "(logs non disponibles)")[-3000:]
        failure_details += (
            f"\n### Run #{r['id']} — {r.get('created_at', '')[:19]}\n"
            f"🔗 {r.get('html_url', '')}\n\n"
            f"<details><summary>Logs (extrait)</summary>\n\n"
            f"```\n{logs_excerpt}\n```\n\n</details>\n"
        )
    if len(failures) > 5:
        failure_details += f"\n*… et {len(failures) - 5} autre(s) échec(s) non détaillés.*\n"

    return (
        f"## Rapport quotidien — {today}\n\n"
        f"⚠️ **{len(failures)} échec(s)** détecté(s) sur les dernières 24 heures.\n\n"
        f"{stats}"
        f"{claude_section}"
        f"\n\n## Détails des échecs\n{failure_details}"
        f"{fix_section}"
        f"\n\n---\n*Généré automatiquement par `daily_monitor.yml`*"
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Surveillance quotidienne {WORKFLOW_NAME} — {today} ===")

    if not GH_TOKEN:
        print("ERREUR : GITHUB_TOKEN non défini.")
        sys.exit(1)

    ensure_labels()

    # Find workflow
    wf_id = get_workflow_id()
    if not wf_id:
        print(f"Workflow '{WORKFLOW_NAME}' introuvable dans le dépôt.")
        sys.exit(1)
    print(f"  Workflow ID : {wf_id}")

    # Fetch last 24h runs
    runs = get_runs(wf_id, since_hours=24)
    total = len(runs)
    print(f"  {total} exécution(s) trouvée(s) dans les 24 dernières heures.")

    if total == 0:
        body = (
            f"## Rapport quotidien — {today}\n\n"
            f"⚠️ **Aucune exécution** du workflow `{WORKFLOW_NAME}` détectée dans les 24 dernières heures.\n\n"
            f"### Points à vérifier\n"
            f"- Le déclencheur `schedule` est-il actif ?\n"
            f"- Le workflow a-t-il été désactivé dans GitHub Actions ?\n"
            f"- Le planificateur GitHub est-il en retard ? (possible lors de forte charge)\n\n"
            f"---\n*Généré automatiquement par `daily_monitor.yml`*"
        )
        issue = create_issue(
            f"[{today}] aut_prep : ⚠️ Aucune exécution détectée",
            body,
            labels=["monitoring", "rapport-quotidien"],
        )
        print(f"  Issue créée : #{issue.get('number')}")
        return

    # Categorize runs
    def by_conclusion(c):
        return [r for r in runs if r.get("conclusion") == c]

    successes   = by_conclusion("success")
    failures    = by_conclusion("failure")
    skipped     = by_conclusion("skipped")
    cancelled   = by_conclusion("cancelled")
    in_progress = [r for r in runs if r.get("status") in ("in_progress", "queued")]

    print(f"  ✅ {len(successes)}  ❌ {len(failures)}  ⏭️ {len(skipped)}  ✕ {len(cancelled)}  🔄 {len(in_progress)}")

    # No failures → success report
    if not failures:
        body = (
            f"## Rapport quotidien — {today}\n\n"
            f"✅ **Tout s'est bien passé !** Aucun échec sur les 24 dernières heures.\n\n"
            f"| Statut | Nombre |\n|--------|--------|\n"
            f"| ✅ Succès | {len(successes)} |\n"
            f"| ⏭️ Ignoré (pas de mail) | {len(skipped)} |\n"
            f"| ✕ Annulé | {len(cancelled)} |\n"
            f"| 🔄 En cours | {len(in_progress)} |\n"
            f"| **Total** | **{total}** |\n\n"
            f"---\n*Généré automatiquement par `daily_monitor.yml`*"
        )
        issue = create_issue(
            f"[{today}] aut_prep : ✅ RAS — {total} exécution(s)",
            body,
            labels=["monitoring", "rapport-quotidien"],
        )
        print(f"  Issue créée : #{issue.get('number')} — {issue.get('html_url', '')}")
        return

    # Fetch logs for each failure (max 5)
    print(f"\n  {len(failures)} échec(s) — récupération des logs...")
    for r in failures[:5]:
        print(f"    Logs run #{r['id']}...")
        r["logs"] = get_logs(r["id"])

    # Read current workflow file
    try:
        with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
            workflow_content = f.read()
    except Exception:
        workflow_content = "(fichier non trouvé localement)"

    # Claude analysis
    analysis = None
    if ANTHROPIC_KEY:
        print("  Analyse Claude en cours...")
        analysis = analyze_with_claude(failures[:5], workflow_content)
        if analysis:
            print(f"  → {analysis.get('analyse_globale', '')[:100]}")
    else:
        print("  ANTHROPIC_API_KEY absent — analyse Claude ignorée.")

    # Apply fix if available and AUTO_FIX enabled
    fix_ok, fix_msg = False, ""
    if (
        AUTO_FIX
        and analysis
        and analysis.get("corrections_possibles")
        and analysis.get("workflow_corrige")
    ):
        print("  Application de la correction...")
        fix_ok, fix_msg = apply_fix(
            analysis["workflow_corrige"],
            analysis.get("analyse_globale", "Correction automatique"),
        )
        print(f"  → {'OK' if fix_ok else 'ÉCHEC'} : {fix_msg}")

    # Build and post report
    labels = ["monitoring", "rapport-quotidien"]
    if fix_ok:
        labels.append("auto-fix")

    body = build_report(
        today, runs, failures, successes, skipped, cancelled, in_progress,
        analysis, fix_ok, fix_msg,
    )
    title = f"[{today}] aut_prep : ❌ {len(failures)} échec(s) sur {total} exécution(s)"
    issue = create_issue(title, body, labels=labels)
    print(f"\n  Issue créée : #{issue.get('number')} — {issue.get('html_url', '')}")

    # Exit with error code if there were uncorrected failures
    if failures and not fix_ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
