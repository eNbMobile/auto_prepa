#!/usr/bin/env python3
"""
Agent 3 - Surveillance et correction automatique des workflows GitHub
Surveille eNbMobile/auto_prepa, détecte les échecs du workflow 'aut_prep',
et utilise l'API Claude pour proposer + appliquer des corrections.
"""

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

REPO = os.environ.get("GITHUB_REPO", "eNbMobile/auto_prepa")
WORKFLOW_NAME = os.environ.get("WORKFLOW_NAME", "aut_prep")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REPO_PATH = Path(os.environ.get("REPO_PATH", Path(__file__).parent.parent))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "120"))
MAX_FIXES_PER_RUN = int(os.environ.get("MAX_FIXES_PER_RUN", "3"))


# ──────────────────────────────────────────────────────────────────
# GitHub API helpers
# ──────────────────────────────────────────────────────────────────

def _gh_request(path, method="GET", data=None):
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN non défini")
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API {method} {path} → {e.code}: {e.read().decode()}") from e


def get_recent_failed_runs(since_minutes=30):
    """Récupère les runs échoués du workflow cible dans les dernières N minutes."""
    since = (datetime.utcnow() - timedelta(minutes=since_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = urllib.parse.urlencode({
        "status": "failure",
        "created": f">={since}",
        "per_page": "10",
    })
    data = _gh_request(f"/repos/{REPO}/actions/runs?{params}")
    runs = data.get("workflow_runs", [])
    return [r for r in runs if r.get("name") == WORKFLOW_NAME or r.get("workflow_name") == WORKFLOW_NAME]


def get_run_logs(run_id):
    """Télécharge les logs d'un run (texte brut, tronqué à 15 000 caractères)."""
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
        # Les logs sont un ZIP ; on extrait le texte brut en cherchant les lignes d'erreur
        text = _extract_text_from_zip(raw)
        return text[-15000:] if len(text) > 15000 else text
    except Exception as e:
        return f"(Impossible de récupérer les logs : {e})"


def _extract_text_from_zip(data):
    """Extrait le texte des logs depuis un ZIP GitHub (format simple)."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            parts = []
            for name in sorted(z.namelist()):
                try:
                    parts.append(f"=== {name} ===\n" + z.read(name).decode("utf-8", errors="replace"))
                except Exception:
                    pass
            return "\n".join(parts)
    except Exception:
        return data.decode("utf-8", errors="replace")


def get_workflow_file_content(workflow_name):
    """Lit le contenu du fichier workflow depuis le dépôt local."""
    yml_path = REPO_PATH / ".github" / "workflows" / f"{workflow_name}.yml"
    if yml_path.exists():
        return yml_path.read_text(encoding="utf-8"), yml_path
    # Chercher par nom
    workflows_dir = REPO_PATH / ".github" / "workflows"
    for f in workflows_dir.glob("*.yml"):
        content = f.read_text(encoding="utf-8")
        if f"name: {workflow_name}" in content:
            return content, f
    return None, None


def create_github_issue(title, body):
    """Crée une issue GitHub pour signaler une correction."""
    return _gh_request(f"/repos/{REPO}/issues", method="POST", data={
        "title": title,
        "body": body,
        "labels": ["bug", "auto-fix"],
    })


# ──────────────────────────────────────────────────────────────────
# Analyse et correction via Claude
# ──────────────────────────────────────────────────────────────────

def analyser_et_corriger(run, workflow_content, logs):
    """
    Envoie le contexte à Claude et récupère une proposition de correction.
    Retourne (corrige: bool, nouveau_contenu: str, explication: str)
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Tu es un expert DevOps spécialisé en GitHub Actions.

Le workflow GitHub Actions nommé **{WORKFLOW_NAME}** du dépôt `{REPO}` a échoué.

## Informations sur l'échec
- Run ID : {run['id']}
- Heure : {run.get('created_at', 'inconnue')}
- URL : {run.get('html_url', '')}

## Contenu actuel du workflow (`auto_prepa.yml`)
```yaml
{workflow_content}
```

## Logs d'erreur (extrait)
```
{logs}
```

## Ta mission
1. Identifie la cause exacte de l'échec en analysant les logs.
2. Propose une correction minimale du fichier workflow.
3. Si aucune correction n'est possible (erreur externe, secret manquant, problème réseau), dis-le clairement.

## Format de réponse requis (JSON strict)
Réponds UNIQUEMENT avec un objet JSON de cette forme exacte :
{{
  "peut_corriger": true,
  "explication": "Description courte de la cause et de la correction",
  "workflow_corrige": "contenu YAML complet corrigé (ou null si pas de correction)"
}}
"""

    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in response.content if b.type == "text"), "{}")
        # Extraire le JSON même s'il y a du texte autour
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return False, None, f"Réponse Claude non parseable : {raw[:200]}"
        result = json.loads(match.group())
        peut_corriger = result.get("peut_corriger", False)
        explication = result.get("explication", "")
        contenu_corrige = result.get("workflow_corrige")
        return peut_corriger, contenu_corrige, explication
    except Exception as e:
        return False, None, f"Erreur Claude API : {e}"


def appliquer_correction(yml_path, nouveau_contenu, run, explication):
    """Applique la correction, commit et push."""
    try:
        yml_path.write_text(nouveau_contenu, encoding="utf-8")
        msg = (
            f"fix(workflow): correction automatique {WORKFLOW_NAME} "
            f"[run {run['id']}]\n\n{explication[:300]}"
        )
        subprocess.run(["git", "-C", str(REPO_PATH), "add", str(yml_path)], check=True)
        subprocess.run(
            ["git", "-C", str(REPO_PATH), "commit", "-m", msg],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(REPO_PATH), "push"],
            check=True, capture_output=True
        )
        print(f"    ✓ Correction commitée et poussée.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"    ✗ Erreur git : {e.stderr.decode() if e.stderr else e}")
        # Annuler les changements
        subprocess.run(["git", "-C", str(REPO_PATH), "checkout", "--", str(yml_path)])
        return False


# ──────────────────────────────────────────────────────────────────
# Suivi des runs déjà traités
# ──────────────────────────────────────────────────────────────────

_TRAITES_FILE = Path(os.path.expanduser("~/.agent3_runs_traites.json"))


def _charger_traites():
    if _TRAITES_FILE.exists():
        try:
            return set(json.loads(_TRAITES_FILE.read_text()))
        except Exception:
            pass
    return set()


def _sauvegarder_traites(ids):
    # Garder seulement les 500 derniers
    recent = sorted(ids)[-500:]
    _TRAITES_FILE.write_text(json.dumps(recent))


# ──────────────────────────────────────────────────────────────────
# Boucle principale
# ──────────────────────────────────────────────────────────────────

def _verifier_config():
    manquants = []
    if not GITHUB_TOKEN:
        manquants.append("GITHUB_TOKEN")
    if not ANTHROPIC_API_KEY:
        manquants.append("ANTHROPIC_API_KEY")
    if manquants:
        raise RuntimeError(f"Variables d'environnement manquantes : {', '.join(manquants)}")
    if not REPO_PATH.exists():
        raise RuntimeError(f"REPO_PATH introuvable : {REPO_PATH}")


def scan_et_corriger():
    """Un cycle de surveillance et correction."""
    runs_traites = _charger_traites()
    runs_echoues = get_recent_failed_runs()

    nouveaux = [r for r in runs_echoues if str(r["id"]) not in runs_traites]
    if not nouveaux:
        return 0

    print(f"  {len(nouveaux)} run(s) échoué(s) non traité(s)")
    workflow_content, yml_path = get_workflow_file_content(WORKFLOW_NAME)

    corrections = 0
    for run in nouveaux[:MAX_FIXES_PER_RUN]:
        run_id = str(run["id"])
        print(f"\n  → Run #{run_id} ({run.get('created_at', '')})")

        if workflow_content is None:
            print("    Fichier workflow introuvable — impossible de corriger.")
            runs_traites.add(run_id)
            continue

        logs = get_run_logs(run["id"])
        peut_corriger, contenu_corrige, explication = analyser_et_corriger(run, workflow_content, logs)
        print(f"    Analyse : {explication[:120]}")

        if peut_corriger and contenu_corrige:
            ok = appliquer_correction(yml_path, contenu_corrige, run, explication)
            if ok:
                corrections += 1
                # Mettre à jour pour les itérations suivantes
                workflow_content = contenu_corrige
        else:
            # Créer une issue si correction impossible
            try:
                issue = create_github_issue(
                    f"[aut_prep] Échec non corrigeable – run #{run_id}",
                    f"**Cause :** {explication}\n\n**Run :** {run.get('html_url', run_id)}\n\n"
                    f"*Généré automatiquement par agent3_github_watcher*",
                )
                print(f"    Issue créée : #{issue.get('number')}")
            except Exception as e:
                print(f"    (Impossible de créer l'issue : {e})")

        runs_traites.add(run_id)

    _sauvegarder_traites(runs_traites)
    return corrections


def main():
    print(f"=== Agent 3 - GitHub Watcher ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"  Dépôt : {REPO}  |  Workflow : {WORKFLOW_NAME}  |  Intervalle : {POLL_INTERVAL}s")

    try:
        _verifier_config()
    except RuntimeError as e:
        print(f"ERREUR CONFIG : {e}")
        print("\nVariables requises :")
        print("  GITHUB_TOKEN=<token>")
        print("  ANTHROPIC_API_KEY=<clé>")
        print("  REPO_PATH=<chemin vers le dépôt local>  (optionnel)")
        return

    try:
        while True:
            debut = time.time()
            try:
                n = scan_et_corriger()
                if n:
                    print(f"  {n} correction(s) appliquée(s).")
                else:
                    print(f"  Aucun nouveau problème.  ({datetime.now().strftime('%H:%M')})")
            except Exception as e:
                print(f"  Erreur scan : {e}")
            time.sleep(max(0, POLL_INTERVAL - (time.time() - debut)))
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
