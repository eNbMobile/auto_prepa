# Agents d'automatisation

## Installation

```bash
pip install -r agents/requirements_agents.txt
```

## Agent 1 — Collecte EAN (`agent1_collecte_ean.py`)

Surveille Google Drive (dossier BDC > MM_AAAA > JJ_MM), extrait les EAN-13 des PDFs
`BonDeCommande_*.pdf` et les stocke dans `~/visuels_ean.db`.

```bash
# Avec ID Drive explicite
BDC_FOLDER_ID=1FinYJTdFY1JCYNlZR8xl73ycpWO6WiIP python3 agents/agent1_collecte_ean.py

# Découverte automatique du dossier BDC
python3 agents/agent1_collecte_ean.py
```

Variables d'environnement :
- `BDC_FOLDER_ID` : ID du dossier BDC racine sur Drive
- `POLL_INTERVAL` : intervalle de scan en secondes (défaut : 300)

Prérequis : `~/.credentials_drive.json` (OAuth2 Google, type "application bureau")

## Agent 2 — Téléchargement visuels (`agent2_telechargement.py`)

Lit `~/visuels_ean.db`, télécharge les images produits depuis coursesu.com
en réutilisant les cookies Firefox.

```bash
VISUELS_DIR=~/visuels python3 agents/agent2_telechargement.py
```

Variables d'environnement :
- `VISUELS_DIR` : dossier de destination (défaut : `~/visuels`)
- `COURSESU_URL` : URL de base du site (défaut : `https://www.coursesu.com`)
- `DELAY_DL` : délai entre téléchargements en secondes (défaut : 1.5)
- `BATCH_SIZE` : nombre d'EAN par passe (défaut : 50)

Prérequis : Firefox connecté à coursesu.com

## Agent 3 — GitHub Watcher (`agent3_github_watcher.py`)

Surveille les runs du workflow `aut_prep` sur `eNbMobile/auto_prepa`.
En cas d'échec, analyse les logs via l'API Claude et applique une correction.

```bash
GITHUB_TOKEN=ghp_xxx \
ANTHROPIC_API_KEY=sk-ant-xxx \
REPO_PATH=/chemin/vers/auto_prepa \
python3 agents/agent3_github_watcher.py
```

Variables d'environnement :
- `GITHUB_TOKEN` : token GitHub avec permissions `repo` et `workflow`
- `ANTHROPIC_API_KEY` : clé API Anthropic
- `REPO_PATH` : chemin vers le dépôt local (défaut : répertoire parent des agents)
- `GITHUB_REPO` : dépôt à surveiller (défaut : `eNbMobile/auto_prepa`)
- `WORKFLOW_NAME` : nom du workflow (défaut : `aut_prep`)
- `POLL_INTERVAL` : intervalle en secondes (défaut : 120)

## Lancer automatiquement via cron

```cron
# Agent 1 : toutes les 10 minutes
*/10 * * * * BDC_FOLDER_ID=xxx python3 /chemin/auto_prepa/agents/agent1_collecte_ean.py --once

# Agent 2 : chaque nuit à 2h
0 2 * * * python3 /chemin/auto_prepa/agents/agent2_telechargement.py --once

# Agent 3 : toutes les 5 minutes
*/5 * * * * GITHUB_TOKEN=xxx ANTHROPIC_API_KEY=xxx python3 /chemin/auto_prepa/agents/agent3_github_watcher.py --once
```
