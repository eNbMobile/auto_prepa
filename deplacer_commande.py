#!/usr/bin/env python3
"""
Deplace un (ou plusieurs) BonDeCommande_NUMERO.pdf d'un jour a un autre dans
l'archive Drive BDC/MM_AAAA/JJ_MM.

Pourquoi : un client qui oublie de venir chercher sa commande, ou qui doit la
decaler, la laisse dans le dossier du jour prevu. Les ventes du jour (calculees
a partir des BonDeCommande de ce dossier : generer_ventes, controle_stocks,
cumul_ventes_semaine, renseigne_ca) seraient alors faussees, et le controle de
stock du lendemain aussi. Deplacer le PDF dans le dossier du jour reel de
retrait remet les compteurs d'aplomb.

Le fichier Drive est deplace (meme identifiant, changement de parent) : rien
n'est recree ni perdu. Si le jour cible contient deja ce bon, l'exemplaire du
jour d'origine est mis a la corbeille (restaurable depuis Drive).

Par defaut, ce script ne deplace PAS tout de suite : la demande est inscrite
dans un marqueur Drive (GITHUB/DeplacementsEnAttente/deplacer_NUMERO.txt,
contenant la date cible deja resolue) et c'est deplacer_commandes_attente.py,
lance chaque soir a 22h par cron, qui effectue le deplacement physique. Raison
du differe : les ventes du jour (generer_ventes, controle_stocks,
cumul_ventes_semaine, renseigne_ca) tournent dans la journee, et un
deplacement immediat d'un jour a l'autre leur faisait perdre une commande deja
preparee. --forcer deplace immediatement, comme avant (a utiliser quand la
commande n'a pas encore ete preparee).

--supprimer ne deplace pas la commande : tous ses exemplaires archives dans
BDC sont mis a la corbeille Drive (restaurables). Seul, --supprimer suit la
meme logique de differe (marqueur contenant SUPPRIMER, traite le soir a 22h) ;
avec --forcer, la suppression est immediate. Le jour / la date cible sont
alors ignores.

Usage :
  deplacer_commande.py --numeros "54868421 54868422" [--jour CHOIX] [--date JJ/MM[/AAAA]] [--forcer] [--supprimer]

  --jour    : lendemain (defaut : lendemain du jour actuel de la commande),
              aujourdhui, demain, apres-demain
  --date    : date cible explicite, prioritaire sur --jour
  --forcer  : deplace immediatement au lieu d'attendre le run du soir
  --supprimer : supprime la commande (corbeille Drive) au lieu de la deplacer
"""

import io
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import auto_prepa as ap

MIME_DOSSIER = "application/vnd.google-apps.folder"
_RE_JJ_MM = re.compile(r"^\d{2}_\d{2}$")
_RE_MM_AAAA = re.compile(r"^\d{2}_\d{4}$")

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ─────────────────────────────────────────────────────────────────
# Lecture des parametres
# ─────────────────────────────────────────────────────────────────

def extraire_numeros(texte):
    """Numeros de commande (6 chiffres et plus) saisis, dans l'ordre, sans
    doublon. Accepte espaces, virgules, points-virgules, retours a la ligne,
    et meme des noms de fichier du type BonDeCommande_54868421.pdf."""
    vus = []
    for n in re.findall(r"\d{6,}", texte or ""):
        if n not in vus:
            vus.append(n)
    return vus


def _normaliser(texte):
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def lire_date(texte, aujourd_hui):
    """JJ/MM/AAAA, JJ/MM/AA ou JJ/MM (separateurs / - _ . ou espace).
    Sans annee : l'annee qui place la date au plus pres d'aujourd'hui (un
    31/12 saisi le 2 janvier vise l'annee qui s'acheve). None si invalide."""
    morceaux = re.split(r"[/\-_. ]+", (texte or "").strip())
    try:
        if len(morceaux) == 3:
            j, m, a = (int(x) for x in morceaux)
            if a < 100:
                a += 2000
            return date(a, m, j)
        if len(morceaux) == 2:
            j, m = (int(x) for x in morceaux)
            candidats = []
            for a in (aujourd_hui.year - 1, aujourd_hui.year, aujourd_hui.year + 1):
                try:
                    candidats.append(date(a, m, j))
                except ValueError:
                    pass
            if not candidats:
                return None
            return min(candidats, key=lambda d: abs((d - aujourd_hui).days))
    except ValueError:
        return None
    return None


def date_cible(jour_choisi, date_saisie, jour_actuel, aujourd_hui):
    """Date vers laquelle deplacer la commande. La date saisie prime ; sinon
    le choix : lendemain (du jour actuel de la commande), aujourdhui, demain,
    apres-demain. Leve ValueError si la saisie est inexploitable."""
    if (date_saisie or "").strip():
        d = lire_date(date_saisie, aujourd_hui)
        if d is None:
            raise ValueError(f"date cible invalide : {date_saisie!r} "
                             f"(attendu JJ/MM/AAAA ou JJ/MM)")
        return d
    choix = _normaliser(jour_choisi)
    if "apres" in choix:
        return aujourd_hui + timedelta(days=2)
    if "aujourd" in choix:
        return aujourd_hui
    if "demain" in choix and "lendemain" not in choix:
        return aujourd_hui + timedelta(days=1)
    if not choix or "lendemain" in choix:
        if jour_actuel is None:
            raise ValueError("jour actuel de la commande inconnu : "
                             "impossible de calculer le lendemain, saisir une date")
        return jour_actuel + timedelta(days=1)
    raise ValueError(f"choix de jour inconnu : {jour_choisi!r}")


def jour_du_dossier(dossier_jj_mm, dossier_mm_aaaa):
    """date d'un dossier BDC (JJ_MM dans MM_AAAA), None si non interpretable."""
    try:
        j, m = (int(x) for x in dossier_jj_mm.split("_"))
        _, a = (int(x) for x in dossier_mm_aaaa.split("_"))
        return date(a, m, j)
    except (ValueError, AttributeError):
        return None


def libelle(d):
    return f"{JOURS_FR[d.weekday()]} {d.strftime('%d/%m/%Y')}"


# ─────────────────────────────────────────────────────────────────
# Drive
# ─────────────────────────────────────────────────────────────────

def _meta(drive_svc, file_id):
    return drive_svc.files().get(fileId=file_id, fields="id,name,parents").execute()


def localiser_bdc(drive_svc, numero):
    """Exemplaires de BonDeCommande_NUMERO.pdf archives dans Drive BDC.

    Retourne une liste de dicts {file_id, dossier_id, jj_mm, mm_aaaa} ; seuls
    comptent les fichiers ranges dans BDC/MM_AAAA/JJ_MM (les depots du dossier
    de traitement manuel, par exemple, sont ignores)."""
    nom = f"BonDeCommande_{numero}.pdf"
    res = drive_svc.files().list(
        q=f"name='{nom}' and trashed=false",
        fields="files(id,parents)",
    ).execute()
    trouves = []
    for f in res.get("files", []):
        for dossier_id in f.get("parents") or []:
            dossier = _meta(drive_svc, dossier_id)
            if not _RE_JJ_MM.match(dossier.get("name", "")):
                continue
            for mois_id in dossier.get("parents") or []:
                mois = _meta(drive_svc, mois_id)
                if (_RE_MM_AAAA.match(mois.get("name", ""))
                        and ap.DRIVE_BDC_FOLDER_ID in (mois.get("parents") or [])):
                    trouves.append({"file_id": f["id"], "dossier_id": dossier_id,
                                    "jj_mm": dossier["name"], "mm_aaaa": mois["name"]})
    return trouves


def _localiser_et_resoudre_cible(drive_svc, numero, cible, jour_choisi, date_saisie, aujourd_hui):
    """Localise BonDeCommande_NUMERO.pdf dans l'archive Drive et resout la date
    cible (`cible` si deja calculee, sinon via date_cible()).

    Retourne (ok, cible_ou_None, exemplaires_ou_None, jours_ou_None, message).
    `message` est l'erreur si ok=False, sinon None."""
    nom = f"BonDeCommande_{numero}.pdf"
    try:
        exemplaires = localiser_bdc(drive_svc, numero)
    except Exception as e:
        return False, None, None, None, f"{nom} : recherche sur Drive echouee ({e})"
    if not exemplaires:
        return False, None, None, None, f"{nom} : introuvable dans l'archive Drive BDC"

    jours = sorted({(e["mm_aaaa"], e["jj_mm"]) for e in exemplaires})
    liste = ", ".join(f"BDC/{m}/{j}" for m, j in jours)
    jour_actuel = jour_du_dossier(jours[0][1], jours[0][0]) if len(jours) == 1 else None

    if cible is None:
        try:
            cible = date_cible(jour_choisi, date_saisie, jour_actuel, aujourd_hui)
        except ValueError as e:
            if len(jours) > 1:
                return False, None, None, None, (f"{nom} : present dans plusieurs jours ({liste}) — "
                               f"saisir une date cible")
            return False, None, None, None, f"{nom} : {e}"

    return True, cible, exemplaires, jours, None


def deplacer(drive_svc, numero, cible, jour_choisi="", date_saisie="", aujourd_hui=None):
    """Deplace BonDeCommande_NUMERO.pdf vers le dossier BDC du jour cible.

    Retourne (ok, message). ok=False si la commande est introuvable, ambigue
    ou si le deplacement a echoue. `cible` : date deja calculee, ou None pour
    la deduire (date_cible) une fois le jour actuel de la commande connu."""
    aujourd_hui = aujourd_hui or datetime.now(ap._TZ).date()
    nom = f"BonDeCommande_{numero}.pdf"
    ok, cible, exemplaires, jours, erreur = _localiser_et_resoudre_cible(
        drive_svc, numero, cible, jour_choisi, date_saisie, aujourd_hui)
    if not ok:
        return False, erreur
    liste = ", ".join(f"BDC/{m}/{j}" for m, j in jours)
    jour_actuel = jour_du_dossier(jours[0][1], jours[0][0]) if len(jours) == 1 else None

    cible_jj_mm = cible.strftime("%d_%m")
    cible_mm_aaaa = cible.strftime("%m_%Y")
    chemin_cible = f"BDC/{cible_mm_aaaa}/{cible_jj_mm}"
    hors_cible = [e for e in exemplaires
                  if (e["mm_aaaa"], e["jj_mm"]) != (cible_mm_aaaa, cible_jj_mm)]

    if not hors_cible:
        return True, f"{nom} : deja dans le {libelle(cible)} ({chemin_cible}), rien a faire"
    if len(hors_cible) < len(exemplaires):
        # Deplacement deja fait en partie (bon present a l'origine ET au jour
        # cible) : il ne reste qu'a retirer les exemplaires en trop.
        try:
            for e in hors_cible:
                drive_svc.files().update(fileId=e["file_id"], body={"trashed": True}).execute()
        except Exception as e:
            return False, f"{nom} : mise a la corbeille des doublons echouee ({e})"
        autres = ", ".join(sorted({f"BDC/{e['mm_aaaa']}/{e['jj_mm']}" for e in hors_cible}))
        return True, (f"{nom} : deja present dans le {libelle(cible)} ({chemin_cible}) — "
                      f"exemplaire(s) de {autres} mis a la corbeille")
    if len(jours) > 1:
        return False, (f"{nom} : present dans plusieurs jours ({liste}) — "
                       f"a regler a la main sur Drive")

    chemin_source = liste
    de = libelle(jour_actuel) if jour_actuel else chemin_source

    try:
        mois_id = ap._get_or_create_subfolder(drive_svc, ap.DRIVE_BDC_FOLDER_ID, cible_mm_aaaa)
        dossier_cible = mois_id and ap._get_or_create_subfolder(drive_svc, mois_id, cible_jj_mm)
        if not dossier_cible:
            return False, f"{nom} : dossier Drive {chemin_cible} inaccessible"

        for e in exemplaires:
            drive_svc.files().update(
                fileId=e["file_id"],
                addParents=dossier_cible,
                removeParents=e["dossier_id"],
                fields="id,parents",
            ).execute()
    except Exception as e:
        return False, f"{nom} : deplacement {chemin_source} -> {chemin_cible} echoue ({e})"

    return True, f"{nom} : deplace du {de} au {libelle(cible)} ({chemin_source} -> {chemin_cible})"


def supprimer(drive_svc, numero, *_ignores, **_ignores_nommes):
    """Met a la corbeille Drive (restaurable) tous les exemplaires de
    BonDeCommande_NUMERO.pdf archives dans BDC/MM_AAAA/JJ_MM. Les parametres
    de date cible (meme signature que deplacer()) sont ignores.

    Retourne (ok, message), comme deplacer()."""
    nom = f"BonDeCommande_{numero}.pdf"
    try:
        exemplaires = localiser_bdc(drive_svc, numero)
    except Exception as e:
        return False, f"{nom} : recherche sur Drive echouee ({e})"
    if not exemplaires:
        return False, f"{nom} : introuvable dans l'archive Drive BDC"
    chemins = ", ".join(sorted({f"BDC/{e['mm_aaaa']}/{e['jj_mm']}" for e in exemplaires}))
    try:
        for e in exemplaires:
            drive_svc.files().update(fileId=e["file_id"], body={"trashed": True}).execute()
    except Exception as e:
        return False, f"{nom} : suppression ({chemins}) echouee ({e})"
    return True, f"{nom} : supprime ({chemins}, mis a la corbeille Drive)"


# ─────────────────────────────────────────────────────────────────
# File d'attente (marqueurs Drive GITHUB/DeplacementsEnAttente)
# ─────────────────────────────────────────────────────────────────

DOSSIER_ATTENTE_NOM = "DeplacementsEnAttente"
# Contenu d'un marqueur demandant une suppression plutot qu'un deplacement (a
# la place de la date cible AAAA-MM-JJ).
SUPPRIMER = "SUPPRIMER"
_RE_MARQUEUR_ATTENTE = re.compile(r"^deplacer_(\d{6,})\.txt$")


def _dossier_attente(drive_svc, creer=True):
    """ID du dossier Drive GITHUB/DeplacementsEnAttente. None si absent et
    creer=False."""
    github_id = ap._get_or_create_subfolder(drive_svc, "root", "GITHUB")
    if not creer:
        res = drive_svc.files().list(
            q=(f"name='{DOSSIER_ATTENTE_NOM}' and '{github_id}' in parents "
               f"and mimeType='{MIME_DOSSIER}' and trashed=false"),
            fields="files(id)",
        ).execute()
        fichiers = res.get("files", [])
        return fichiers[0]["id"] if fichiers else None
    return ap._get_or_create_subfolder(drive_svc, github_id, DOSSIER_ATTENTE_NOM)


def deposer_marqueur_attente(drive_svc, numero, cible):
    """Depose (ou met a jour) le marqueur deplacer_NUMERO.txt dans
    GITHUB/DeplacementsEnAttente/, contenant la date cible deja resolue
    (AAAA-MM-JJ), ou SUPPRIMER pour une suppression. Une nouvelle demande sur
    le meme numero remplace la precedente."""
    folder_id = _dossier_attente(drive_svc)
    nom_fichier = f"deplacer_{numero}.txt"
    res = drive_svc.files().list(
        q=f"name='{nom_fichier}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    existant = res.get("files", [])
    tmp = os.path.join(ap.WORK_DIR, nom_fichier)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write((SUPPRIMER if cible == SUPPRIMER else cible.isoformat()) + "\n")
    try:
        media = MediaFileUpload(tmp, mimetype="text/plain", resumable=False)
        if existant:
            drive_svc.files().update(fileId=existant[0]["id"], media_body=media).execute()
        else:
            drive_svc.files().create(
                body={"name": nom_fichier, "parents": [folder_id]},
                media_body=media, fields="id",
            ).execute()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def lister_marqueurs_attente(drive_svc):
    """Marqueurs de deplacement en attente : liste de (file_id, numero, cible),
    cible etant une date, ou SUPPRIMER pour une suppression.
    Liste vide si le dossier n'existe pas encore (aucune demande a ce jour) ou
    si un marqueur est illisible (ignore plutot que de faire echouer le run)."""
    folder_id = _dossier_attente(drive_svc, creer=False)
    if not folder_id:
        return []
    res = drive_svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name)",
    ).execute()
    resultats = []
    for f in res.get("files", []):
        m = _RE_MARQUEUR_ATTENTE.match(f.get("name", ""))
        if not m:
            continue
        try:
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=f["id"]))
            done = False
            while not done:
                _, done = dl.next_chunk()
            contenu = buf.getvalue().decode("utf-8").strip()
            cible = SUPPRIMER if contenu.upper() == SUPPRIMER else date.fromisoformat(contenu)
        except Exception as e:
            print(f"    {f['name']} : lecture echouee, ignore ({e})")
            continue
        resultats.append((f["id"], m.group(1), cible))
    return resultats


def mettre_en_attente(drive_svc, numero, cible, jour_choisi="", date_saisie="", aujourd_hui=None):
    """Inscrit la demande de deplacement de BonDeCommande_NUMERO.pdf dans la
    file d'attente (marqueur Drive), pour un deplacement physique differe au
    soir (deplacer_commandes_attente.py). Meme resolution de date cible que
    deplacer(), mais aucun fichier BDC n'est touche ici.

    Retourne (ok, message), comme deplacer()."""
    aujourd_hui = aujourd_hui or datetime.now(ap._TZ).date()
    nom = f"BonDeCommande_{numero}.pdf"
    ok, cible, _exemplaires, _jours, erreur = _localiser_et_resoudre_cible(
        drive_svc, numero, cible, jour_choisi, date_saisie, aujourd_hui)
    if not ok:
        return False, erreur

    try:
        deposer_marqueur_attente(drive_svc, numero, cible)
    except Exception as e:
        return False, f"{nom} : mise en attente echouee ({e})"
    return True, (f"{nom} : deplacement vers le {libelle(cible)} enregistre, "
                  f"sera effectue ce soir (22h)")


def mettre_en_attente_suppression(drive_svc, numero, *_ignores, **_ignores_nommes):
    """Inscrit la demande de suppression de BonDeCommande_NUMERO.pdf dans la
    file d'attente (marqueur SUPPRIMER), pour une suppression differee au soir
    (deplacer_commandes_attente.py). Rien n'est supprime ici.

    Retourne (ok, message), comme deplacer()."""
    nom = f"BonDeCommande_{numero}.pdf"
    try:
        exemplaires = localiser_bdc(drive_svc, numero)
    except Exception as e:
        return False, f"{nom} : recherche sur Drive echouee ({e})"
    if not exemplaires:
        return False, f"{nom} : introuvable dans l'archive Drive BDC"
    try:
        deposer_marqueur_attente(drive_svc, numero, SUPPRIMER)
    except Exception as e:
        return False, f"{nom} : mise en attente echouee ({e})"
    return True, f"{nom} : suppression enregistree, sera effectuee ce soir (22h)"


def traiter_marqueur(drive_svc, numero, cible):
    """Applique une demande en attente : suppression si cible vaut SUPPRIMER,
    deplacement vers la date cible sinon. Retourne (ok, message)."""
    if cible == SUPPRIMER:
        return supprimer(drive_svc, numero)
    return deplacer(drive_svc, numero, cible)


def _parser_args(argv):
    valeurs = {"--numeros": "", "--jour": "", "--date": ""}
    for nom in valeurs:
        if nom in argv:
            i = argv.index(nom)
            if i + 1 < len(argv):
                valeurs[nom] = argv[i + 1]
    forcer = "--forcer" in argv
    suppr = "--supprimer" in argv
    return valeurs["--numeros"], valeurs["--jour"], valeurs["--date"], forcer, suppr


def _resume(lignes, forcer, suppr=False):
    """Recapitulatif visible sur la page du run GitHub Actions."""
    chemin = os.environ.get("GITHUB_STEP_SUMMARY")
    if not chemin:
        return
    try:
        with open(chemin, "a", encoding="utf-8") as f:
            titre = "Supprimer commandes" if suppr else "Deplacer commandes"
            if not forcer:
                titre += " (mise en attente)"
            f.write(f"## {titre}\n\n")
            for ok, message in lignes:
                f.write(f"- {'✅' if ok else '❌'} {message}\n")
    except OSError:
        pass


def main():
    texte_numeros, jour_choisi, date_saisie, forcer, suppr = _parser_args(sys.argv[1:])
    numeros = extraire_numeros(texte_numeros)
    if not numeros:
        print(f"Aucun numero de commande reconnu dans {texte_numeros!r} "
              f"(6 chiffres minimum, separes par des espaces ou des virgules).")
        sys.exit(1)

    aujourd_hui = datetime.now(ap._TZ).date()
    # Date saisie verifiee avant tout acces Drive : une faute de frappe ne
    # doit rien deplacer.
    cible = None
    if date_saisie.strip() and not suppr:
        cible = lire_date(date_saisie, aujourd_hui)
        if cible is None:
            print(f"Date cible invalide : {date_saisie!r} (attendu JJ/MM/AAAA ou JJ/MM).")
            sys.exit(1)

    os.makedirs(ap.WORK_DIR, exist_ok=True)
    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    ap._charger_config(drive_svc)

    if suppr:
        action = supprimer if forcer else mettre_en_attente_suppression
        verbe = "Suppression" if forcer else "Mise en attente de la suppression"
    else:
        action = deplacer if forcer else mettre_en_attente
        verbe = "Deplacement" if forcer else "Mise en attente du deplacement"
    print(f"\n{verbe} de {len(numeros)} commande(s) : {', '.join(numeros)}")
    resultats = []
    for numero in numeros:
        ok, message = action(drive_svc, numero, cible, jour_choisi, date_saisie, aujourd_hui)
        print(f"  {'OK ' if ok else 'ERREUR'} {message}")
        resultats.append((ok, message))

    _resume(resultats, forcer, suppr)
    if suppr and forcer:
        print("\nBons mis a la corbeille Drive (restaurables). Si les ventes / le CA "
              "du jour concerne ont deja ete calcules, relancer les workflows "
              "correspondants (generer_ventes, renseigne_ca, controle_stocks).")
    elif suppr:
        print("\nLa suppression aura lieu ce soir a 22h (workflow 'Deplacer commandes "
              "en attente'). Cocher aussi --forcer pour supprimer tout de suite.")
    elif forcer:
        print("\nSi les ventes / le CA d'un des jours concernes ont deja ete calcules, "
              "relancer les workflows correspondants (generer_ventes, renseigne_ca, "
              "controle_stocks) pour ces jours.")
    else:
        print("\nLe deplacement physique aura lieu ce soir a 22h (workflow "
              "'Deplacer commandes en attente'). Utiliser --forcer si la commande "
              "n'est pas encore preparee et doit etre deplacee tout de suite.")
    if not all(ok for ok, _ in resultats):
        sys.exit(1)


if __name__ == "__main__":
    main()
