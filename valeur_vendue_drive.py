#!/usr/bin/env python3
"""
Valeur vendue au Drive du jour : somme, sur tous les gencods vendus, de
(UVC vendues × prix de vente), le prix venant de la colonne « Prix Vte » de
l'export de stocks du matin du même jour (Archives/stocks/
stock_JJ_MM_AAAA_matin.xlsx).

Le résultat est inscrit dans le classeur Drive « CA DRIVE AAAA.xlsx »,
onglet « RÉALISATION », dans un tableau « VALEUR VENDUE DRIVE » placé sous
le tableau « NB COMMANDES DRIVE » (K58:R113, même disposition que le tableau
« CA MAGASIN » en A58:H113 : une ligne par semaine « S n », une colonne par
jour du lundi au samedi, totaux par semaine et par jour).

Le classeur est un .xlsx (pas un Google Sheets natif) : il est téléchargé,
seul le XML de l'onglet RÉALISATION est modifié (les autres parties du
fichier sont recopiées octet pour octet, pour ne rien perdre de la mise en
forme, des commentaires…), puis réimporté sous le même identifiant Drive.
"""
import io
import os
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

import controle_stocks as cs

ONGLET = "RÉALISATION"
TITRE_TABLEAU = "VALEUR VENDUE DRIVE"

# Tableau modèle (CA MAGASIN, A..H) et tableau cible (K..R), lignes 58 à 113.
COLS_MODELE = ["A", "B", "C", "D", "E", "F", "G", "H"]
COLS_CIBLE  = ["K", "L", "M", "N", "O", "P", "Q", "R"]
LIGNE_TITRE    = 58
LIGNE_JOURS    = 59
LIGNE_S1       = 60          # « S 1 » ; « S n » en ligne 59 + n
LIGNE_DERNIERE_SEMAINE = 112  # « S 53 »
LIGNE_TOTAL    = 113
LIGNE_FIN_SOMME_TOTAL = 111   # comme le modèle : SUM(B60:B111)

_NS  = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RNS = "http://schemas.openxmlformats.org/package/2006/relationships"
_ONS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ─────────────────────────────────────────────────────────────────
# Calcul
# ─────────────────────────────────────────────────────────────────

def lire_prix(chemin):
    """{gencod: prix de vente} depuis un export de stocks (colonne « Prix Vte »)."""
    ext = os.path.splitext(chemin)[1].lower()
    rows = cs._rows_depuis_xlsx(chemin) if ext in (".xlsx", ".xls") else cs._rows_depuis_csv(chemin)
    prix = {}
    idx_gencod = idx_prix = None
    for row in rows:
        if idx_gencod is None:
            norm = [c.strip().lower() for c in row]
            if "gencod" in norm:
                idx_gencod = norm.index("gencod")
                for i, h in enumerate(norm):
                    if re.match(r"prix\s*v", h):
                        idx_prix = i
                if idx_prix is None:
                    raise ValueError(f"Colonne 'Prix Vte' introuvable dans {chemin}.")
            continue
        if len(row) <= max(idx_gencod, idx_prix):
            continue
        g = row[idx_gencod].strip()
        if g.isdigit():
            g = g.lstrip("0").zfill(13)
        if not re.match(r"^\d{5,}$", g):
            continue
        try:
            prix[g] = float(row[idx_prix].strip().replace(",", ".").replace(" ", ""))
        except ValueError:
            pass
    if idx_gencod is None:
        raise ValueError(f"Colonne 'Gencod' introuvable dans {chemin}.")
    return prix


def calculer_valeur_vendue(ventes, prix):
    """Retourne (valeur arrondie au centime, [gencods vendus sans prix])."""
    total = 0.0
    sans_prix = []
    for gencod, qty in ventes.items():
        p = prix.get(gencod)
        if p is None:
            sans_prix.append(gencod)
            continue
        total += qty * p
    return round(total, 2), sorted(sans_prix)


# ─────────────────────────────────────────────────────────────────
# Écriture dans le .xlsx (XML de l'onglet uniquement)
# ─────────────────────────────────────────────────────────────────

def _chemin_onglet(zf, nom_onglet):
    cible = unicodedata.normalize("NFC", nom_onglet)
    rid = None
    for sh in ET.fromstring(zf.read("xl/workbook.xml")).iter(f"{{{_NS}}}sheet"):
        if unicodedata.normalize("NFC", sh.get("name", "")) == cible:
            rid = sh.get(f"{{{_ONS}}}id")
            break
    if rid is None:
        raise ValueError(f"Onglet « {nom_onglet} » introuvable dans le classeur.")
    for rel in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")).iter(f"{{{_RNS}}}Relationship"):
        if rel.get("Id") == rid:
            t = rel.get("Target", "").lstrip("/")
            return t if t.startswith("xl/") else f"xl/{t}"
    raise ValueError(f"Fichier de l'onglet « {nom_onglet} » introuvable.")


_RE_CELLULE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


def _cellules(contenu_ligne):
    """{colonne: (attributs, contenu interne ou None)} d'une ligne."""
    return {m.group(1): (m.group(3), m.group(4)) for m in _RE_CELLULE.finditer(contenu_ligne)}


def _style(attrs):
    m = re.search(r'\ss="(\d+)"', attrs or "")
    return f' s="{m.group(1)}"' if m else ""


def _nombre(contenu):
    m = re.search(r"<v>([^<]*)</v>", contenu or "")
    if not m or "<f" in (contenu or ""):
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _fmt(x):
    x = round(x, 2)
    return str(int(x)) if x == int(x) else repr(x)


def _col_idx(col):
    return cs._col_index(col)


def inscrire_valeur(xml_onglet, semaine, jour_idx, valeur):
    """Construit/met à jour le tableau K58:R113 dans le XML de l'onglet et y
    inscrit `valeur` pour la semaine ISO `semaine` (1..53) et le jour
    `jour_idx` (0 = lundi … 5 = samedi). Les valeurs déjà présentes dans le
    tableau sont conservées. Retourne le nouveau XML."""
    if not 1 <= semaine <= 53 or not 0 <= jour_idx <= 5:
        raise ValueError(f"Semaine {semaine} / jour {jour_idx} hors tableau.")

    lignes = {}
    for n in range(LIGNE_TITRE, LIGNE_TOTAL + 1):
        m = re.search(r'<row r="%d"([^>]*)>(.*?)</row>' % n, xml_onglet, re.S)
        if not m:
            raise ValueError(f"Ligne {n} absente de l'onglet {ONGLET}.")
        lignes[n] = m

    # Valeurs déjà saisies (L..Q, lignes des semaines)
    valeurs = {}
    for n in range(LIGNE_S1, LIGNE_DERNIERE_SEMAINE + 1):
        cells = _cellules(lignes[n].group(2))
        for j, col in enumerate(COLS_CIBLE[1:7]):
            if col in cells:
                v = _nombre(cells[col][1])
                if v is not None:
                    valeurs[(n, j)] = v
    valeurs[(LIGNE_S1 + semaine - 1, jour_idx)] = round(valeur, 2)

    def somme_ligne(n):
        return sum(valeurs.get((n, j), 0.0) for j in range(6))

    def somme_jour(j):
        return sum(valeurs.get((n, j), 0.0) for n in range(LIGNE_S1, LIGNE_FIN_SOMME_TOTAL + 1))

    morceaux = []
    pos = 0
    for n in range(LIGNE_TITRE, LIGNE_TOTAL + 1):
        m = lignes[n]
        cells = _cellules(m.group(2))
        modele = {c: cells.get(c, ("", None)) for c in COLS_MODELE}
        nouvelles = {}
        for k, (cm, cc) in enumerate(zip(COLS_MODELE, COLS_CIBLE)):
            attrs, contenu = modele[cm]
            s = _style(attrs)
            ref = f"{cc}{n}"
            if n == LIGNE_TITRE:
                if k == 0:
                    nouvelles[cc] = (f'<c r="{ref}"{s} t="inlineStr"><is><t>{TITRE_TABLEAU}</t></is></c>')
                else:
                    nouvelles[cc] = f'<c r="{ref}"{s}/>'
            elif n == LIGNE_JOURS or (k == 0):
                # En-têtes des jours / libellés « S n » / « Total » : recopie du modèle
                t = re.search(r'\st="[^"]*"', attrs or "")
                t = t.group(0) if t else ""
                if contenu is None or "<f" in contenu:
                    nouvelles[cc] = f'<c r="{ref}"{s}/>'
                else:
                    nouvelles[cc] = f'<c r="{ref}"{s}{t}>{contenu}</c>'
            elif n == LIGNE_TOTAL:
                if k == 7:
                    tot = sum(somme_jour(j) for j in range(6))
                    f = f"SUM({COLS_CIBLE[1]}{n}:{COLS_CIBLE[6]}{n})"
                else:
                    tot = somme_jour(k - 1)
                    f = f"SUM({cc}{LIGNE_S1}:{cc}{LIGNE_FIN_SOMME_TOTAL})"
                nouvelles[cc] = f'<c r="{ref}"{s}><f>{f}</f><v>{_fmt(tot)}</v></c>'
            elif k == 7:
                f = f"SUM({COLS_CIBLE[1]}{n}:{COLS_CIBLE[6]}{n})"
                nouvelles[cc] = f'<c r="{ref}"{s}><f>{f}</f><v>{_fmt(somme_ligne(n))}</v></c>'
            else:
                v = valeurs.get((n, k - 1))
                nouvelles[cc] = (f'<c r="{ref}"{s}><v>{_fmt(v)}</v></c>' if v is not None
                                 else f'<c r="{ref}"{s}/>')

        # Fusion : cellules existantes hors K..R + nouvelles, triées par colonne
        conservees = [(mm.group(1), mm.group(0)) for mm in _RE_CELLULE.finditer(m.group(2))
                      if mm.group(1) not in COLS_CIBLE]
        toutes = conservees + list(nouvelles.items())
        toutes.sort(key=lambda x: _col_idx(x[0]))
        attrs_ligne = re.sub(r'\sspans="[^"]*"', "", m.group(1))
        morceaux.append(xml_onglet[pos:m.start()])
        morceaux.append(f'<row r="{n}"{attrs_ligne}>' + "".join(x[1] for x in toutes) + "</row>")
        pos = m.end()
    morceaux.append(xml_onglet[pos:])
    xml = "".join(morceaux)

    # Fusion du titre K58:R58
    fusion = f"{COLS_CIBLE[0]}{LIGNE_TITRE}:{COLS_CIBLE[-1]}{LIGNE_TITRE}"
    if f'<mergeCell ref="{fusion}"/>' not in xml:
        if "<mergeCells" in xml:
            xml = re.sub(r'<mergeCells count="(\d+)">',
                         lambda mm: f'<mergeCells count="{int(mm.group(1)) + 1}"><mergeCell ref="{fusion}"/>',
                         xml, count=1)
        else:
            xml = xml.replace("</sheetData>",
                              f'</sheetData><mergeCells count="1"><mergeCell ref="{fusion}"/></mergeCells>', 1)
    return xml


def modifier_classeur(contenu_xlsx, jour, valeur=None):
    """Retourne les octets du .xlsx avec la valeur du jour inscrite.
    `jour` peut aussi être un dict {date: valeur} pour inscrire plusieurs jours."""
    valeurs = jour if isinstance(jour, dict) else {jour: valeur}
    with zipfile.ZipFile(io.BytesIO(contenu_xlsx)) as zin:
        chemin = _chemin_onglet(zin, ONGLET)
        xml = zin.read(chemin).decode("utf-8")
        for j, v in sorted(valeurs.items()):
            xml = inscrire_valeur(xml, j.isocalendar()[1], j.weekday(), v)
        sortie = io.BytesIO()
        with zipfile.ZipFile(sortie, "w") as zout:
            for info in zin.infolist():
                data = xml.encode("utf-8") if info.filename == chemin else zin.read(info.filename)
                zout.writestr(info, data, compress_type=info.compress_type)
    return sortie.getvalue()


# ─────────────────────────────────────────────────────────────────
# Drive
# ─────────────────────────────────────────────────────────────────

def _trouver_classeur(svc, annee):
    fichier = f"CA DRIVE {annee}.xlsx"
    res = svc.files().list(
        q=f"name='{fichier}' and trashed=false",
        fields="files(id,name,modifiedTime)", orderBy="modifiedTime desc",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if not files:
        raise FileNotFoundError(f"« {fichier} » introuvable sur Drive.")
    return files[0]["id"], fichier


def inscrire_dans_ca_drive(jour, valeur=None):
    """Inscrit `valeur` pour `jour` (ou un dict {date: valeur}) dans
    « CA DRIVE <année ISO>.xlsx », en un seul aller-retour par classeur."""
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    valeurs = jour if isinstance(jour, dict) else {jour: valeur}
    for j in [j for j in valeurs if j.weekday() == 6]:
        print(f"  {j.strftime('%d/%m/%Y')} (dimanche) : pas de colonne, rien inscrit.")
        del valeurs[j]
    if not valeurs:
        return
    svc = cs._get_drive_service()
    if not svc:
        raise RuntimeError("Drive inaccessible.")
    par_annee = {}
    for j, v in valeurs.items():
        par_annee.setdefault(j.isocalendar()[0], {})[j] = v
    for annee, vals in sorted(par_annee.items()):
        file_id, fichier = _trouver_classeur(svc, annee)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        nouveau = modifier_classeur(buf.getvalue(), vals)
        media = MediaIoBaseUpload(io.BytesIO(nouveau), mimetype=_MIME_XLSX, resumable=False)
        svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        for j, v in sorted(vals.items()):
            print(f"  {fichier} / {ONGLET} : S {j.isocalendar()[1]}, "
                  f"{_JOURS[j.weekday()]} {j.strftime('%d/%m')} = {v:.2f} €")


_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _valeur_du_jour(jour, ventes):
    nom_stock = cs.nom_archive_stock(jour, "matin")
    os.makedirs(cs.WORK_DIR, exist_ok=True)
    chemin = cs.telecharger_fichier_archive(
        "stocks", nom_stock, os.path.join(cs.WORK_DIR, nom_stock),
        root_id=cs.DRIVE_CONFIG_FOLDER_ID)
    if not chemin:
        raise FileNotFoundError(f"Archives/stocks/{nom_stock} introuvable sur Drive.")
    prix = lire_prix(chemin)
    valeur, sans_prix = calculer_valeur_vendue(ventes, prix)
    print(f"\nValeur vendue au Drive du {jour.strftime('%d/%m/%Y')} : {valeur:.2f} € "
          f"({len(ventes)} gencods, prix de {nom_stock})")
    if sans_prix:
        print(f"  {len(sans_prix)} gencod(s) vendu(s) sans prix dans {nom_stock} "
              f"(non valorisés) : {', '.join(sans_prix[:20])}{' …' if len(sans_prix) > 20 else ''}")
    return valeur


def traiter(jour, ventes):
    """Calcule la valeur vendue du jour et l'inscrit dans CA DRIVE.
    Retourne la valeur. Lève une exception en cas d'échec."""
    valeur = _valeur_du_jour(jour, ventes)
    inscrire_dans_ca_drive(jour, valeur)
    return valeur


def rattraper(du, au):
    """Rattrapage du..au (inclus, lundi–samedi) depuis les ventes archivées
    (Archives/ventes/ventes_JJ_MM.csv) : aucun recalcul depuis les BDC.
    Retourne la liste des jours non traités."""
    from datetime import timedelta
    valeurs, manquants = {}, []
    os.makedirs(cs.WORK_DIR, exist_ok=True)
    j = du
    while j <= au:
        if j.weekday() != 6:
            nom_csv = f"ventes_{j.strftime('%d_%m')}.csv"
            chemin = cs.telecharger_fichier_archive(
                "ventes", nom_csv, os.path.join(cs.WORK_DIR, nom_csv),
                root_id=cs.DRIVE_CONFIG_FOLDER_ID)
            try:
                if not chemin:
                    raise FileNotFoundError(f"Archives/ventes/{nom_csv} introuvable.")
                ventes, _ = cs._charger_ventes_csv(chemin)
                valeurs[j] = _valeur_du_jour(j, ventes)
            except Exception as e:
                print(f"  {j.strftime('%d/%m/%Y')} non traité : {e}")
                manquants.append(j)
        j += timedelta(days=1)
    print(f"\n{len(valeurs)} jour(s) à inscrire, {len(manquants)} non traité(s).")
    inscrire_dans_ca_drive(valeurs)
    return manquants


def _parse_date(texte):
    jj, mm, aaaa = texte.split("/")
    return date(int(aaaa), int(mm), int(jj))


def main():
    import argparse
    p = argparse.ArgumentParser(description="Rattrapage de la valeur vendue au Drive.")
    p.add_argument("--du", required=True, help="JJ/MM/AAAA")
    p.add_argument("--au", required=True, help="JJ/MM/AAAA")
    a = p.parse_args()
    cs._charger_config()
    manquants = rattraper(_parse_date(a.du), _parse_date(a.au))
    if manquants:
        print("Jours non traités : " + ", ".join(j.strftime("%d/%m/%Y") for j in manquants))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
