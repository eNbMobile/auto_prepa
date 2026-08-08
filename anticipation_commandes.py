#!/usr/bin/env python3
"""
Recupere tous les bon_anticipation_NUMERO.txt deja archives dans la journee
sur Drive (GITHUB/Anticipation/MM_AAAA/JJ_MM, deposes au fil de l'eau par
auto_prepa.py) et les assemble dans un seul fichier anticipation_JJ_MM.txt,
trie par lettre d'anticipation, uploade sur Drive.
"""

import io
import os
import re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import auto_prepa as ap

_TZ = ZoneInfo("Europe/Paris")

# Format des lignes de bon_anticipation.txt (16 champs separes par ';') :
# 0 gencod ; 1 libelle ; 2 prix ; 3 prix au kg/L ; 4 qte ; 5 substitution ;
# 6-8 sans interet ; 9 jour de commande + heure + autres infos ; 10 sacs ;
# 11 adresse ; 12-14 sans interet ; 15 (dernier champ) lettre d'anticipation
_IDX_GENCOD  = 0
_IDX_LIBELLE = 1
_IDX_PRIX    = 2
_IDX_QTE     = 4
_IDX_JOUR_HEURE = 9
_IDX_ADRESSE = 11
_NB_CHAMPS_MIN = 16

_RE_LEADING_SEQ = re.compile(r'^(?:-\d+)?;(\d{13};)')
_RE_HEURE = re.compile(r'([01]?\d|2[0-3])[:h]([0-5]\d)')


def _parser_lignes_anticipation(contenu, numero_commande):
    """Parse le contenu d'un bon_anticipation.txt et ne garde que les champs utiles.

    Retourne une liste de dicts : commande, gencod, libelle, prix, qte, heure, adresse, lettre.
    """
    produits = []
    for ligne in contenu.splitlines():
        ligne = ligne.rstrip('\n')
        if not ligne.strip():
            continue
        ligne = _RE_LEADING_SEQ.sub(r'\1', ligne)
        champs = ligne.split(';')
        if len(champs) < _NB_CHAMPS_MIN:
            print(f"    [{numero_commande}] ligne ignoree ({len(champs)} champ(s)) : {ligne[:120]}")
            continue

        m_heure = _RE_HEURE.search(champs[_IDX_JOUR_HEURE])
        heure = f"{m_heure.group(1)}:{m_heure.group(2)}" if m_heure else ""

        produits.append({
            "commande": numero_commande,
            "gencod":   champs[_IDX_GENCOD].strip(),
            "libelle":  champs[_IDX_LIBELLE].strip(),
            "prix":     champs[_IDX_PRIX].strip(),
            "qte":      champs[_IDX_QTE].strip(),
            "heure":    heure,
            "adresse":  champs[_IDX_ADRESSE].strip(),
            "lettre":   champs[-1].strip() or "?",
        })
    return produits


def _extraire_numero(filename):
    m = re.search(r'bon_anticipation_(\w+)\.txt', filename, re.IGNORECASE)
    return m.group(1) if m else filename


def _lister_anticipations_du_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm):
    """Retourne [(file_id, filename), ...] des bon_anticipation_*.txt deja archives
    aujourd'hui sur Drive sous GITHUB/Anticipation/MM_AAAA/JJ_MM."""
    res = drive_svc.files().list(
        q=("name='GITHUB' and 'root' in parents "
           "and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    github = res.get("files", [])
    if not github:
        print("  Dossier GITHUB/ introuvable sur Drive.")
        return []

    res = drive_svc.files().list(
        q=(f"name='Anticipation' and '{github[0]['id']}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    anticipation = res.get("files", [])
    if not anticipation:
        print("  Dossier GITHUB/Anticipation/ introuvable sur Drive.")
        return []

    res = drive_svc.files().list(
        q=(f"name='{dossier_mm_aaaa}' and '{anticipation[0]['id']}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    mois = res.get("files", [])
    if not mois:
        print(f"  Dossier GITHUB/Anticipation/{dossier_mm_aaaa}/ introuvable sur Drive.")
        return []

    res = drive_svc.files().list(
        q=(f"name='{dossier_jj_mm}' and '{mois[0]['id']}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    jour = res.get("files", [])
    if not jour:
        print(f"  Dossier GITHUB/Anticipation/{dossier_mm_aaaa}/{dossier_jj_mm}/ introuvable sur Drive.")
        return []

    res = drive_svc.files().list(
        q=(f"'{jour[0]['id']}' in parents and name contains 'bon_anticipation_' "
           f"and trashed=false"),
        fields="files(id,name)",
        pageSize=200,
    ).execute()
    return [(f["id"], f["name"]) for f in res.get("files", [])]


def _telecharger_texte(drive_svc, file_id):
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8", errors="replace")


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)

    ap._charger_config(drive_svc)

    maintenant = datetime.now(_TZ)
    dossier_mm_aaaa = maintenant.strftime("%m_%Y")
    dossier_jj_mm = maintenant.strftime("%d_%m")

    print(f"Recherche des anticipations du {dossier_jj_mm}/{dossier_mm_aaaa} "
          f"sur Drive GITHUB/Anticipation...")
    fichiers = _lister_anticipations_du_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm)
    if not fichiers:
        print("Aucune anticipation trouvee pour aujourd'hui.")
        return

    print(f"{len(fichiers)} commande(s) avec anticipation trouvee(s).")

    tous_produits = []
    for file_id, filename in sorted(fichiers, key=lambda p: p[1]):
        numero = _extraire_numero(filename)
        contenu = _telecharger_texte(drive_svc, file_id)
        produits = _parser_lignes_anticipation(contenu, numero)
        tous_produits.extend(produits)

    par_lettre = defaultdict(list)
    for p in tous_produits:
        par_lettre[p["lettre"]].append(p)

    sections = []
    for lettre in sorted(par_lettre.keys()):
        produits_lettre = sorted(par_lettre[lettre], key=lambda p: (p["commande"], p["gencod"]))
        entete_section = f"=== Lettre {lettre} ({len(produits_lettre)} produit(s)) ===\n"
        corps_lignes = "\n".join(
            f"{p['commande']};{p['gencod']};{p['libelle']};{p['prix']};{p['qte']};{p['heure']};{p['adresse']}"
            for p in produits_lettre
        )
        sections.append(entete_section + corps_lignes + "\n")

    entete = (
        f"Produits anticipables du {dossier_jj_mm}/{maintenant.strftime('%Y')}\n"
        f"{len(fichiers)} commande(s) avec anticipation, "
        f"{len(tous_produits)} produit(s) anticipable(s)\n"
        f"Colonnes : commande;gencod;libelle;prix;qte;heure;adresse\n"
        + "=" * 50 + "\n\n"
    )
    corps = "\n".join(sections) if sections else "(aucun produit anticipable aujourd'hui)\n"
    contenu_final = entete + corps

    nom_fichier = f"anticipation_{dossier_jj_mm}.txt"
    chemin_local = os.path.join(ap.WORK_DIR, nom_fichier)
    with open(chemin_local, "w", encoding="utf-8") as f:
        f.write(contenu_final)
    try:
        ap.upload_bon(drive_svc, chemin_local)
    finally:
        if os.path.exists(chemin_local):
            os.remove(chemin_local)

    print(f"\n{nom_fichier} => Drive OK "
          f"({len(fichiers)} commande(s) avec produits anticipables)")


if __name__ == "__main__":
    main()
