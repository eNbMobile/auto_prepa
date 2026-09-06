#!/usr/bin/env python3
"""Diagnostic a usage unique : lance prepa_drive_degrade sous gdb pour un
BonDeCommande deja en cache, afin d'obtenir la pile d'appel exacte du
SIGSEGV observe lors du rattrapage des commandes du 05-06/09/2026."""
import os
import shutil
import subprocess

from googleapiclient.discovery import build

import auto_prepa as ap

NUMERO_TEST = "54604892"


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)
    os.makedirs(ap.CACHE_DIR, exist_ok=True)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    ap._charger_config(drive_svc)
    ap.telecharger_config_drive(drive_svc)

    pdf = f"BonDeCommande_{NUMERO_TEST}.pdf"
    cache_path = os.path.join(ap.CACHE_DIR, pdf)
    if not os.path.exists(cache_path):
        print(f"ERREUR : {cache_path} absent du cache.")
        return
    shutil.copy2(cache_path, os.path.join(ap.WORK_DIR, pdf))

    for fname in ["gencod_adresses.csv", "gencod_nomenclatures.csv",
                  "chemin_prepa_mono.csv", "chemin_prepa_ramasse.csv", "prepa_drive_degrade"]:
        p = os.path.join(ap.WORK_DIR, fname)
        print(f"--- {fname} ---")
        print(subprocess.run(["ls", "-la", p], capture_output=True, text=True).stdout)
        print(subprocess.run(["file", p], capture_output=True, text=True).stdout)
        if fname.endswith(".csv"):
            print(subprocess.run(["wc", "-l", p], capture_output=True, text=True).stdout)
            print(subprocess.run(["head", "-c", "200", p], capture_output=True, text=True).stdout)
            print(subprocess.run(["tail", "-c", "200", p], capture_output=True, text=True).stdout)

    print("--- gdb backtrace ---", flush=True)
    r = subprocess.run(
        ["gdb", "-batch", "-ex", "run", "-ex", "bt full", "-ex", "info registers",
         "./prepa_drive_degrade"],
        cwd=ap.WORK_DIR, capture_output=True, text=True, timeout=120)
    print(r.stdout)
    print("STDERR:", r.stderr)


if __name__ == "__main__":
    main()
