#!/usr/bin/env python3
"""
Recupere anticipation_JJ_MM.pdf, deja genere au fil de l'eau par
assembler_anticipation.py sur Drive (GITHUB/Anticipation/MM_AAAA/JJ_MM), et
l'archive + l'envoie par mail — sans aucun recalcul.

Ce module fournit aussi (utilisees par assembler_anticipation.py, qui fait le
calcul reel a chaque commande) le parsing de bon_anticipation_JJ_MM.txt, le
regroupement par lettre d'anticipation et la generation du PDF (un rayon par
page).
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

# Rayons dont le format PDF affiche systematiquement poids/qte + prix + prix/kg
# par ligne de commande (comme la Boucherie) : cf. avec_poids/poids_variable
# dans _elements_rayon.
_LETTRES_AVEC_POIDS_SYSTEMATIQUE = ("B", "D")


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


def _telecharger_photo(gencod, cache):
    """Recupere la photo produit (jpg ou png) depuis enbmobile.nl/mobUDrive/visuels/.

    Retourne les octets de l'image, ou None si introuvable. Resultat mis en
    cache par gencod pour eviter de re-telecharger le meme visuel plusieurs
    fois dans un meme PDF."""
    if gencod in cache:
        return cache[gencod]
    for ext in _PHOTO_EXTENSIONS:
        url = f"{_VISUELS_BASE_URL}{gencod}{ext}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            cache[gencod] = data
            return data
        except Exception:
            continue
    cache[gencod] = None
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


def _generer_pdf_rayons(produits_pdf, dossier_jj_mm, date_complete, ordre_chemin):
    """Genere un unique PDF reunissant tous les rayons fournis (produits_pdf :
    {lettre: [produit, ...]}), chaque rayon demarrant en haut d'une nouvelle
    page. Pour chaque rayon : une ligne par produit (gencod) avec
    commande(s), heure(s), photo, code-barres EAN13 + gencod, libelle, prix
    et quantite(s) (+ poids pour la Boucherie et la Poissonnerie). Les produits identiques
    provenant de plusieurs commandes sont regroupes sur une seule ligne
    (commande/heure/qte empiles dans la meme case, triees par heure de
    commande croissante), et les groupes sont tries par heure de commande
    croissante (l'ordre du chemin de preparation, chemin_prepa_ramasse.csv
    via ordre_chemin, ne departage plus qu'a heure egale). Retourne le
    chemin local du PDF, ou None si reportlab est indisponible / produits_pdf
    est vide."""
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
        # plus, juste avant le Prix (_LETTRES_AVEC_POIDS_SYSTEMATIQUE).
        avec_poids = lettre in _LETTRES_AVEC_POIDS_SYSTEMATIQUE
        largeur_code_barres = 95
        if avec_poids:
            col_widths = [55, 35, 55, largeur_code_barres, 184, 45, 42, 30]
            hdr_txts = ('Commande', 'Heure', 'Photo', 'Code-barres', 'Libellé', 'Poids', 'Prix', 'Qté')
        else:
            col_widths = [55, 35, 55, largeur_code_barres, 239, 42, 30]
            hdr_txts = ('Commande', 'Heure', 'Photo', 'Code-barres', 'Libellé', 'Prix', 'Qté')
        derniere_col = len(hdr_txts) - 1

        hdr = [Paragraph(t, header_s) for t in hdr_txts]
        data = [hdr]

        cache_photos = {}
        span_rows = []
        for g in groupes:
            gencod = g['gencod']

            photo_cell = ''
            photo_bytes = _telecharger_photo(gencod, cache_photos) if gencod else None
            if photo_bytes:
                try:
                    photo_cell = RLImage(io.BytesIO(photo_bytes), width=18 * mm, height=18 * mm, kind='bound')
                except Exception:
                    photo_cell = ''

            bc = None
            if len(gencod) == 13 and gencod.isdigit():
                try:
                    bc = createBarcodeDrawing('EAN13', value=gencod, width=largeur_code_barres, height=28,
                                              humanReadable=False)
                except Exception:
                    bc = None
            if bc:
                bc_cell = Table(
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
            else:
                bc_cell = Paragraph(gencod, small)

            # Produit identique dans plusieurs commandes : commande et heure
            # empilees d'une ligne a l'autre, dans la meme case, triees par
            # heure de commande croissante (deja fait dans _grouper_produits).
            commande_cell = Paragraph("<br/>".join(c for c, _, _ in g['lignes']), small)
            heure_cell = Paragraph("<br/>".join(h for _, _, h in g['lignes']), small)

            row = [commande_cell, heure_cell, photo_cell, bc_cell, Paragraph(g['libelle'], small)]
            if avec_poids:
                # Qte, poids et prix restent detailles par commande (poids
                # total = qte * poids unitaire, prix = prix/kg * ce poids :
                # chaque client peut avoir commande une quantite differente,
                # donc un poids et un prix differents pour le meme produit).
                poids_txts = ["" if not g['poids'] else f"{_poids_ligne(q, g['poids'])} Kg"
                              for _, q, _ in g['lignes']]
                poids_txt = "<br/>".join(poids_txts)
                prix_txts = ["" if not (g['poids'] and g['prix_kg'])
                             else f"{_prix_ligne_poids(q, g['poids'], g['prix_kg'])} €"
                             for _, q, _ in g['lignes']]
                prix_txt = "<br/>".join(prix_txts)
                qte_txt = "<br/>".join(q for _, q, _ in g['lignes'])
                if g['poids'] and g['prix_kg']:
                    # Poids, Prix et Qte dans une meme table imbriquee (et non
                    # Qte a part dans la colonne du tableau principal) : sinon
                    # le VALIGN MIDDLE du tableau principal centre chaque bloc
                    # independamment sur sa propre hauteur, et comme ce bloc
                    # est plus haut que la colonne Qte (ligne supplementaire
                    # pour le prix/kg), les lignes Qte se decalent des lignes
                    # Poids/Prix des qu'elles ne sont plus toutes de la meme
                    # hauteur (libelle sur plusieurs lignes notamment).
                    # Prix/kg affiche sur une ligne centree sous Poids/Prix/Qte
                    # (colonnes fusionnees), comme annote a la main sur le bon
                    # d'origine.
                    poids_prix = Table(
                        [[Paragraph(poids_txt, small_c), Paragraph(prix_txt, small_c), Paragraph(qte_txt, small_c)],
                         [Paragraph(f"{g['prix_kg']} €/Kg", small_c), '', '']],
                        colWidths=[col_widths[5], col_widths[6], col_widths[7]],
                        style=TableStyle([
                            ('SPAN',          (0, 1), (2, 1)),
                            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                            ('TOPPADDING',    (0, 0), (-1, -1), 0),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                            ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                            ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                            # Ecarte legerement Poids/Prix/Qte (remontes) du
                            # prix/kg (descendu), sans agrandir la ligne : le
                            # leading de small_c a ete resserre d'autant.
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
                            ('TOPPADDING',    (0, 1), (-1, 1), 2),
                        ]),
                    )
                    row.append(poids_prix)
                    row.append('')
                    qte_cell = ''
                    span_rows.append(len(data))
                else:
                    row.append(Paragraph(poids_txt, small))
                    row.append(Paragraph(prix_txt, small))
                    qte_cell = Paragraph(qte_txt, small)
            else:
                # Rayon sans colonne Poids : quantite totale a collecter,
                # sans le detail par commande.
                qte_cell = Paragraph(_qte_totale(g['lignes']), small)
                prix_txt = f"{g['prix']} €" if g['prix'] else ''
                row.append(Paragraph(prix_txt, small))
            row.append(qte_cell)
            data.append(row)

        style = TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0), BLEU),
            ('FONTNAME',       (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',       (0, 0), (-1, 0), 8),
            ('ALIGN',          (0, 0), (-1, 0), 'CENTER'),
            ('FONTSIZE',       (0, 1), (-1, -1), 8),
            ('ALIGN',          (0, 1), (3, -1), 'CENTER'),
            ('ALIGN',          (5, 1), (derniere_col, -1), 'CENTER'),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF6FB')]),
            ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('TOPPADDING',     (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 6),
        ])
        # Prix/kg (Boucherie) : cellule Poids+Prix+Qte fusionnee sur la ligne
        # ou elle est affichee (cf. poids_prix ci-dessus).
        for idx in span_rows:
            style.add('SPAN', (5, idx), (7, idx))

        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(style)
        elements.append(table)
        print(f"  {nom_rayon} (lettre {lettre}) : {len(groupes)} produit(s), "
              f"{len(produits)} ligne(s) commande")
        return elements

    nom_pdf = f"anticipation_{dossier_jj_mm}.pdf"
    doc = SimpleDocTemplate(nom_pdf, pagesize=A4,
                            topMargin=8 * mm, bottomMargin=8 * mm,
                            leftMargin=5 * mm, rightMargin=5 * mm)

    elements_total = []
    for i, lettre in enumerate(sorted(produits_pdf.keys())):
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


def _cle_tri_commande(numero):
    """Tri numerique quand possible (numeros de commande), alphabetique sinon."""
    return (0, int(numero)) if numero.isdigit() else (1, numero)


def _maj_fichier_commandes_anticipees(drive_svc, commandes, dossier_mm_aaaa, dossier_jj_mm):
    """Note dans GITHUB/Anticipation/archives/MM_AAAA/JJ_MM/commandes_anticipées_JJ_MM.txt
    (separateur virgule) les numeros de commande anticipes ce jour-la. Si une
    anticipation a deja ete lancee dans la journee pour ce meme JJ_MM (J, J+1,
    ...), le fichier existant est fusionne avec les commandes de ce run plutot
    qu'ecrase."""
    if not commandes:
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


def _supprimer_pdf_jour_anticipation(drive_svc, file_id, nom_pdf):
    """Met a la corbeille anticipation_JJ_MM.pdf dans GITHUB/Anticipation/MM_AAAA/JJ_MM/
    une fois archive + envoye par mail (trashed=True plutot que suppression
    definitive, pour rester restaurable) — evite qu'un second lancement du
    WF Anticipation ne retrouve ce brouillon et renvoie les memes produits."""
    try:
        drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
        print(f"  {nom_pdf} retire du dossier du jour (conserve dans archives/)")
    except Exception as e:
        print(f"  Suppression {nom_pdf} du dossier du jour echouee : {e}")


def _reinitialiser_dossier_jour_anticipation(drive_svc, folder_id, dossier_jj_mm):
    """Une fois le PDF du jour archive + envoye par mail, vide GITHUB/Anticipation/MM_AAAA/JJ_MM/
    de bon_anticipation_JJ_MM.txt (l'assemblage accumule au fil des commandes par
    assembler_anticipation.py) et des bon_anticipation_NUMERO.txt individuels deja
    integres — sinon une commande anticipable arrivant apres cet envoi ferait
    regenerer par l'assembleur un nouveau PDF repartant de ce contenu deja
    envoye (donc avec les memes produits en plus des nouveaux), et un lancement
    suivant du WF Anticipation les renverrait en double."""
    nom_jour = f"bon_anticipation_{dossier_jj_mm}.txt"
    try:
        res = drive_svc.files().list(
            q=f"name='{nom_jour}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        for f in res.get("files", []):
            drive_svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
        for file_id, numero in _lister_bons_commande(drive_svc, folder_id):
            drive_svc.files().update(fileId=file_id, body={"trashed": True}).execute()
        print(f"  {nom_jour} et bon_anticipation_NUMERO.txt du jour reinitialises "
              f"(evite un doublon au prochain assemblage)")
    except Exception as e:
        print(f"  Reinitialisation du dossier du jour echouee : {e}")


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

    # Aucun calcul ici : anticipation_JJ_MM.pdf est deja a jour, regenere a
    # chaque commande par assembler_anticipation.py. On le recupere tel
    # quel, on l'archive sous archives/ et on l'envoie par mail.
    print(f"Recuperation du PDF d'anticipation du {dossier_jj_mm}/{dossier_mm_aaaa} "
          f"sur Drive GITHUB/Anticipation...")
    folder_id = ap._dossier_anticipation_jour(drive_svc, dossier_mm_aaaa, dossier_jj_mm, creer=False)

    nom_pdf = f"anticipation_{dossier_jj_mm}.pdf"
    chemin_pdf = None
    pdf_file_id = None
    if folder_id:
        res = drive_svc.files().list(
            q=f"name='{nom_pdf}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        fichiers_pdf = res.get("files", [])
        if fichiers_pdf:
            pdf_file_id = fichiers_pdf[0]["id"]
            chemin_pdf = os.path.join(ap.WORK_DIR, nom_pdf)
            ap.download_pdf(drive_svc, pdf_file_id, chemin_pdf)

    if not chemin_pdf or not os.path.exists(chemin_pdf):
        print(f"  Aucun {nom_pdf} trouve pour ce jour — rien a envoyer.")
        return

    try:
        archive_ok = ap.archiver_resultat_anticipation_drive(
            drive_svc, chemin_pdf, dossier_mm_aaaa, dossier_jj_mm)
        if archive_ok:
            print(f"\n{nom_pdf} => Drive Anticipation/archives OK")
            email_ok = _envoyer_email_resultat(gmail_svc, dossier_jj_mm, chemin_pdf)
            if email_ok and pdf_file_id:
                _supprimer_pdf_jour_anticipation(drive_svc, pdf_file_id, nom_pdf)
                _reinitialiser_dossier_jour_anticipation(drive_svc, folder_id, dossier_jj_mm)
    finally:
        if os.path.exists(chemin_pdf):
            os.remove(chemin_pdf)


if __name__ == "__main__":
    main()
