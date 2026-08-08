#!/usr/bin/env python3
"""
Reprend tous les BonDeCommande archives du jour sur Drive (BDC/MM_AAAA/JJ_MM),
relance la generation (prepa_drive_degrade) pour chacun et archive le resultat
de chaque commande (bon_anticipation_NUMERO.txt) sous
GITHUB/Anticipation/MM_AAAA/JJ_MM sur Drive.
"""

import os
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

import auto_prepa as ap

_TZ = ZoneInfo("Europe/Paris")

TEMP_FILES = [
    "bon_prepa.txt", "bon_anticipation.txt", "bon_prepa_NEW.txt", "bon_prepa_dlc.txt",
    "bon_encaissement.pdf", "bon_encaissement.csv", "bon_encaissement_NEW.csv",
    "base_client.txt", "tri_cde.txt", "tri_heures.txt",
    "tmp", "tmp2", "tmp_NEW", "temp", "gentemp.txt", "temp_lib.txt",
]


def _nettoyer_work_dir():
    """Supprime les artefacts de generation laisses par un run precedent."""
    for fname in TEMP_FILES:
        fpath = os.path.join(ap.WORK_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)


def _extraire_numero(filename):
    m = re.search(r'BonDeCommande_(\w+)\.pdf', filename, re.IGNORECASE)
    return m.group(1) if m else filename


def _lister_pdfs_du_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm):
    """Retourne [(file_id, filename), ...] des BonDeCommande du jour sur Drive."""
    res = drive_svc.files().list(
        q=(f"name='{dossier_mm_aaaa}' and '{ap.DRIVE_BDC_FOLDER_ID}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    mois = res.get("files", [])
    if not mois:
        print(f"  Dossier BDC/{dossier_mm_aaaa}/ introuvable sur Drive.")
        return []

    res = drive_svc.files().list(
        q=(f"name='{dossier_jj_mm}' and '{mois[0]['id']}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    jour = res.get("files", [])
    if not jour:
        print(f"  Dossier BDC/{dossier_mm_aaaa}/{dossier_jj_mm}/ introuvable sur Drive.")
        return []

    res = drive_svc.files().list(
        q=(f"'{jour[0]['id']}' in parents and mimeType='application/pdf' "
           f"and name contains 'BonDeCommande' and trashed=false"),
        fields="files(id,name)",
        pageSize=200,
    ).execute()
    return [(f["id"], f["name"]) for f in res.get("files", [])]


def _generer_anticipation_pour_pdf(drive_svc, file_id, filename):
    """Telecharge un BDC, lance prepa_drive_degrade, retourne le contenu de bon_anticipation.txt."""
    numero = _extraire_numero(filename)
    _nettoyer_work_dir()

    pdf_path = os.path.join(ap.WORK_DIR, filename)
    try:
        ap.download_pdf(drive_svc, file_id, pdf_path)

        pt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                             capture_output=True, text=True)
        if not pt.stdout.strip():
            print(f"    [{numero}] ECHEC pdftotext - PDF vide ou non lisible")
            return ""

        r = subprocess.run(["./prepa_drive_degrade"], cwd=ap.WORK_DIR,
                            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"    [{numero}] ERREUR generation (code {r.returncode})")
            if r.stderr:
                print(f"      stderr : {r.stderr[:300]}")
            return ""

        anticipation_path = os.path.join(ap.WORK_DIR, "bon_anticipation.txt")
        if not os.path.exists(anticipation_path) or os.path.getsize(anticipation_path) == 0:
            return ""
        with open(anticipation_path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"    [{numero}] Erreur : {e}")
        return ""
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        _nettoyer_work_dir()


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)

    ap._charger_config(drive_svc)
    ap.telecharger_config_drive(drive_svc)

    maintenant = datetime.now(_TZ)
    dossier_mm_aaaa = maintenant.strftime("%m_%Y")
    dossier_jj_mm = maintenant.strftime("%d_%m")

    print(f"Recherche des commandes du {dossier_jj_mm}/{dossier_mm_aaaa} sur Drive BDC...")
    pdfs = _lister_pdfs_du_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm)
    if not pdfs:
        print("Aucune commande trouvee pour aujourd'hui.")
        return

    print(f"{len(pdfs)} commande(s) trouvee(s).")

    nb_avec_anticipation = 0
    for file_id, filename in sorted(pdfs, key=lambda p: p[1]):
        numero = _extraire_numero(filename)
        print(f"  [{numero}] Generation...", end="", flush=True)
        contenu = _generer_anticipation_pour_pdf(drive_svc, file_id, filename)
        if not contenu.strip():
            print(" aucun produit anticipable")
            continue

        nb_avec_anticipation += 1
        chemin_local = os.path.join(ap.WORK_DIR, f"bon_anticipation_{numero}.txt")
        with open(chemin_local, "w", encoding="utf-8") as f:
            f.write(contenu)
        try:
            ap.archiver_anticipation_drive(drive_svc, chemin_local, dossier_jj_mm, dossier_mm_aaaa)
        finally:
            if os.path.exists(chemin_local):
                os.remove(chemin_local)
        print(" OK")

    print(f"\n{nb_avec_anticipation}/{len(pdfs)} commande(s) avec produits anticipables "
          f"=> Drive GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}/")


if __name__ == "__main__":
    main()
