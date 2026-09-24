#!/usr/bin/env python3
"""
Envoie par mail l'anticipation d'un jour : lit une seule fois le brouillon
bon_anticipation_JJ_MM.txt tenu a jour au fil de l'eau par
assembler_anticipation.py sur Drive (GITHUB/Anticipation/MM_AAAA/JJ_MM),
genere le PDF a partir de cette lecture, l'archive et l'envoie. Le PDF
brouillon deja present sur Drive n'est pas repris tel quel : l'assembleur
pouvait le reecrire pendant l'envoi, et une commande assemblee a ce moment-la
etait notee comme envoyee puis effacee sans etre partie dans le mail.

Avant de generer ce PDF, applique une derniere fois les annulations en
attente sur le dossier du jour (appliquer_annulations_jour) : c'est la seule
etape de la chaine qui ne depende d'aucun repository_dispatch, donc le filet
qui garantit qu'une commande annulee ou remplacee ne parte jamais dans le PDF
envoye (l'ancien et le nouveau numero d'une commande modifiee s'y retrouvaient
en double quand le retrait n'avait pas abouti).

Ce module fournit aussi (utilisees par assembler_anticipation.py, qui fait le
calcul reel a chaque commande, et par retirer_anticipation.py) le parsing de
bon_anticipation_JJ_MM.txt, le regroupement par lettre d'anticipation, la
generation du PDF (un rayon par page) et le retrait des commandes annulees.

La generation du PDF (publier_pdf_jour) ajoute au passage a la page BVP les 4
baguettes tradition du Drive, qui ne viennent d'aucune commande client — mais
seulement quand le PDF est genere le jour meme de son anticipation : une
anticipation lancee la veille pour le lendemain ne les contient pas, sans quoi
elles seraient preparees une seconde fois avec l'anticipation du lendemain.
"""

import base64
import io
import os
import re
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import auto_prepa as ap

_TZ = ZoneInfo("Europe/Paris")

# Photos produits : servies par nom de gencod, extension inconnue a priori.
_VISUELS_BASE_URL = "http://enbmobile.nl/mobUDrive/visuels/"
_PHOTO_EXTENSIONS = (".jpg", ".png")

# Lettres d'anticipation dont le rayon est connu : format PDF dedie (photo,
# code-barres, prix, ...). Les lettres absentes d'ici (rayon pas encore
# defini) sont ignorees (pas de PDF possible pour elles).
RAYONS_LETTRE = {
    "A": "Bazar",
    "B": "Boucherie",
    "C": "BVP",
    "D": "Poissonnerie",
    "G": "Traiteur chaud",
}

# Ordre des rayons dans le PDF (une page par rayon) : la BVP d'abord, puis la
# boucherie, le bazar, le traiteur chaud et la poissonnerie. Une lettre absente
# d'ici passe apres, par ordre alphabetique.
_ORDRE_RAYONS_PDF = ("C", "B", "A", "G", "D")

# Rayons dont le format PDF affiche systematiquement poids/qte + prix + prix/kg
# par ligne de commande (comme la Boucherie) : cf. avec_poids/poids_variable
# dans _elements_rayon.
_LETTRES_AVEC_POIDS_SYSTEMATIQUE = ("B", "D")

# Rayons dont le PDF consacre une ligne du tableau a chaque commande au lieu de
# regrouper un meme produit sur une seule ligne : la Boucherie prepare commande
# par commande, contrairement aux autres rayons qui ramassent par produit.
# Doit rester un sous-ensemble de _LETTRES_AVEC_POIDS_SYSTEMATIQUE (le format
# de ces lignes suppose la colonne Poids).
_LETTRES_UNE_LIGNE_PAR_COMMANDE = ("B",)


# Baguettes tradition du Drive : 4 pieces ajoutees d'office a la page BVP de
# chaque anticipation du jour, sans etre liees a une vraie commande client
# (commande "Drive", heure fixe 7h30 comme le reste de la page). Uniquement
# l'anticipation du jour lancee ce meme jour (cf. _est_anticipation_du_jour) :
# un envoi anticipe la veille (ex. a 12h55 pour les commandes du lendemain)
# ne les porte pas, elles sont pour l'anticipation du lendemain. Elles sont
# injectees a la generation du PDF (cf. _ajouter_baguettes_drive), pas dans
# bon_anticipation_JJ_MM.txt : le PDF etant regenere a chaque commande
# assemblee comme a chaque annulation, les stocker dans le brouillon les
# empilerait a chaque passage.
_LETTRE_BAGUETTES_DRIVE = "C"
_GENCOD_BAGUETTE_DRIVE  = "2000000286235"
_LIBELLE_BAGUETTE_DRIVE = "Baguette tradition française à base de farine LABEL ROUGE, 1 pièce, 250g"
_PRIX_BAGUETTE_DRIVE    = "1,05"
_QTE_BAGUETTES_DRIVE    = 4
_HEURE_BAGUETTES_DRIVE  = "07:30"
_COMMANDE_BAGUETTES_DRIVE = "Drive"


# Format des lignes de bon_anticipation.txt (16 champs separes par ';') :
# 0 gencod ; 1 libelle ; 2 prix ; 3 prix au kg/L ; 4 qte ; 5 substitution ;
# 6 poids (nombre decimal, utilise pour la lettre B/Boucherie) ; 7-8 sans
# interet ; 9 jour de commande + heure + autres infos ; 10 sacs ;
# 11 adresse ; 12-14 sans interet ; 15 (dernier champ) lettre d'anticipation
_IDX_GENCOD  = 0
_IDX_LIBELLE = 1
_IDX_PRIX    = 2
_IDX_PRIX_KG = 3
_IDX_QTE     = 4
_IDX_POIDS   = 6
_IDX_JOUR_HEURE = 9
_IDX_ADRESSE = 11
_NB_CHAMPS_MIN = 16

_RE_LEADING_SEQ = re.compile(r'^(?:-\d+)?;(\d{13};)')
_RE_HEURE = re.compile(r'([01]?\d|2[0-3])[:h]([0-5]\d)')


def _parser_lignes_anticipation(contenu, numero_commande):
    """Parse le contenu d'un bon_anticipation.txt et ne garde que les champs utiles.

    Retourne une liste de dicts : commande, gencod, libelle, prix, qte, poids,
    heure, adresse, lettre.
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
        heure = f"{int(m_heure.group(1)):02d}:{m_heure.group(2)}" if m_heure else ""

        produits.append({
            "commande": numero_commande,
            "gencod":   champs[_IDX_GENCOD].strip(),
            "libelle":  champs[_IDX_LIBELLE].strip(),
            "prix":     champs[_IDX_PRIX].strip(),
            "prix_kg":  champs[_IDX_PRIX_KG].strip(),
            "qte":      champs[_IDX_QTE].strip(),
            "poids":    champs[_IDX_POIDS].strip(),
            "heure":    heure,
            "adresse":  champs[_IDX_ADRESSE].strip(),
            "lettre":   champs[-1].strip().upper() or "?",
        })
    return produits


_RE_MARQUEUR_CDE = re.compile(r'^#CDE:(\S+)\s*$')


def _commandes_deja_assemblees(contenu_jour):
    """Numeros de commande deja marques '#CDE:NUMERO' dans bon_anticipation_JJ_MM.txt."""
    marqueurs = set()
    for ligne in contenu_jour.splitlines():
        m = _RE_MARQUEUR_CDE.match(ligne.strip())
        if m:
            marqueurs.add(m.group(1))
    return marqueurs


def _parser_lignes_anticipation_jour(contenu):
    """Parse bon_anticipation_JJ_MM.txt, assemble au fil de l'eau par
    assembler_anticipation.py : succession de blocs '#CDE:NUMERO' suivis des
    lignes de bon_anticipation.txt de cette commande. Reutilise
    _parser_lignes_anticipation par bloc et retourne la liste consolidee de
    tous les produits, toutes commandes confondues."""
    produits = []
    numero_courant = None
    bloc = []

    def _flush():
        if numero_courant is not None and bloc:
            produits.extend(_parser_lignes_anticipation("\n".join(bloc), numero_courant))

    for ligne in contenu.splitlines():
        m = _RE_MARQUEUR_CDE.match(ligne)
        if m:
            _flush()
            numero_courant = m.group(1)
            bloc = []
        else:
            bloc.append(ligne)
    _flush()
    return produits


def _telecharger_texte(drive_svc, file_id):
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8", errors="replace")


_RE_BON_ANTICIPATION_CDE = re.compile(r'^bon_anticipation_(\d+)\.txt$')


def _lister_bons_commande(drive_svc, jour_id):
    """Retourne [(file_id, numero), ...] des bon_anticipation_NUMERO.txt
    (fichiers individuels par commande, jamais supprimes tant que l'anticipation
    du jour n'a pas ete envoyee par mail — cf. _reinitialiser_dossier_jour_anticipation)
    presents dans ce dossier jour — distincts de bon_anticipation_JJ_MM.txt
    (l'assemblage)."""
    res = drive_svc.files().list(
        q=(f"'{jour_id}' in parents and trashed=false "
           f"and name contains 'bon_anticipation_'"),
        fields="files(id,name)",
        pageSize=1000,
    ).execute()
    resultat = []
    for f in res.get("files", []):
        m = _RE_BON_ANTICIPATION_CDE.match(f["name"])
        if m:
            resultat.append((f["id"], m.group(1)))
    return resultat


def _telecharger_photo(gencod, cache, erreurs=None):
    """Recupere la photo produit (jpg ou png) depuis enbmobile.nl/mobUDrive/visuels/.

    Retourne les octets de l'image, ou None si introuvable. Resultat mis en
    cache par gencod pour eviter de re-telecharger le meme visuel plusieurs
    fois dans un meme PDF. Si erreurs est fourni, la derniere exception
    rencontree pour ce gencod y est ajoutee (diagnostic : sans ca, une photo
    manquante est indistinguable en sortie qu'il s'agisse d'un visuel
    inexistant ou d'une panne reseau/serveur - les deux sont avales ici en
    silence pour ne jamais faire echouer la generation du PDF)."""
    if gencod in cache:
        return cache[gencod]
    derniere_erreur = None
    for ext in _PHOTO_EXTENSIONS:
        url = f"{_VISUELS_BASE_URL}{gencod}{ext}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            cache[gencod] = data
            return data
        except Exception as e:
            derniere_erreur = e
            continue
    cache[gencod] = None
    if erreurs is not None and derniere_erreur is not None:
        erreurs.append(f"{gencod} : {derniere_erreur}")
    return None


def _charger_ordre_chemin_prepa(drive_svc):
    """Telecharge chemin_prepa_ramasse.csv (config Drive) : une adresse par
    ligne, dans l'ordre du chemin de preparation. Retourne {adresse: index}."""
    if not ap.DRIVE_CONFIG_FOLDER_ID:
        return {}
    try:
        res = drive_svc.files().list(
            q=(f"name='chemin_prepa_ramasse.csv' and '{ap.DRIVE_CONFIG_FOLDER_ID}' "
               f"in parents and trashed=false"),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if not files:
            print("  chemin_prepa_ramasse.csv introuvable sur Drive — tri par chemin de prepa ignore.")
            return {}
        contenu = _telecharger_texte(drive_svc, files[0]["id"])
    except Exception as e:
        print(f"  Impossible de charger chemin_prepa_ramasse.csv : {e}")
        return {}

    ordre = {}
    for i, ligne in enumerate(contenu.splitlines()):
        adresse = ligne.strip()
        if adresse and adresse not in ordre:
            ordre[adresse] = i
    return ordre


def _grouper_produits(produits):
    """Regroupe les lignes portant le meme gencod (produit identique commande
    dans plusieurs commandes) : commande, quantite et heure sont empilees, le
    reste (libelle, prix, poids, adresse) est partage. Les lignes sont triees
    par heure de commande croissante. Retourne une liste de dicts {gencod,
    libelle, prix, poids, adresse, lignes: [(commande, qte, heure), ...]}."""
    groupes = {}
    ordre_gencods = []
    for p in produits:
        gencod = p["gencod"]
        if gencod not in groupes:
            groupes[gencod] = {
                "gencod":   gencod,
                "libelle":  p["libelle"],
                "prix":     p["prix"],
                "prix_kg":  p["prix_kg"],
                "poids":    p["poids"],
                "adresse":  p["adresse"],
                "lignes":   [],
            }
            ordre_gencods.append(gencod)
        groupes[gencod]["lignes"].append((p["commande"], p["qte"], p["heure"]))

    resultat = []
    for gencod in ordre_gencods:
        g = groupes[gencod]
        g["lignes"].sort(key=lambda t: (t[2], t[0]))
        resultat.append(g)
    return resultat


def _qte_totale(lignes):
    """Somme des quantites (commande, qte, heure) d'un groupe : la qte totale
    a collecter pour ce produit, tous clients confondus."""
    total = 0.0
    for _, q, _ in lignes:
        try:
            total += float(q.replace(',', '.'))
        except (TypeError, ValueError):
            pass
    if total.is_integer():
        return str(int(total))
    return f"{total:.2f}".replace('.', ',')


def _poids_ligne(qte, poids_unitaire):
    """qte * poids_unitaire (poids du produit pour cette commande), formate
    avec le meme separateur/nombre de decimales que poids_unitaire."""
    if not poids_unitaire:
        return ''
    try:
        qte_f = float(qte.replace(',', '.'))
        poids_f = float(poids_unitaire.replace(',', '.'))
    except (TypeError, ValueError):
        return poids_unitaire
    sep = ',' if ',' in poids_unitaire else '.'
    decimales = len(poids_unitaire.split(sep)[-1]) if sep in poids_unitaire else 3
    return f"{qte_f * poids_f:.{decimales}f}".replace('.', sep)


def _prix_ligne_poids(qte, poids_unitaire, prix_kg):
    """Prix reellement commande pour cette ligne (poids variable) : prix/kg *
    poids commande (qte * poids_unitaire), et non le prix indicatif partage
    par toutes les commandes du meme produit. Retourne '' si le calcul n'est
    pas possible (poids ou prix/kg manquant)."""
    if not poids_unitaire or not prix_kg:
        return ''
    try:
        qte_f = float(qte.replace(',', '.'))
        poids_f = float(poids_unitaire.replace(',', '.'))
        prix_kg_f = float(prix_kg.replace(',', '.'))
    except (TypeError, ValueError):
        return ''
    return f"{qte_f * poids_f * prix_kg_f:.2f}".replace('.', ',')


def _rang_rayon_pdf(lettre):
    """Cle de tri des rayons dans le PDF : l'ordre de _ORDRE_RAYONS_PDF, les
    lettres inconnues a la suite, par ordre alphabetique."""
    try:
        return (0, _ORDRE_RAYONS_PDF.index(lettre), lettre)
    except ValueError:
        return (1, 0, lettre)


def _generer_pdf_rayons(produits_pdf, dossier_jj_mm, date_complete, ordre_chemin):
    """Genere un unique PDF reunissant tous les rayons fournis (produits_pdf :
    {lettre: [produit, ...]}), chaque rayon demarrant en haut d'une nouvelle
    page, dans l'ordre de _ORDRE_RAYONS_PDF. Colonnes : quantite, photo, code-barres EAN13 + gencod, libelle,
    prix, numero de commande et heure (+ poids avant le prix pour la Boucherie
    et la Poissonnerie, qui ajoute une colonne Qte detaillee par commande). Un
    produit commande par plusieurs clients tient sur une seule ligne (quantite
    totale a collecter, commandes et heures empilees dans leur case), sauf en
    Boucherie ou chaque commande a sa propre ligne : ce rayon prepare commande
    par commande. Les lignes sont triees par heure de commande croissante
    (l'ordre du chemin de preparation, chemin_prepa_ramasse.csv via
    ordre_chemin, ne departage plus qu'a heure egale), celles d'un meme produit
    restant groupees. Retourne le chemin local du PDF, ou None si reportlab est
    indisponible / produits_pdf est vide."""
    if not produits_pdf:
        return None

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.graphics.barcode import createBarcodeDrawing
        from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                        SimpleDocTemplate, Spacer, Table, TableStyle)
    except Exception as e:
        print(f"  PDF anticipation ignore : {e}")
        return None

    small    = ParagraphStyle('small', fontSize=8, leading=10)
    # Quantite a ramasser : le chiffre le plus lu du tableau, donc en gros et
    # en gras. Centree par son propre style : l'ALIGN du TableStyle ne centre
    # que les cellules non textuelles (photo, code-barres), un Paragraph
    # occupant toute la largeur de sa cellule.
    qte_s    = ParagraphStyle('qte', fontName='Helvetica-Bold', fontSize=16,
                              leading=19, alignment=1)
    small_c  = ParagraphStyle('small_c', fontSize=8, leading=8, alignment=1)
    header_s = ParagraphStyle('hdr', fontSize=8, leading=10, textColor=colors.white)
    tiny_c   = ParagraphStyle('tiny_c', fontSize=7, leading=8, alignment=1)
    titre_s  = ParagraphStyle('titre', fontName='Helvetica-Bold', fontSize=13,
                              leading=16, alignment=1)
    BLEU     = colors.HexColor('#006797')

    def _elements_rayon(produits, lettre, nom_rayon):
        groupes = _grouper_produits(produits)
        fin_chemin = len(ordre_chemin)
        groupes.sort(key=lambda g: (g["lignes"][0][2],
                                     ordre_chemin.get(g["adresse"], fin_chemin),
                                     g["gencod"]))

        elements = [
            Paragraph(f"Anticipation {nom_rayon} {date_complete} — À préparer avant 7h30",
                      titre_s),
            Spacer(1, 5 * mm),
        ]

        # Boucherie (lettre B) et Poissonnerie (lettre D) : colonne Poids en
        # plus, juste avant le Prix (_LETTRES_AVEC_POIDS_SYSTEMATIQUE). La
        # Boucherie va plus loin : une ligne du tableau par commande, donc pas
        # besoin d'une colonne Qte detaillee a cote du Prix
        # (_LETTRES_UNE_LIGNE_PAR_COMMANDE).
        avec_poids = lettre in _LETTRES_AVEC_POIDS_SYSTEMATIQUE
        par_commande = lettre in _LETTRES_UNE_LIGNE_PAR_COMMANDE
        largeur_code_barres = 95
        # Colonne Quantite un peu plus large que les autres bons : le chiffre
        # y est ecrit en 16 (cf. qte_s), une quantite au poids type "12,50"
        # ne tiendrait pas sur une seule ligne sinon. La largeur reprise vient
        # du Libelle, la colonne la plus large.
        if par_commande:
            col_widths = [56, 55, largeur_code_barres, 178, 45, 42, 57, 35]
            hdr_txts = ('Quantité', 'Photo', 'Code-barres', 'Libellé', 'Poids', 'Prix',
                        'Commande', 'Heure')
        elif avec_poids:
            col_widths = [56, 55, largeur_code_barres, 148, 45, 42, 30, 57, 35]
            hdr_txts = ('Quantité', 'Photo', 'Code-barres', 'Libellé', 'Poids', 'Prix',
                        'Qté', 'Commande', 'Heure')
        else:
            col_widths = [56, 55, largeur_code_barres, 222, 42, 57, 35]
            hdr_txts = ('Quantité', 'Photo', 'Code-barres', 'Libellé', 'Prix', 'Commande', 'Heure')
        derniere_col = len(hdr_txts) - 1
        # Derniere colonne couverte par la cellule Poids/Prix (+ Qte quand le
        # produit tient sur une seule ligne) : cf. _poids_prix_cell.
        derniere_col_poids = 5 if par_commande else 6

        hdr = [Paragraph(t, header_s) for t in hdr_txts]
        data = [hdr]

        cache_photos = {}
        erreurs_photos = []
        photos_trouvees = 0
        span_rows = []

        def _photo_cell(photo_bytes):
            """Cellule photo, recreee a chaque appel : un meme flowable ne peut
            pas etre place dans plusieurs cellules (produit repete d'une ligne
            de commande a l'autre en Boucherie/Poissonnerie)."""
            if not photo_bytes:
                return ''
            try:
                return RLImage(io.BytesIO(photo_bytes), width=18 * mm, height=18 * mm, kind='bound')
            except Exception:
                return ''

        def _bc_cell(gencod):
            """Code-barres EAN13 + gencod en clair dessous (recree a chaque
            appel, cf. _photo_cell)."""
            bc = None
            if len(gencod) == 13 and gencod.isdigit():
                try:
                    bc = createBarcodeDrawing('EAN13', value=gencod, width=largeur_code_barres, height=28,
                                              humanReadable=False)
                except Exception:
                    bc = None
            if not bc:
                return Paragraph(gencod, small)
            return Table(
                [[bc], [Paragraph(gencod, tiny_c)]],
                colWidths=[largeur_code_barres],
                style=TableStyle([
                    ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                    ('TOPPADDING',    (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                ]),
            )

        def _poids_prix_cell(poids_txt, prix_txt, prix_kg, qte_txt=None):
            """Poids et Prix cote a cote (+ Qte quand le rayon detaille les
            commandes empilees dans une seule ligne : sinon le VALIGN MIDDLE du
            tableau principal centre chaque bloc independamment sur sa propre
            hauteur, et les lignes Qte se decalent des lignes Poids/Prix, plus
            hautes d'une ligne a cause du prix/kg). Prix/kg centre en dessous
            sur une ligne fusionnee, comme annote a la main sur le bon
            d'origine."""
            haut = [Paragraph(poids_txt, small_c), Paragraph(prix_txt, small_c)]
            if qte_txt is not None:
                haut.append(Paragraph(qte_txt, small_c))
            derniere = len(haut) - 1
            return Table(
                [haut,
                 [Paragraph(f"{prix_kg} €/Kg", small_c)] + [''] * derniere],
                colWidths=col_widths[4:4 + len(haut)],
                style=TableStyle([
                    ('SPAN',          (0, 1), (derniere, 1)),
                    ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING',    (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                    # Ecarte legerement Poids/Prix (remontes) du prix/kg
                    # (descendu), sans agrandir la ligne : le leading de
                    # small_c a ete resserre d'autant.
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
                    ('TOPPADDING',    (0, 1), (-1, 1), 2),
                ]),
            )

        for g in groupes:
            gencod = g['gencod']

            photo_bytes = _telecharger_photo(gencod, cache_photos, erreurs_photos) if gencod else None
            if photo_bytes:
                photos_trouvees += 1

            if par_commande:
                # Boucherie : une ligne du tableau par commande, meme quand
                # plusieurs clients ont commande le meme produit (poids et prix
                # different d'un client a l'autre : poids = qte * poids
                # unitaire, prix = prix/kg * ce poids). Les lignes d'un meme
                # produit restent groupees, triees par heure de commande
                # croissante (cf. _grouper_produits).
                for commande, qte, heure in g['lignes']:
                    row = [Paragraph(qte, qte_s), _photo_cell(photo_bytes),
                           _bc_cell(gencod), Paragraph(g['libelle'], small)]
                    poids_txt = f"{_poids_ligne(qte, g['poids'])} Kg" if g['poids'] else ''
                    if g['poids'] and g['prix_kg']:
                        prix_txt = f"{_prix_ligne_poids(qte, g['poids'], g['prix_kg'])} €"
                        row.extend([_poids_prix_cell(poids_txt, prix_txt, g['prix_kg']), ''])
                        span_rows.append(len(data))
                    else:
                        row.extend([Paragraph(poids_txt, small), Paragraph('', small)])
                    row.append(Paragraph(commande, small))
                    row.append(Paragraph(heure, small))
                    data.append(row)
                continue

            # Autres rayons : une seule ligne par produit, quantite totale a
            # collecter tous clients confondus, commandes et heures empilees
            # dans leur case (triees par heure de commande croissante).
            row = [Paragraph(_qte_totale(g['lignes']), qte_s), _photo_cell(photo_bytes),
                   _bc_cell(gencod), Paragraph(g['libelle'], small)]
            if avec_poids:
                # Poissonnerie : le poids, le prix et la quantite restent
                # detailles par commande, empiles en face du numero de commande
                # correspondant.
                poids_txt = "<br/>".join("" if not g['poids'] else f"{_poids_ligne(q, g['poids'])} Kg"
                                         for _, q, _ in g['lignes'])
                prix_txt = "<br/>".join("" if not (g['poids'] and g['prix_kg'])
                                        else f"{_prix_ligne_poids(q, g['poids'], g['prix_kg'])} €"
                                        for _, q, _ in g['lignes'])
                qte_txt = "<br/>".join(q for _, q, _ in g['lignes'])
                if g['poids'] and g['prix_kg']:
                    row.extend([_poids_prix_cell(poids_txt, prix_txt, g['prix_kg'], qte_txt), '', ''])
                    span_rows.append(len(data))
                else:
                    row.extend([Paragraph(poids_txt, small), Paragraph(prix_txt, small),
                                Paragraph(qte_txt, small)])
            else:
                row.append(Paragraph(f"{g['prix']} €" if g['prix'] else '', small))
            # Commande(s) et heure(s) en fin de ligne : ce qui identifie le
            # client passe apres ce qu'il faut ramasser.
            row.append(Paragraph("<br/>".join(c for c, _, _ in g['lignes']), small))
            row.append(Paragraph("<br/>".join(h for _, _, h in g['lignes']), small))
            data.append(row)

        style = TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0), BLEU),
            ('FONTNAME',       (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',       (0, 0), (-1, 0), 8),
            ('ALIGN',          (0, 0), (-1, 0), 'CENTER'),
            ('FONTSIZE',       (0, 1), (-1, -1), 8),
            ('ALIGN',          (0, 1), (2, -1), 'CENTER'),
            ('ALIGN',          (4, 1), (derniere_col, -1), 'CENTER'),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF6FB')]),
            ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('TOPPADDING',     (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 6),
        ])
        # Prix/kg (Boucherie) : cellule Poids+Prix fusionnee sur la ligne ou
        # elle est affichee (cf. _poids_prix_cell ci-dessus).
        for idx in span_rows:
            style.add('SPAN', (4, idx), (derniere_col_poids, idx))

        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(style)
        elements.append(table)
        print(f"  {nom_rayon} (lettre {lettre}) : {len(groupes)} produit(s), "
              f"{len(produits)} ligne(s) commande, "
              f"{photos_trouvees}/{len(groupes)} photo(s) trouvee(s)")
        if erreurs_photos:
            print(f"    Photo(s) manquante(s) sur {_VISUELS_BASE_URL} "
                  f"- exemple d'erreur : {erreurs_photos[0]}")
        return elements

    nom_pdf = f"anticipation_{dossier_jj_mm}.pdf"
    doc = SimpleDocTemplate(nom_pdf, pagesize=A4,
                            topMargin=8 * mm, bottomMargin=8 * mm,
                            leftMargin=5 * mm, rightMargin=5 * mm)

    elements_total = []
    for i, lettre in enumerate(sorted(produits_pdf.keys(), key=_rang_rayon_pdf)):
        if i > 0:
            elements_total.append(PageBreak())
        elements_total.extend(_elements_rayon(produits_pdf[lettre], lettre, RAYONS_LETTRE[lettre]))

    doc.build(elements_total)
    print(f"  → {nom_pdf} ({len(produits_pdf)} rayon(s))")
    return nom_pdf


def _envoyer_email_resultat(gmail_svc, dossier_jj_mm, chemin_pdf):
    """Envoie par email le PDF d'anticipation du jour au destinataire
    configure sur Drive (config.json / email_destinataire)."""
    destinataire = ap.EMAIL_ANTICIPATION
    destinataire_cc = ap.EMAIL_ANTICIPATION_2
    if not destinataire:
        print("  Envoi email anticipation ignore : email_destinataire absent de config.json")
        return False
    if not chemin_pdf or not os.path.exists(chemin_pdf):
        return False

    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    try:
        msg = MIMEMultipart()
        msg["To"] = destinataire
        if destinataire_cc:
            msg["Cc"] = destinataire_cc
        msg["Subject"] = f"Anticipation {dossier_jj_mm}"
        msg.attach(MIMEText(
            f"Bonjour,\n\nCi-joint le resultat de l'anticipation du {dossier_jj_mm}.\n",
            "plain", "utf-8"))

        with open(chemin_pdf, "rb") as f:
            data = f.read()
        part = MIMEApplication(data, "pdf")
        part.add_header("Content-Disposition", "attachment", filename=os.path.basename(chemin_pdf))
        msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Email anticipation envoye => {destinataire} (cc: {destinataire_cc})")
        return True
    except Exception as e:
        print(f"  Envoi email anticipation echoue : {e}")
        return False


def _envoyer_email_commandes_orphelines(gmail_svc, dossier_jj_mm, numeros):
    """Alerte le destinataire configure qu'une ou plusieurs commandes
    anticipables n'ont jamais ete integrees au PDF d'anticipation du jour
    envoye (bon_anticipation_NUMERO.txt jamais assemble, probablement suite a
    un dispatch d'assemblage perdu, cf. _reinitialiser_dossier_jour_anticipation) —
    pour qu'elles soient traitees manuellement plutot que silencieusement
    perdues."""
    destinataire = ap.EMAIL_ANTICIPATION
    if not destinataire or not numeros:
        return
    from email.mime.text import MIMEText

    corps = (
        f"Bonjour,\n\n"
        f"La ou les commande(s) suivante(s) n'ont jamais ete integrees a "
        f"l'anticipation du {dossier_jj_mm} envoyee par email, malgre un bon "
        f"d'anticipation genere pour elles (bon_anticipation_NUMERO.txt) : "
        f"{', '.join(numeros)}.\n\n"
        f"Ces articles n'ont donc pas ete prepares a l'avance. Merci de "
        f"verifier manuellement ces commandes.\n"
    )
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["To"] = destinataire
        if ap.EMAIL_ANTICIPATION_2:
            msg["Cc"] = ap.EMAIL_ANTICIPATION_2
        msg["Subject"] = f"Anticipation {dossier_jj_mm} — commande(s) non integree(s)"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Email alerte commande(s) orpheline(s) envoye => {destinataire} : {', '.join(numeros)}")
    except Exception as e:
        print(f"  Envoi email alerte commande(s) orpheline(s) echoue : {e}")


def _envoyer_email_commandes_arrivees_pendant_envoi(gmail_svc, dossier_jj_mm, numeros):
    """Alerte : une ou plusieurs commandes ont ete assemblees dans le brouillon
    pendant l'envoi de l'anticipation du jour, trop tard pour figurer dans le
    PDF envoye. Elles restent dans le brouillon (rien n'est perdu) : il suffit
    de relancer l'anticipation de ce jour pour les envoyer."""
    destinataire = ap.EMAIL_ANTICIPATION
    if not destinataire or not numeros:
        return
    from email.mime.text import MIMEText

    corps = (
        f"Bonjour,\n\n"
        f"La ou les commande(s) suivante(s) sont arrivees pendant l'envoi de "
        f"l'anticipation du {dossier_jj_mm} et ne figurent PAS dans le PDF "
        f"envoye : {', '.join(numeros)}.\n\n"
        f"Elles sont conservees : relancer l'anticipation du {dossier_jj_mm} "
        f"pour les envoyer.\n"
    )
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["To"] = destinataire
        if ap.EMAIL_ANTICIPATION_2:
            msg["Cc"] = ap.EMAIL_ANTICIPATION_2
        msg["Subject"] = f"Anticipation {dossier_jj_mm} — commande(s) a relancer"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Email alerte commande(s) arrivee(s) pendant l'envoi envoye => "
              f"{destinataire} : {', '.join(numeros)}")
    except Exception as e:
        print(f"  Envoi email alerte commande(s) arrivee(s) pendant l'envoi echoue : {e}")


def _envoyer_email_annulees_rattrapees(gmail_svc, dossier_jj_mm, numeros):
    """Alerte : une ou plusieurs commandes annulees etaient encore presentes
    dans le brouillon d'anticipation au moment de l'envoi, et n'ont ete
    retirees que par le filet de securite de ce workflow (le retrait normal,
    declenche des l'annulation, n'a donc pas fait son office). Le PDF envoye
    est correct, mais l'alerte permet de voir que la chaine a du etre
    rattrapee."""
    destinataire = ap.EMAIL_ANTICIPATION
    if not destinataire or not numeros:
        return
    from email.mime.text import MIMEText

    corps = (
        f"Bonjour,\n\n"
        f"La ou les commande(s) suivante(s), annulee(s) ou remplacee(s), "
        f"etaient encore presentes dans le brouillon d'anticipation du "
        f"{dossier_jj_mm} : {', '.join(numeros)}.\n\n"
        f"Elles ont ete retirees avant l'envoi : le PDF ci-joint ne les "
        f"contient pas. Aucune action necessaire, ce message signale "
        f"seulement que le retrait automatique n'avait pas abouti en amont.\n"
    )
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["To"] = destinataire
        if ap.EMAIL_ANTICIPATION_2:
            msg["Cc"] = ap.EMAIL_ANTICIPATION_2
        msg["Subject"] = f"Anticipation {dossier_jj_mm} — commande(s) annulee(s) retiree(s) in extremis"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Email alerte commande(s) annulee(s) rattrapee(s) envoye => {destinataire} : "
              f"{', '.join(numeros)}")
    except Exception as e:
        print(f"  Envoi email alerte commande(s) annulee(s) rattrapee(s) echoue : {e}")


def _cle_tri_commande(numero):
    """Tri numerique quand possible (numeros de commande), alphabetique sinon."""
    return (0, int(numero)) if numero.isdigit() else (1, numero)


def _maj_fichier_numeros_archive(drive_svc, commandes, dossier_mm_aaaa, dossier_jj_mm,
                                 nom_fichier):
    """Note dans GITHUB/Anticipation/archives/MM_AAAA/JJ_MM/nom_fichier
    (separateur virgule) les numeros de commande passes en argument. Si le
    fichier existe deja (plusieurs anticipations dans la journee pour ce meme
    JJ_MM : J, J+1, ...), son contenu est fusionne avec commandes plutot
    qu'ecrase."""
    if not commandes:
        return

    path = f"GITHUB/Anticipation/archives/{dossier_mm_aaaa}/{dossier_jj_mm}"
    try:
        github_id = ap._get_or_create_subfolder(drive_svc, "root", "GITHUB")
        anticipation_id = ap._get_or_create_subfolder(drive_svc, github_id, "Anticipation")
        archives_id = ap._get_or_create_subfolder(drive_svc, anticipation_id, "archives")
        mois_id = ap._get_or_create_subfolder(drive_svc, archives_id, dossier_mm_aaaa)
        subfolder_id = ap._get_or_create_subfolder(drive_svc, mois_id, dossier_jj_mm)

        res = drive_svc.files().list(
            q=f"name='{nom_fichier}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])

        deja_notees = set()
        if existing:
            contenu = _telecharger_texte(drive_svc, existing[0]["id"])
            deja_notees = {c.strip() for c in contenu.strip().split(',') if c.strip()}

        toutes = sorted(deja_notees | set(commandes), key=_cle_tri_commande)
        nouveau_contenu = ",".join(toutes)

        chemin_local = os.path.join(ap.WORK_DIR, nom_fichier)
        os.makedirs(ap.WORK_DIR, exist_ok=True)
        with open(chemin_local, "w", encoding="utf-8") as f:
            f.write(nouveau_contenu)
        try:
            media = MediaFileUpload(chemin_local, mimetype="text/plain", resumable=False)
            if existing:
                drive_svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            else:
                drive_svc.files().create(
                    body={"name": nom_fichier, "parents": [subfolder_id]},
                    media_body=media,
                    fields="id",
                ).execute()
        finally:
            os.remove(chemin_local)
        print(f"    {nom_fichier} => Drive {path}/ OK ({len(toutes)} commande(s) au total)")
    except Exception as e:
        print(f"    Mise a jour {nom_fichier} echouee : {e}")


def _maj_fichier_commandes_anticipees(drive_svc, commandes, dossier_mm_aaaa, dossier_jj_mm):
    """Commandes presentes dans le BROUILLON d'anticipation du jour
    (commandes_anticipées_JJ_MM.txt), tenu a jour a chaque assemblage."""
    _maj_fichier_numeros_archive(drive_svc, commandes, dossier_mm_aaaa, dossier_jj_mm,
                                 f"commandes_anticipées_{dossier_jj_mm}.txt")


def _maj_fichier_commandes_envoyees(drive_svc, commandes, dossier_mm_aaaa, dossier_jj_mm):
    """Commandes reellement PARTIES par mail a l'equipe dans l'anticipation du
    jour (commandes_envoyées_JJ_MM.txt) : seule cette liste, et non le
    brouillon, justifie l'alerte d'auto_prepa.py quand l'une d'elles est
    annulee ensuite (_alerter_si_commande_anticipee_annulee). Cumulative, pour
    couvrir les jours ou plusieurs anticipations sont envoyees (J, J+1, ...)."""
    _maj_fichier_numeros_archive(drive_svc, commandes, dossier_mm_aaaa, dossier_jj_mm,
                                 f"commandes_envoyées_{dossier_jj_mm}.txt")


def _retirer_commandes_fichier_anticipees(drive_svc, numeros_a_retirer, dossier_mm_aaaa, dossier_jj_mm):
    """Retire numeros_a_retirer de GITHUB/Anticipation/archives/MM_AAAA/JJ_MM/
    commandes_anticipées_JJ_MM.txt (symetrique de _maj_fichier_commandes_anticipees) :
    ces commandes, annulees, ne font plus partie de l'anticipation du jour."""
    if not numeros_a_retirer:
        return

    nom_fichier = f"commandes_anticipées_{dossier_jj_mm}.txt"
    path = f"GITHUB/Anticipation/archives/{dossier_mm_aaaa}/{dossier_jj_mm}"
    try:
        github_id = ap._get_or_create_subfolder(drive_svc, "root", "GITHUB")
        anticipation_id = ap._get_or_create_subfolder(drive_svc, github_id, "Anticipation")
        archives_id = ap._get_or_create_subfolder(drive_svc, anticipation_id, "archives")
        mois_id = ap._get_or_create_subfolder(drive_svc, archives_id, dossier_mm_aaaa)
        subfolder_id = ap._get_or_create_subfolder(drive_svc, mois_id, dossier_jj_mm)

        res = drive_svc.files().list(
            q=f"name='{nom_fichier}' and '{subfolder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])
        if not existing:
            return

        contenu = _telecharger_texte(drive_svc, existing[0]["id"])
        actuelles = {c.strip() for c in contenu.strip().split(',') if c.strip()}
        restantes = actuelles - set(numeros_a_retirer)
        if restantes == actuelles:
            return

        nouveau_contenu = ",".join(sorted(restantes, key=_cle_tri_commande))
        chemin_local = os.path.join(ap.WORK_DIR, nom_fichier)
        os.makedirs(ap.WORK_DIR, exist_ok=True)
        with open(chemin_local, "w", encoding="utf-8") as f:
            f.write(nouveau_contenu)
        try:
            media = MediaFileUpload(chemin_local, mimetype="text/plain", resumable=False)
            drive_svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
        finally:
            os.remove(chemin_local)
        print(f"    {nom_fichier} => Drive {path}/ OK ({len(restantes)} commande(s) restante(s))")
    except Exception as e:
        print(f"    Retrait dans {nom_fichier} echoue : {e}")


_RE_MARQUEUR_RETRAIT = re.compile(r'^annuler_anticipation_(\d+)\.txt$')


def lister_marqueurs_retrait(drive_svc, folder_id):
    """[(file_id, numero), ...] des marqueurs annuler_anticipation_NUMERO.txt
    presents dans le dossier du jour (deposes par auto_prepa.py via
    _marquer_retrait_anticipation_drive)."""
    res = drive_svc.files().list(
        q=(f"'{folder_id}' in parents and trashed=false "
           f"and name contains 'annuler_anticipation_'"),
        fields="files(id,name)",
        pageSize=1000,
    ).execute()
    resultat = []
    for f in res.get("files", []):
        m = _RE_MARQUEUR_RETRAIT.match(f["name"])
        if m:
            resultat.append((f["id"], m.group(1)))
    return resultat


def numeros_annules(drive_svc, folder_id, numeros_sup=()):
    """Tous les numeros de commande a exclure de l'anticipation de ce jour :
    marqueurs annuler_anticipation_NUMERO.txt du dossier + registre global des
    annulations (ap.commandes_annulees, independant de toute date) + numeros
    supplementaires fournis par l'appelant.

    Les deux sources sont necessaires : le marqueur date ne peut etre depose
    que si la date de livraison de la commande annulee est connue, et le
    registre global ne dit rien du jour concerne — leur union couvre les deux
    cas (cf. auto_prepa._traiter_commande_potentiellement_anticipee)."""
    annules = set(numeros_sup)
    try:
        annules |= {num for _, num in lister_marqueurs_retrait(drive_svc, folder_id)}
    except Exception as e:
        print(f"    Lecture des marqueurs de retrait echouee : {e}")
    try:
        annules |= ap.commandes_annulees(drive_svc)
    except Exception as e:
        print(f"    Lecture du registre des annulations echouee : {e}")
    return annules


def retirer_blocs_commandes(contenu_jour, numeros_a_retirer):
    """Retire de bon_anticipation_JJ_MM.txt tous les blocs '#CDE:NUMERO' ...
    dont le numero est dans numeros_a_retirer. Retourne le contenu restant."""
    lignes_resultat = []
    ignorer = False
    for ligne in contenu_jour.splitlines():
        m = _RE_MARQUEUR_CDE.match(ligne.strip())
        if m:
            ignorer = m.group(1) in numeros_a_retirer
            if ignorer:
                continue
        if not ignorer:
            lignes_resultat.append(ligne)
    return "\n".join(lignes_resultat) + ("\n" if lignes_resultat else "")


def telecharger_texte_dossier(drive_svc, folder_id, filename):
    """(contenu, file_id) d'un fichier texte du dossier, (None, None) s'il
    n'existe pas."""
    res = drive_svc.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    if not files:
        return None, None
    return _telecharger_texte(drive_svc, files[0]["id"]), files[0]["id"]


def _aujourdhui():
    """Date du jour a Paris (isolee pour les tests)."""
    return datetime.now(_TZ).date()


def _est_anticipation_du_jour(dossier_jj_mm, dossier_mm_aaaa):
    """True si le dossier JJ_MM (mois MM_AAAA) est celui d'aujourd'hui : seule
    l'anticipation du jour, generee ou envoyee ce meme jour, porte les
    baguettes du Drive. Celle du lendemain, preparee ou lancee en amont la
    veille, ne les porte pas (elles s'y retrouveraient une seconde fois le
    lendemain)."""
    try:
        jj, mm = (int(x) for x in dossier_jj_mm.split("_"))
        aaaa = int(dossier_mm_aaaa.split("_")[1])
        return datetime(aaaa, mm, jj).date() == _aujourdhui()
    except (ValueError, IndexError):
        return False


def _ajouter_baguettes_drive(produits_pdf):
    """Ajoute les 4 baguettes tradition du Drive a la page BVP du PDF : elles
    ne viennent d'aucune commande client mais sont a preparer tous les jours
    avec le reste de l'anticipation. Regroupees par gencod comme n'importe
    quel produit (cf. _grouper_produits), elles s'additionnent donc a une
    baguette identique reellement commandee au lieu de faire une ligne a part.

    Ne fait rien si produits_pdf en contient deja (garde-fou : l'appelant
    reconstruit produits_pdf a chaque generation, mais le PDF est regenere a
    chaque commande assemblee et a chaque annulation)."""
    lignes = produits_pdf.get(_LETTRE_BAGUETTES_DRIVE, [])
    if any(p["commande"] == _COMMANDE_BAGUETTES_DRIVE
           and p["gencod"] == _GENCOD_BAGUETTE_DRIVE for p in lignes):
        return
    produits_pdf.setdefault(_LETTRE_BAGUETTES_DRIVE, []).append({
        "commande": _COMMANDE_BAGUETTES_DRIVE,
        "gencod":   _GENCOD_BAGUETTE_DRIVE,
        "libelle":  _LIBELLE_BAGUETTE_DRIVE,
        "prix":     _PRIX_BAGUETTE_DRIVE,
        "prix_kg":  "",
        "qte":      str(_QTE_BAGUETTES_DRIVE),
        "poids":    "",
        "heure":    _HEURE_BAGUETTES_DRIVE,
        "adresse":  "",
        "lettre":   _LETTRE_BAGUETTES_DRIVE,
    })
    print(f"  Ajout automatique : {_QTE_BAGUETTES_DRIVE} baguettes tradition, "
          f"commande {_COMMANDE_BAGUETTES_DRIVE}")


def _produits_pdf_jour(contenu_jour):
    """{lettre: [produits]} des rayons connus (RAYONS_LETTRE) du brouillon."""
    par_lettre = {}
    for p in _parser_lignes_anticipation_jour(contenu_jour or ""):
        par_lettre.setdefault(p["lettre"], []).append(p)
    return {lettre: v for lettre, v in par_lettre.items() if lettre in RAYONS_LETTRE}


def commandes_du_pdf(contenu_jour):
    """Numeros des commandes ayant au moins un produit dans le PDF genere a
    partir de ce contenu (meme regle que commandes_anticipées_JJ_MM.txt)."""
    return sorted({p["commande"] for produits in _produits_pdf_jour(contenu_jour).values()
                   for p in produits}, key=_cle_tri_commande)


def generer_pdf_jour(drive_svc, contenu_jour, dossier_jj_mm, dossier_mm_aaaa):
    """Genere en local anticipation_JJ_MM.pdf a partir du contenu du brouillon
    fourni et retourne son chemin, ou None s'il n'y a rien a anticiper. Des
    qu'un produit est a anticiper, les 4 baguettes tradition du Drive sont
    ajoutees a la page BVP (cf. _ajouter_baguettes_drive) — seulement si le
    PDF est genere le jour meme de son anticipation (cf.
    _est_anticipation_du_jour)."""
    produits_pdf = _produits_pdf_jour(contenu_jour)
    if not produits_pdf:
        return None

    # Les baguettes accompagnent l'anticipation du jour, elles ne justifient
    # pas a elles seules un PDF (aucune commande anticipable ce jour => pas de
    # PDF du tout). Et uniquement le jour meme : un PDF du lendemain genere
    # (ou envoye) la veille ne les porte pas, sinon elles partiraient deux fois.
    if _est_anticipation_du_jour(dossier_jj_mm, dossier_mm_aaaa):
        _ajouter_baguettes_drive(produits_pdf)

    jj, mm = dossier_jj_mm.split("_")
    aaaa = dossier_mm_aaaa.split("_")[1]
    date_complete = f"{jj}/{mm}/{aaaa}"
    ordre_chemin = _charger_ordre_chemin_prepa(drive_svc)
    return _generer_pdf_rayons(produits_pdf, dossier_jj_mm, date_complete, ordre_chemin)


def _mettre_pdf_jour_a_la_corbeille(drive_svc, folder_id, dossier_jj_mm):
    nom_pdf = f"anticipation_{dossier_jj_mm}.pdf"
    res = drive_svc.files().list(
        q=f"name='{nom_pdf}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    for f in res.get("files", []):
        drive_svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
        print(f"  {nom_pdf} mis a la corbeille du dossier du jour.")


def publier_pdf_jour(drive_svc, folder_id, contenu_jour, dossier_jj_mm, dossier_mm_aaaa):
    """Regenere anticipation_JJ_MM.pdf a partir du brouillon du jour (cf.
    generer_pdf_jour) et le depose dans le dossier du jour, ou le met a la
    corbeille s'il ne reste plus rien a anticiper. Retourne True si un PDF a
    ete depose."""
    if not _produits_pdf_jour(contenu_jour):
        _mettre_pdf_jour_a_la_corbeille(drive_svc, folder_id, dossier_jj_mm)
        return False

    chemin_pdf = generer_pdf_jour(drive_svc, contenu_jour, dossier_jj_mm, dossier_mm_aaaa)
    if not chemin_pdf:
        return False
    try:
        ap.deposer_fichier_jour_anticipation(drive_svc, chemin_pdf, dossier_mm_aaaa, dossier_jj_mm)
    finally:
        if os.path.exists(chemin_pdf):
            os.remove(chemin_pdf)
    return True


def appliquer_annulations_jour(drive_svc, folder_id, dossier_mm_aaaa, dossier_jj_mm,
                               contenu_jour=None, numeros_sup=(), regenerer_pdf=True,
                               retires_out=None):
    """Purge le dossier d'anticipation du jour de TOUTE commande annulee ou
    remplacee : met a la corbeille son bon_anticipation_NUMERO.txt individuel
    (pour qu'aucun assemblage ulterieur ne puisse la reintegrer), retire son
    bloc '#CDE:NUMERO' de bon_anticipation_JJ_MM.txt, met a jour
    commandes_anticipées_JJ_MM.txt et, si regenerer_pdf, regenere (ou met a la
    corbeille) anticipation_JJ_MM.pdf.

    Idempotent et appele par les trois etapes de la chaine (assemblage,
    retrait, envoi du PDF) : chacune rattrape ainsi ce qu'une autre aurait
    manque — un run de retrait annule par le concurrency group partage, un
    dispatch perdu, ou une annulation arrivee avant que la commande n'existe.

    retires_out, si fourni, recoit la liste triee des numeros effectivement
    retires du brouillon par cet appel (a distinguer de numeros_annules, qui
    est l'ensemble des commandes annulees connues, presentes ou non).

    Retourne (numeros_annules, contenu_restant, modifie)."""
    annules = numeros_annules(drive_svc, folder_id, numeros_sup)

    # Les bons individuels des commandes annulees d'abord : tant qu'ils sont
    # la, le rattrapage de assembler_anticipation.py les reintegrerait.
    retires_du_dossier = []
    try:
        for file_id, numero in _lister_bons_commande(drive_svc, folder_id):
            if numero in annules:
                drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
                retires_du_dossier.append(numero)
    except Exception as e:
        print(f"    Retrait des bons de commandes annulees echoue : {e}")
    if retires_du_dossier:
        print(f"  bon_anticipation_NUMERO.txt de commande(s) annulee(s) retire(s) du "
              f"dossier du jour : {', '.join(sorted(retires_du_dossier, key=_cle_tri_commande))}")

    nom_jour = f"bon_anticipation_{dossier_jj_mm}.txt"
    file_id_jour = None
    if contenu_jour is None:
        contenu_jour, file_id_jour = telecharger_texte_dossier(drive_svc, folder_id, nom_jour)
    contenu_jour = contenu_jour or ""

    presentes = _commandes_deja_assemblees(contenu_jour) & annules
    if not presentes:
        return annules, contenu_jour, False

    contenu_restant = retirer_blocs_commandes(contenu_jour, presentes)
    if retires_out is not None:
        retires_out.extend(sorted(presentes, key=_cle_tri_commande))
    liste = ', '.join(sorted(presentes, key=_cle_tri_commande))
    print(f"  Commande(s) annulee(s) retiree(s) de {nom_jour} : {liste}")

    if contenu_restant.strip():
        os.makedirs(ap.WORK_DIR, exist_ok=True)
        chemin_local = os.path.join(ap.WORK_DIR, nom_jour)
        with open(chemin_local, "w", encoding="utf-8") as f:
            f.write(contenu_restant)
        try:
            ap.deposer_fichier_jour_anticipation(drive_svc, chemin_local, dossier_mm_aaaa, dossier_jj_mm)
        finally:
            os.remove(chemin_local)
    else:
        if file_id_jour is None:
            _, file_id_jour = telecharger_texte_dossier(drive_svc, folder_id, nom_jour)
        if file_id_jour:
            drive_svc.files().update(fileId=file_id_jour, body={"trashed": True}).execute()
            print(f"  {nom_jour} vide apres retrait — mis a la corbeille.")

    _retirer_commandes_fichier_anticipees(drive_svc, presentes, dossier_mm_aaaa, dossier_jj_mm)

    if regenerer_pdf:
        publier_pdf_jour(drive_svc, folder_id, contenu_restant, dossier_jj_mm, dossier_mm_aaaa)

    return annules, contenu_restant, True


def _reinitialiser_dossier_jour_anticipation(drive_svc, folder_id, dossier_jj_mm,
                                              dossier_mm_aaaa, contenu_envoye):
    """Une fois le PDF du jour archive + envoye par mail, retire de
    GITHUB/Anticipation/MM_AAAA/JJ_MM/ tout ce qui est PARTI dans ce PDF
    (contenu_envoye, le brouillon lu une seule fois avant de generer le PDF
    envoye) : blocs '#CDE:' de bon_anticipation_JJ_MM.txt, bons
    bon_anticipation_NUMERO.txt individuels et anticipation_JJ_MM.pdf —
    sinon une commande anticipable arrivant ensuite ferait regenerer par
    l'assembleur un PDF repartant de ce contenu deja envoye, et un lancement
    suivant du WF Anticipation les renverrait en double.

    Le brouillon est relu juste avant ce nettoyage : une commande assemblee
    PENDANT l'envoi (assemblage lance a la meme seconde que le WF
    Anticipation, cf. commande 55376672 du 24/09/2026 dont le roti de veau
    n'est jamais parti) n'est pas dans le PDF envoye. Elle n'est donc ni
    effacee ni comptee comme envoyee : elle reste seule dans le brouillon
    (texte + PDF regeneres pour elle) et son numero est retourne pour que
    l'appelant previenne qu'il faut relancer l'anticipation.

    Un bon_anticipation_NUMERO.txt ni envoye ni dans le brouillon n'a jamais
    ete integre (dispatch d'assemblage perdu par le concurrency group, cf.
    assembler_anticipation.py) : il est laisse intact sur Drive et son numero
    est retourne pour que l'appelant alerte par email au lieu de le perdre
    silencieusement (cf. incident commande 54522243 du 04/09/2026). Une
    commande annulee n'est evidemment pas orpheline.

    Les marqueurs annuler_anticipation_NUMERO.txt sont purges ici, et
    nulle part ailleurs : ils doivent survivre a tous les assemblages du jour
    (c'est par eux que l'assembleur sait ne pas reintegrer une commande
    annulee) et ne deviennent inutiles qu'avec le dossier lui-meme.

    Retourne (orphelins, arrivees_pendant_envoi)."""
    nom_jour = f"bon_anticipation_{dossier_jj_mm}.txt"
    envoyees = _commandes_deja_assemblees(contenu_envoye or "")
    orphelins, arrivees = [], []
    try:
        res = drive_svc.files().list(
            q=f"name='{nom_jour}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        fichiers_jour = res.get("files", [])
        contenu_actuel = ""
        for f in fichiers_jour:
            contenu_actuel += _telecharger_texte(drive_svc, f["id"]).rstrip("\n") + "\n"

        annules = numeros_annules(drive_svc, folder_id)
        restant = retirer_blocs_commandes(contenu_actuel, envoyees | annules)
        encore_au_brouillon = _commandes_deja_assemblees(restant)

        if encore_au_brouillon:
            arrivees = sorted(encore_au_brouillon, key=_cle_tri_commande)
            for f in fichiers_jour[1:]:
                drive_svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
            os.makedirs(ap.WORK_DIR, exist_ok=True)
            chemin_local = os.path.join(ap.WORK_DIR, nom_jour)
            with open(chemin_local, "w", encoding="utf-8") as f:
                f.write(restant)
            try:
                ap.deposer_fichier_jour_anticipation(
                    drive_svc, chemin_local, dossier_mm_aaaa, dossier_jj_mm)
            finally:
                os.remove(chemin_local)
            publier_pdf_jour(drive_svc, folder_id, restant, dossier_jj_mm, dossier_mm_aaaa)
            print(f"  ATTENTION : commande(s) assemblee(s) pendant l'envoi, absente(s) du "
                  f"PDF envoye, laissee(s) dans le brouillon : {', '.join(arrivees)}")
        else:
            for f in fichiers_jour:
                drive_svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
            _mettre_pdf_jour_a_la_corbeille(drive_svc, folder_id, dossier_jj_mm)

        for file_id, numero in _lister_bons_commande(drive_svc, folder_id):
            if numero in encore_au_brouillon:
                continue
            if numero in envoyees or numero in annules:
                drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
            else:
                orphelins.append(numero)

        for file_id, _numero in lister_marqueurs_retrait(drive_svc, folder_id):
            drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()

        print(f"  {nom_jour}, bon_anticipation_NUMERO.txt envoyes et marqueurs "
              f"d'annulation du jour reinitialises (evite un doublon au prochain assemblage)")
        if orphelins:
            print(f"  ATTENTION : bon_anticipation_NUMERO.txt jamais integre(s), "
                  f"conserve(s) sur Drive : {', '.join(orphelins)}")
    except Exception as e:
        print(f"  Reinitialisation du dossier du jour echouee : {e}")
    return orphelins, arrivees


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)

    ap._charger_config(drive_svc)

    jour_cible = datetime.now(_TZ)
    args = sys.argv[1:]
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                jour_cible = jour_cible.replace(year=int(a), month=int(m), day=int(j))
            except Exception:
                print(f"Format de date invalide : {args[i + 1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)

    dossier_mm_aaaa = jour_cible.strftime("%m_%Y")
    dossier_jj_mm = jour_cible.strftime("%d_%m")

    # Le PDF envoye est genere ici, a partir d'une SEULE lecture du
    # brouillon (contenu_jour), et non telecharge tel quel depuis Drive :
    # l'assembleur, qui tourne a chaque commande, peut reecrire le brouillon
    # et son PDF a tout moment, y compris pendant cet envoi. Tout ce qui suit
    # (commandes notees comme envoyees, nettoyage du dossier) se base sur ce
    # meme contenu : une commande assemblee entre-temps n'est ni perdue ni
    # comptee comme envoyee (cf. _reinitialiser_dossier_jour_anticipation).
    print(f"Anticipation du {dossier_jj_mm}/{dossier_mm_aaaa} a partir du brouillon "
          f"Drive GITHUB/Anticipation...")
    folder_id = ap._dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm, creer=False)
    if not folder_id:
        print("  Aucun dossier d'anticipation pour ce jour — rien a envoyer.")
        return

    # Dernier filet avant l'envoi : si une commande annulee/remplacee est
    # encore dans le brouillon (retrait jamais execute, run annule par le
    # concurrency group partage, annulation arrivee avant la commande...),
    # elle est retiree ici. C'est la seule etape de la chaine qui ne depende
    # d'aucun repository_dispatch — donc la seule qui garantisse que le PDF
    # envoye ne contienne jamais une commande annulee (ancien + nouveau numero
    # en double apres une modification de commande).
    annulees_rattrapees = []
    _, contenu_jour, rattrape = appliquer_annulations_jour(
        drive_svc, folder_id, dossier_mm_aaaa, dossier_jj_mm,
        retires_out=annulees_rattrapees)
    if rattrape:
        print(f"  ATTENTION : commande(s) annulee(s) encore presente(s) dans le "
              f"brouillon, retiree(s) avant envoi : {', '.join(annulees_rattrapees)}")

    nom_pdf = f"anticipation_{dossier_jj_mm}.pdf"
    chemin_pdf = generer_pdf_jour(drive_svc, contenu_jour, dossier_jj_mm, dossier_mm_aaaa)
    if not chemin_pdf or not os.path.exists(chemin_pdf):
        print("  Aucun produit a anticiper dans le brouillon du jour — rien a envoyer.")
        return

    try:
        archive_ok = ap.archiver_resultat_anticipation_drive(
            drive_svc, chemin_pdf, dossier_mm_aaaa, dossier_jj_mm)
        if archive_ok:
            print(f"\n{nom_pdf} => Drive Anticipation/archives OK")
            email_ok = _envoyer_email_resultat(gmail_svc, dossier_jj_mm, chemin_pdf)
            if email_ok:
                _maj_fichier_commandes_envoyees(
                    drive_svc, commandes_du_pdf(contenu_jour), dossier_mm_aaaa, dossier_jj_mm)
                orphelins, arrivees = _reinitialiser_dossier_jour_anticipation(
                    drive_svc, folder_id, dossier_jj_mm, dossier_mm_aaaa, contenu_jour)
                _envoyer_email_commandes_orphelines(gmail_svc, dossier_jj_mm, orphelins)
                _envoyer_email_commandes_arrivees_pendant_envoi(gmail_svc, dossier_jj_mm, arrivees)
                _envoyer_email_annulees_rattrapees(gmail_svc, dossier_jj_mm, annulees_rattrapees)
    finally:
        if os.path.exists(chemin_pdf):
            os.remove(chemin_pdf)


if __name__ == "__main__":
    main()
