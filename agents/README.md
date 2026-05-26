# Agents d'automatisation

## Architecture

```
[Cloud - GitHub Actions]          [Local - machine utilisateur]
────────────────────────          ─────────────────────────────
collecte_ean.yml                  agent2_telechargement.py
  ↓ toutes les 30 min               ↓ chaque nuit
  Scan Drive BDC/MM_AAAA/JJ_MM      Lit visuels_ean.json sur Drive
  Extrait EAN-13 des PDFs           Télécharge images
  → Drive: data/visuels_ean.json    via cookies Firefox
  → Drive: data/fichiers_traites.json

                                  agent3_github_watcher.py
                                    ↓ toutes les 2 minutes
                                    Surveille runs aut_prep
                                    Analyse échecs via Claude API
                                    Corrige + push le workflow
```

## Secrets GitHub requis

| Secret | Description |
|--------|-------------|
| `GOOGLE_TOKEN_JSON` | Token OAuth2 Google (déjà présent) |
| `DRIVE_CONFIG_FOLDER_ID` | ID dossier config Drive (déjà présent) |
| `BDC_FOLDER_ID` | ID du dossier BDC racine sur Drive |
| `GH_PAT` | Token GitHub pour mise à jour des secrets |

## Agent 1 (Cloud) — `collecte_ean.yml`

Workflow GitHub Actions planifié toutes les 30 minutes.
- Scanne `BDC/MM_AAAA/JJ_MM` sur Drive
- Extrait les EAN-13 valides des PDFs `BonDeCommande_*.pdf`
- Stocke sur Drive : `DRIVE_CONFIG_FOLDER_ID/data/visuels_ean.json`

**Déclenchement manuel :**
```
GitHub → Actions → collecte_ean → Run workflow
```

**Secret supplémentaire à ajouter :**
```
BDC_FOLDER_ID = <ID Drive du dossier BDC racine>
```

## Agent 2 (Local) — `agent2_telechargement.py`

Lit `data/visuels_ean.json` depuis Drive, télécharge les images

```bash
pip install -r agents/requirements_agents.txt

DRIVE_CONFIG_FOLDER_ID=<id> \
VISUELS_DIR=~/visuels \
python3 agents/agent2_telechargement.py
```

Variables d'environnement :
- `DRIVE_CONFIG_FOLDER_ID` : même ID que le secret GitHub
- `VISUELS_DIR` : dossier de destination (défaut : `~/visuels`)
- `DELAY_DL` : délai entre téléchargements en secondes (défaut : 1.5)
- `BATCH_SIZE` : nombre d'EAN par passe (défaut : 50)

Prérequis : `~/.credentials_drive.json` + Firefox connecté à coursesu.com

## Agent 3 (Local) — `agent3_github_watcher.py`

Surveille les runs `aut_prep`, analyse les échecs via Claude API et corrige.

```bash
GITHUB_TOKEN=ghp_xxx \
ANTHROPIC_API_KEY=sk-ant-xxx \
python3 agents/agent3_github_watcher.py
```

Variables d'environnement :
- `GITHUB_TOKEN` : token GitHub avec permissions `repo` + `workflow`
- `ANTHROPIC_API_KEY` : clé API Anthropic
- `REPO_PATH` : chemin du dépôt local (défaut : répertoire parent de `agents/`)
- `POLL_INTERVAL` : intervalle en secondes (défaut : 120)

## Cron recommandé (agents locaux)

```cron
# Agent 2 : chaque nuit à 2h
0 2 * * * DRIVE_CONFIG_FOLDER_ID=xxx python3 /chemin/auto_prepa/agents/agent2_telechargement.py

# Agent 3 : toutes les 5 minutes
*/5 * * * * GITHUB_TOKEN=xxx ANTHROPIC_API_KEY=xxx python3 /chemin/auto_prepa/agents/agent3_github_watcher.py
```
