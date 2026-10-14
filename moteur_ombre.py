"""Mode ombre du moteur de préparation : à chaque commande, le portage Python
(prepa_drive_degrade.py) tourne derrière le binaire C de production, sur une
copie des mêmes entrées, et ses sorties sont comparées à celles du C.

Le C reste seul à produire les bons utilisés : le Python ne fait que
calculer, dans un dossier temporaire à part. Une erreur du mode ombre
(plantage Python, copie impossible…) est affichée et n'interrompt jamais la
commande.

Dépôt public : le log n'affiche que le verdict, les durées et le nombre de
lignes qui diffèrent, jamais le contenu des bons (il contient le nom du
client). En cas d'écart, les deux bons sont déposés sur Drive (privé) dans
GITHUB/MoteurOmbre/ pour analyse.

Interrupteur : variable de dépôt MOTEUR_OMBRE=0 pour le couper.
"""
import contextlib
import io
import os
import re
import shutil
import tempfile
import time

import prepa_drive_degrade as pdd

# Fichiers lus par le moteur Python (le C lit aussi chemin_prepa_ramasse.csv,
# inutile ici : une commande traitée seule est toujours en mode MONO).
ENTREES = ("gencod_adresses.csv", "gencod_nomenclatures.csv", "chemin_prepa_mono.csv")
_RE_PREFIXE = re.compile(rb"^(?:-\d+)?;(\d{13};)")

_tables = {}  # tables du moteur Python, chargées une fois par run


def actif(moteur_prepa):
    """Le mode ombre ne tourne que lorsque le C est le moteur de production."""
    return moteur_prepa != "python" and os.environ.get("MOTEUR_OMBRE", "1").strip() != "0"


def preparer(work_dir, pdf_name):
    """Copie les entrées du moteur AVANT le passage du C (qui réécrit certains
    fichiers de WORK_DIR). Renvoie le dossier temporaire, ou None."""
    try:
        dossier = tempfile.mkdtemp(prefix="ombre_")
        for nom in ENTREES + (pdf_name,):
            src = os.path.join(work_dir, nom)
            if os.path.exists(src):
                shutil.copy2(src, dossier)
        return dossier
    except Exception as e:  # noqa: BLE001 - le mode ombre ne doit rien casser
        print(f"    Mode ombre : préparation impossible ({type(e).__name__})")
        return None


def garder_sorties_c(dossier, work_dir):
    """Copie les sorties brutes du C (avant toute retouche par auto_prepa.py)
    dans dossier/c/, pour comparer plus tard, après le dépôt du bon.
    Renvoie ce sous-dossier, ou None."""
    if not dossier:
        return None
    try:
        cible = os.path.join(dossier, "c")
        os.makedirs(cible, exist_ok=True)
        for nom in ("bon_prepa.txt", "bon_anticipation.txt"):
            src = os.path.join(work_dir, nom)
            if os.path.exists(src):
                shutil.copy2(src, cible)
        return cible
    except Exception as e:  # noqa: BLE001
        print(f"    Mode ombre : copie des sorties du C impossible ({type(e).__name__})")
        return None


def normaliser_bon(data):
    """Même nettoyage que auto_prepa.py : préfixe parasite « -N; » retiré."""
    lignes = (data or b"").split(b"\n")
    return b"\n".join([lignes[0]] + [_RE_PREFIXE.sub(rb"\1", l) for l in lignes[1:]])


def avertissements(sortie):
    return [l.strip() for l in (sortie or "").splitlines()
            if "ne fait pas partie du chemin de" in l
            or "Aucune adresse ni aucune nomenclature" in l]


def _lire(chemin):
    try:
        with open(chemin, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return b""


def _lignes_differentes(a, b):
    la, lb = a.split(b"\n"), b.split(b"\n")
    return sum(1 for x, y in zip(la, lb) if x != y) + abs(len(la) - len(lb))


def comparer(dossier, work_dir, sortie_c):
    """Fait tourner le Python dans `dossier` et compare avec les sorties du C
    présentes dans `work_dir`. Renvoie un dict :
    identique, ecarts (liste de textes courts), duree_py, chargement_py."""
    t0 = time.perf_counter()
    if "tables" not in _tables:
        _tables["tables"] = pdd.charger_tables(dossier)
    chargement = time.perf_counter() - t0

    buf = io.StringIO()
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        pdd.Moteur(dossier).executer(tables=_tables["tables"])
    duree = time.perf_counter() - t0

    ecarts = []
    prepa_c = normaliser_bon(_lire(os.path.join(work_dir, "bon_prepa.txt")))
    prepa_py = normaliser_bon(_lire(os.path.join(dossier, "bon_prepa.txt")))
    if prepa_c != prepa_py:
        ecarts.append(f"bon_prepa ({_lignes_differentes(prepa_c, prepa_py)} ligne(s))")
    anticip_c = _lire(os.path.join(work_dir, "bon_anticipation.txt"))
    anticip_py = _lire(os.path.join(dossier, "bon_anticipation.txt"))
    if anticip_c != anticip_py:
        ecarts.append(f"bon_anticipation ({_lignes_differentes(anticip_c, anticip_py)} ligne(s))")
    if avertissements(sortie_c) != avertissements(buf.getvalue()):
        ecarts.append("avertissements d'adressage")
    return {"identique": not ecarts, "ecarts": ecarts,
            "duree_py": duree, "chargement_py": chargement}


def deposer_ecart(drive_svc, get_or_create_subfolder, numero, dossier, work_dir):
    """Dépose les bons C et Python sur Drive (GITHUB/MoteurOmbre/)."""
    from googleapiclient.http import MediaFileUpload
    github = get_or_create_subfolder(drive_svc, "root", "GITHUB")
    cible = get_or_create_subfolder(drive_svc, github, "MoteurOmbre") if github else None
    if not cible:
        return
    for nom in ("bon_prepa.txt", "bon_anticipation.txt"):
        for moteur, base in (("c", work_dir), ("python", dossier)):
            chemin = os.path.join(base, nom)
            if os.path.exists(chemin):
                drive_svc.files().create(
                    body={"name": f"{numero}_{nom[:-4]}_{moteur}.txt", "parents": [cible]},
                    media_body=MediaFileUpload(chemin, mimetype="text/plain"),
                    fields="id").execute()


def executer(drive_svc, get_or_create_subfolder, numero, dossier, work_dir, sortie_c, duree_c):
    """Point d'entrée appelé par auto_prepa.py après un passage réussi du C.
    `work_dir` : dossier contenant les sorties brutes du C (garder_sorties_c)."""
    if not dossier:
        return None
    if not work_dir:
        shutil.rmtree(dossier, ignore_errors=True)
        return None
    try:
        res = comparer(dossier, work_dir, sortie_c)
        verdict = "identique" if res["identique"] else "DIFFÉRENT : " + ", ".join(res["ecarts"])
        print(f"    Mode ombre : Python {verdict} | C {duree_c:.2f} s | "
              f"Python {res['duree_py']:.2f} s"
              + (f" (+ {res['chargement_py']:.1f} s de chargement des CSV, une fois par run)"
                 if res["chargement_py"] >= 0.05 else ""))
        if not res["identique"]:
            try:
                deposer_ecart(drive_svc, get_or_create_subfolder, numero, dossier, work_dir)
                print("    Mode ombre : bons C et Python déposés dans Drive GITHUB/MoteurOmbre/")
            except Exception as e:  # noqa: BLE001
                print(f"    Mode ombre : dépôt Drive impossible ({type(e).__name__})")
        return res
    except Exception as e:  # noqa: BLE001 - un plantage Python est un résultat
        print(f"    Mode ombre : Python EN ERREUR ({type(e).__name__}) | C {duree_c:.2f} s")
        return {"identique": False, "ecarts": [f"erreur {type(e).__name__}"]}
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
