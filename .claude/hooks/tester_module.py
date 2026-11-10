#!/usr/bin/env python3
"""Hook PostToolUse : teste le script Python que Claude vient de modifier.

- fichier tests/test_*.py : lance ce test ;
- script du dépôt : lance les tests qui l'importent, sinon vérifie qu'il compile.

En cas d'échec, la sortie est renvoyée à Claude (code 2) pour qu'il corrige.
"""
import json
import os
import re
import subprocess
import sys

racine = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

try:
    chemin = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
except ValueError:
    sys.exit(0)

if not chemin.endswith(".py"):
    sys.exit(0)
chemin = os.path.abspath(chemin)
relatif = os.path.relpath(chemin, racine)
if relatif.startswith("..") or not os.path.exists(chemin):
    sys.exit(0)

dossier_tests = os.path.join(racine, "tests")
module = os.path.splitext(os.path.basename(chemin))[0]

if relatif.startswith("tests" + os.sep) and module.startswith("test_"):
    tests = [module]
elif os.path.dirname(relatif) == "":
    motif = re.compile(rf"^\s*(import|from)\s+{re.escape(module)}\b", re.M)
    tests = []
    for nom in sorted(os.listdir(dossier_tests)):
        if nom.startswith("test_") and nom.endswith(".py"):
            with open(os.path.join(dossier_tests, nom), encoding="utf-8") as f:
                if motif.search(f.read()):
                    tests.append(nom[:-3])
else:
    tests = []

if tests:
    commande = [sys.executable, "-m", "unittest", "-q"] + [f"tests.{t}" for t in tests]
else:
    commande = [sys.executable, "-m", "py_compile", chemin]

resultat = subprocess.run(commande, cwd=racine, capture_output=True, text=True, timeout=120)
if resultat.returncode != 0:
    sortie = (resultat.stdout + resultat.stderr).strip()
    print(f"Échec après modification de {relatif} ({' '.join(commande[2:])}) :\n{sortie[-4000:]}",
          file=sys.stderr)
    sys.exit(2)
