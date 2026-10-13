#!/usr/bin/env python3
"""Compare le moteur de préparation C (binaire de production, Drive) et son
portage Python (prepa_drive_degrade.py) sur de vrais bons de commande.

Pour chaque BonDeCommande_*.pdf des derniers jours (Drive BDC/MM_AAAA/JJ_MM),
les deux moteurs tournent dans des dossiers séparés, avec la même config
(gencod_adresses.csv, gencod_nomenclatures.csv, chemin_prepa_mono.csv
téléchargés depuis Drive). Sont comparés, après le même nettoyage que fait
auto_prepa.py (préfixe parasite « -N; » retiré) :
- bon_prepa.txt, octet pour octet ;
- bon_anticipation.txt ;
- les avertissements d'adressage affichés (que lit auto_prepa.py).

Dépôt public : le log n'affiche jamais le champ « infos client » (date,
créneau, nom) et les noms extraits des bons sont masqués (::add-mask::).

Usage : comparer_moteurs.py [--max N] [--jours J]
"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import confidentiel
import controle_stocks as cs
import prepa_drive_degrade as pdd

_TZ = ZoneInfo("Europe/Paris")
CONFIG = ["gencod_adresses.csv", "gencod_nomenclatures.csv", "chemin_prepa_mono.csv",
          "chemin_prepa_ramasse.csv", "prepa_drive_degrade"]
_RE_PREFIXE = re.compile(rb"^(?:-\d+)?;(\d{13};)")
_RE_CLIENT = re.compile(r"\b(M\.|Mme|Mlle)\s+([A-ZÀ-ÖØ-Ý' -]+[A-ZÀ-ÖØ-Ý])\b")
CHAMP_INFOS = 9


def _telecharger(svc, file_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()


def _sous_dossier(svc, parent, nom):
    res = svc.files().list(
        q=(f"name='{nom}' and '{parent}' in parents and "
           f"mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)").execute().get("files", [])
    return res[0]["id"] if res else None


def lister_bdc(svc, nb_max, nb_jours):
    """[(nom, file_id)] des bons des `nb_jours` derniers jours, au plus nb_max."""
    trouves = []
    jour = datetime.now(_TZ).date()
    for _ in range(nb_jours):
        mois = _sous_dossier(svc, cs.DRIVE_BDC_FOLDER_ID, jour.strftime("%m_%Y"))
        dossier = _sous_dossier(svc, mois, jour.strftime("%d_%m")) if mois else None
        if dossier:
            token = None
            while True:
                res = svc.files().list(
                    q=f"'{dossier}' in parents and name contains 'BonDeCommande' and trashed=false",
                    fields="nextPageToken, files(id,name)", pageSize=1000,
                    pageToken=token).execute()
                trouves += [(f["name"], f["id"]) for f in res.get("files", [])]
                token = res.get("nextPageToken")
                if not token:
                    break
        if len(trouves) >= nb_max:
            break
        jour -= timedelta(days=1)
    return trouves[:nb_max]


def normaliser_bon(data):
    lignes = (data or b"").split(b"\n")
    return b"\n".join([lignes[0]] + [_RE_PREFIXE.sub(rb"\1", l) for l in lignes[1:]])


def avertissements(sortie):
    return [l for l in sortie.splitlines()
            if "ne fait pas partie du chemin de" in l or "Aucune adresse ni aucune nomenclature" in l
            or "replacé automatiquement" in l]


def anonymiser(ligne):
    champs = ligne.split(b";")
    if len(champs) > CHAMP_INFOS:
        champs[CHAMP_INFOS] = b"<infos client>"
    return b";".join(champs).decode("latin-1")


def lancer_c(dossier_cfg, pdf, travail):
    for f in CONFIG:
        if os.path.exists(os.path.join(dossier_cfg, f)):
            shutil.copy2(os.path.join(dossier_cfg, f), travail)
    os.chmod(os.path.join(travail, "prepa_drive_degrade"), 0o755)
    shutil.copy2(pdf, travail)
    t0 = time.perf_counter()
    r = subprocess.run(["./prepa_drive_degrade"], cwd=travail, capture_output=True,
                       text=True, errors="replace", timeout=300)
    duree = time.perf_counter() - t0
    return r.returncode, r.stdout, duree


def lancer_py(dossier_cfg, pdf, travail, tables):
    for f in CONFIG[:3]:
        os.symlink(os.path.join(dossier_cfg, f), os.path.join(travail, f))
    shutil.copy2(pdf, travail)
    buf = io.StringIO()
    t0 = time.perf_counter()
    try:
        with contextlib.redirect_stdout(buf):
            pdd.Moteur(travail).executer(tables=tables)
        code = 0
    except Exception as e:  # noqa: BLE001 - on veut compter les plantages
        buf.write(f"\nEXCEPTION {type(e).__name__}: {e}\n")
        code = 1
    return code, buf.getvalue(), time.perf_counter() - t0


def lire(chemin):
    try:
        with open(chemin, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def main():
    nb_max = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 150
    nb_jours = int(sys.argv[sys.argv.index("--jours") + 1]) if "--jours" in sys.argv else 30

    cs._charger_config()
    svc = cs._get_drive_service()
    racine = tempfile.mkdtemp()
    cfg = os.path.join(racine, "config")
    os.makedirs(cfg)
    index = {f["name"]: f["id"] for f in svc.files().list(
        q=f"'{cs.DRIVE_CONFIG_FOLDER_ID}' in parents and trashed=false",
        fields="files(id,name)", pageSize=200).execute().get("files", [])}
    for f in CONFIG:
        if f in index:
            _telecharger(svc, index[f], os.path.join(cfg, f))
    print("Config et binaire C de production téléchargés depuis Drive.")

    t0 = time.perf_counter()
    tables = pdd.charger_tables(cfg)
    chargement = time.perf_counter() - t0
    print(f"Python : chargement des CSV en {chargement:.1f} s (une fois par run aut_prep).")

    bons = lister_bdc(svc, nb_max, nb_jours)
    print(f"{len(bons)} bon(s) de commande à comparer.\n")

    stats = {"identiques": 0, "diff_prepa": 0, "diff_anticip": 0, "diff_avert": 0,
             "plantage_c": 0, "plantage_py": 0, "prefixe_c": 0}
    durees_c, durees_py = [], []
    for n, (nom, fid) in enumerate(bons, 1):
        numero = nom.removeprefix("BonDeCommande_").removesuffix(".pdf")
        dossier = os.path.join(racine, f"bon_{n}")
        dc, dp = os.path.join(dossier, "c"), os.path.join(dossier, "py")
        os.makedirs(dc)
        os.makedirs(dp)
        pdf = os.path.join(dossier, nom)
        _telecharger(svc, fid, pdf)
        texte = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True,
                               text=True, errors="replace").stdout
        for m in _RE_CLIENT.finditer(texte):
            confidentiel.masquer(m.group(2))

        code_c, sortie_c, duree_c = lancer_c(cfg, pdf, dc)
        code_p, sortie_p, duree_p = lancer_py(cfg, pdf, dp, tables)
        durees_c.append(duree_c)
        durees_py.append(duree_p)
        if code_c != 0:
            stats["plantage_c"] += 1
        if code_p != 0:
            stats["plantage_py"] += 1

        prepa_c, prepa_p = lire(os.path.join(dc, "bon_prepa.txt")), lire(os.path.join(dp, "bon_prepa.txt"))
        antic_c, antic_p = lire(os.path.join(dc, "bon_anticipation.txt")), lire(os.path.join(dp, "bon_anticipation.txt"))
        if prepa_c and any(_RE_PREFIXE.match(l) and not l[:1].isdigit() for l in prepa_c.split(b"\n")[1:]):
            stats["prefixe_c"] += 1
        ok_prepa = normaliser_bon(prepa_c) == normaliser_bon(prepa_p)
        ok_antic = (antic_c or b"") == (antic_p or b"")
        ok_avert = avertissements(sortie_c) == avertissements(sortie_p)
        if ok_prepa and ok_antic and ok_avert and code_c == code_p:
            stats["identiques"] += 1
            print(f"[{n:3}] {numero} : identique (C {duree_c:.2f} s / Python {duree_p:.2f} s)")
            continue
        stats["diff_prepa"] += not ok_prepa
        stats["diff_anticip"] += not ok_antic
        stats["diff_avert"] += not ok_avert
        print(f"[{n:3}] {numero} : DIFFERENCE (prepa={'ok' if ok_prepa else 'KO'}, "
              f"anticipation={'ok' if ok_antic else 'KO'}, avertissements={'ok' if ok_avert else 'KO'}, "
              f"code C={code_c} Python={code_p})")
        if not ok_prepa:
            lc = normaliser_bon(prepa_c).split(b"\n")
            lp = normaliser_bon(prepa_p).split(b"\n")
            print(f"      lignes : C={len(lc)} Python={len(lp)}")
            affichees = 0
            for k in range(max(len(lc), len(lp))):
                a = lc[k] if k < len(lc) else b"<absente>"
                b = lp[k] if k < len(lp) else b"<absente>"
                if a != b and affichees < 4:
                    print(f"      L{k} C  : {anonymiser(a)}")
                    print(f"      L{k} Py : {anonymiser(b)}")
                    affichees += 1
        if not ok_antic:
            lc = (antic_c or b"").split(b"\n")
            lp = (antic_p or b"").split(b"\n")
            print(f"      anticipation : C={len(lc)} ligne(s), Python={len(lp)}")
            for k in range(min(3, max(len(lc), len(lp)))):
                a = lc[k] if k < len(lc) else b""
                b = lp[k] if k < len(lp) else b""
                if a != b:
                    print(f"      A{k} C  : {anonymiser(a)}")
                    print(f"      A{k} Py : {anonymiser(b)}")
        if not ok_avert:
            print(f"      avertissements C  : {avertissements(sortie_c)[:4]}")
            print(f"      avertissements Py : {avertissements(sortie_p)[:4]}")
        if code_p != 0:
            print("      " + sortie_p.strip().splitlines()[-1][:200])
        shutil.rmtree(dossier, ignore_errors=True)

    total = len(bons)
    print("\n================ BILAN ================")
    print(f"Bons comparés            : {total}")
    print(f"Identiques               : {stats['identiques']}")
    print(f"bon_prepa différent      : {stats['diff_prepa']}")
    print(f"bon_anticipation diff.   : {stats['diff_anticip']}")
    print(f"avertissements différents: {stats['diff_avert']}")
    print(f"Plantages C / Python     : {stats['plantage_c']} / {stats['plantage_py']}")
    print(f"Bons C avec préfixe « -N; » parasite : {stats['prefixe_c']}")
    if durees_c:
        print(f"Durée moyenne par bon    : C {sum(durees_c) / total:.2f} s (max {max(durees_c):.2f}) / "
              f"Python {sum(durees_py) / total:.2f} s (max {max(durees_py):.2f}) "
              f"+ {chargement:.1f} s de chargement par run")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Comparaison moteurs C / Python\n\n{stats['identiques']}/{total} bons identiques.\n")


if __name__ == "__main__":
    main()
