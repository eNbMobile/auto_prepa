#!/usr/bin/env python3
"""
Recupere tous les bon_anticipation_NUMERO.txt deja archives dans la journee
sur Drive (GITHUB/Anticipation/MM_AAAA/JJ_MM, deposes au fil de l'eau par
auto_prepa.py), les regroupe par lettre d'anticipation et genere le PDF
anticipation_JJ_MM.pdf (un rayon par page), uploade sur Drive.
"""

import base64
import io
import os
import re
import urllib.request
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

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
    "F": "Fromage à la coupe",
}

# Format des lignes de bon_anticipation.txt (16 champs separes par ';') :
# 0 gencod ; 1 libelle ; 2 prix ; 3 prix au kg/L ; 4 qte ; 5 substitution ;
# 6 poids (nombre decimal, utilise pour la lettre B/Boucherie) ; 7-8 sans
# interet ; 9 jour de commande + heure + autres infos ; 10 sacs ;
# 11 adresse ; 12-14 sans interet ; 15 (dernier champ) lettre d'anticipation
_IDX_GENCOD  = 0
_IDX_LIBELLE = 1
_IDX_PRIX    = 2
_IDX_QTE     = 4
_IDX_POIDS   = 6
_IDX_JOUR_HEURE = 9
_IDX_ADRESSE = 11
_NB_CHAMPS_MIN = 16

_RE_LEADING_SEQ = re.compile(r'^(?:-\d+)?;(\d{13};)')
_RE_HEURE = re.compile(r'([01]?\d|2[0-3])[:h]([0-5]\d)')

_MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre"]


def _date_fr(dt):
    """Formate une date en francais complet, ex: '11 août 2026'."""
    return f"{dt.day} {_MOIS_FR[dt.month - 1]} {dt.year}"


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
        heure = f"{m_heure.group(1)}:{m_heure.group(2)}" if m_heure else ""

        produits.append({
            "commande": numero_commande,
            "gencod":   champs[_IDX_GENCOD].strip(),
            "libelle":  champs[_IDX_LIBELLE].strip(),
            "prix":     champs[_IDX_PRIX].strip(),
            "qte":      champs[_IDX_QTE].strip(),
            "poids":    champs[_IDX_POIDS].strip(),
            "heure":    heure,
            "adresse":  champs[_IDX_ADRESSE].strip(),
            "lettre":   champs[-1].strip().upper() or "?",
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
    dans plusieurs commandes) : commande et quantite sont empilees, le reste
    (libelle, prix, poids, adresse) est partage. Retourne une liste de dicts
    {gencod, libelle, prix, poids, adresse, lignes: [(commande, qte), ...]}."""
    groupes = {}
    ordre_gencods = []
    for p in produits:
        gencod = p["gencod"]
        if gencod not in groupes:
            groupes[gencod] = {
                "gencod":  gencod,
                "libelle": p["libelle"],
                "prix":    p["prix"],
                "poids":   p["poids"],
                "adresse": p["adresse"],
                "lignes":  [],
            }
            ordre_gencods.append(gencod)
        groupes[gencod]["lignes"].append((p["commande"], p["qte"]))

    resultat = []
    for gencod in ordre_gencods:
        g = groupes[gencod]
        g["lignes"].sort(key=lambda t: t[0])
        resultat.append(g)
    return resultat


def _generer_pdf_rayons(produits_pdf, dossier_jj_mm, date_complete, ordre_chemin):
    """Genere un unique PDF reunissant tous les rayons fournis (produits_pdf :
    {lettre: [produit, ...]}), chaque rayon demarrant en haut d'une nouvelle
    page. Pour chaque rayon : une ligne par produit (gencod) avec
    commande(s), photo, code-barres EAN13 + gencod, libelle, prix et
    quantite(s) (+ poids pour la Boucherie). Les produits identiques
    provenant de plusieurs commandes sont regroupes sur une seule ligne
    (commande/qte empiles dans la meme case), et les lignes sont triees
    selon l'ordre du chemin de preparation (chemin_prepa_ramasse.csv, via
    ordre_chemin). Retourne le chemin local du PDF, ou None si reportlab est
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
    header_s = ParagraphStyle('hdr', fontSize=8, leading=10, textColor=colors.white)
    tiny_c   = ParagraphStyle('tiny_c', fontSize=7, leading=8, alignment=1)
    tiny     = ParagraphStyle('tiny', fontSize=5, leading=6)
    titre_s  = ParagraphStyle('titre', fontName='Helvetica-Bold', fontSize=13,
                              leading=16, alignment=1)
    BLEU     = colors.HexColor('#006797')

    def _cellule_libelle(libelle):
        """Cellule Libelle : le texte produit en haut, puis en dessous deux
        petites cases a cocher (Rupture / Substitution) a remplir a la main
        lors de la preparation."""
        cases = Table(
            [[Paragraph('', tiny_c), Paragraph('Rupture', tiny),
              Paragraph('', tiny_c), Paragraph('Substitution', tiny)]],
            colWidths=[9, 50, 9, 44], rowHeights=[9],
            style=TableStyle([
                ('BOX',           (0, 0), (0, 0), 0.5, colors.black),
                ('BOX',           (2, 0), (2, 0), 0.5, colors.black),
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',    (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                ('LEFTPADDING',   (1, 0), (1, 0), 3),
                ('RIGHTPADDING',  (1, 0), (1, 0), 16),
                ('LEFTPADDING',   (3, 0), (3, 0), 3),
            ]),
        )
        return Table(
            [[Paragraph(libelle, small)], [cases]],
            style=TableStyle([
                ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                ('TOPPADDING',    (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (0, 0), 8),
                ('BOTTOMPADDING', (0, 1), (0, 1), 0),
            ]),
        )

    def _elements_rayon(produits, lettre, nom_rayon):
        groupes = _grouper_produits(produits)
        fin_chemin = len(ordre_chemin)
        groupes.sort(key=lambda g: (ordre_chemin.get(g["adresse"], fin_chemin), g["gencod"]))

        elements = [
            Paragraph(f"Anticipation {nom_rayon} {date_complete} — À préparer avant 7h30",
                      titre_s),
            Spacer(1, 5 * mm),
        ]

        # Boucherie (lettre B) : colonne Poids en plus, juste avant le Prix.
        avec_poids = (lettre == "B")
        largeur_code_barres = 95
        if avec_poids:
            col_widths = [60, 55, largeur_code_barres, 214, 45, 42, 30]
            hdr_txts = ('Commande', 'Photo', 'Code-barres', 'Libellé', 'Poids', 'Prix', 'Qté')
        else:
            col_widths = [60, 55, largeur_code_barres, 259, 42, 30]
            hdr_txts = ('Commande', 'Photo', 'Code-barres', 'Libellé', 'Prix', 'Qté')
        derniere_col = len(hdr_txts) - 1

        hdr = [Paragraph(t, header_s) for t in hdr_txts]
        data = [hdr]

        cache_photos = {}
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

            # Produit identique dans plusieurs commandes : commande et qte
            # empilees l'une sous l'autre, dans la meme case.
            commande_cell = Paragraph("<br/>".join(c for c, _ in g['lignes']), small)
            qte_cell      = Paragraph("<br/>".join(q for _, q in g['lignes']), small)

            row = [commande_cell, photo_cell, bc_cell, _cellule_libelle(g['libelle'])]
            if avec_poids:
                poids_txt = f"{g['poids']} Kg" if g['poids'] else ''
                row.append(Paragraph(poids_txt, small))
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
            ('ALIGN',          (0, 1), (2, -1), 'CENTER'),
            ('ALIGN',          (4, 1), (derniere_col, -1), 'CENTER'),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('VALIGN',         (3, 1), (3, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF6FB')]),
            ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('TOPPADDING',     (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 6),
        ])

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


def _envoyer_email_resultat(gmail_svc, dossier_jj_mm, chemin_pdf, date_fr):
    """Envoie par email le PDF d'anticipation du jour au destinataire
    configure sur Drive (config.json / email_destinataire)."""
    destinataire = ap.EMAIL_ANTICIPATION
    if not destinataire:
        print("  Envoi email anticipation ignore : email_destinataire absent de config.json")
        return
    if not chemin_pdf or not os.path.exists(chemin_pdf):
        return

    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    try:
        msg = MIMEMultipart()
        msg["To"] = destinataire
        msg["Subject"] = f"Anticipation {dossier_jj_mm}"
        msg.attach(MIMEText(
            f"Bonjour, ci-joint l'anticipation pour la journée du {date_fr}.\n",
            "plain", "utf-8"))

        with open(chemin_pdf, "rb") as f:
            data = f.read()
        part = MIMEApplication(data, "pdf")
        part.add_header("Content-Disposition", "attachment", filename=os.path.basename(chemin_pdf))
        msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Email anticipation envoye => {destinataire}")
    except Exception as e:
        print(f"  Envoi email anticipation echoue : {e}")


def main():
    os.makedirs(ap.WORK_DIR, exist_ok=True)

    creds = ap.get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    gmail_svc = build("gmail", "v1", credentials=creds)

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

    # Lettres avec rayon connu (RAYONS_LETTRE) : format PDF dedie.
    produits_pdf = {lettre: par_lettre.pop(lettre)
                    for lettre in list(par_lettre.keys()) if lettre in RAYONS_LETTRE}

    for lettre in sorted(par_lettre.keys()):
        print(f"  Lettre {lettre} ({len(par_lettre[lettre])} produit(s)) : "
              f"rayon non defini, ignoree (pas de PDF)")

    if not produits_pdf:
        print("Aucun produit anticipable avec rayon defini aujourd'hui.")
        return

    date_complete = maintenant.strftime("%d/%m/%Y")
    ordre_chemin = _charger_ordre_chemin_prepa(drive_svc)
    print(f"\nGeneration du PDF anticipation ({len(produits_pdf)} rayon(s)) ...")
    chemin_pdf = _generer_pdf_rayons(produits_pdf, dossier_jj_mm, date_complete, ordre_chemin)

    try:
        if chemin_pdf:
            ap.archiver_resultat_anticipation_drive(drive_svc, chemin_pdf, dossier_mm_aaaa, dossier_jj_mm)
            print(f"\nanticipation_{dossier_jj_mm}.pdf => Drive Anticipation/archives OK "
                  f"({len(fichiers)} commande(s) avec produits anticipables)")
            _envoyer_email_resultat(gmail_svc, dossier_jj_mm, chemin_pdf, _date_fr(maintenant))
    finally:
        if chemin_pdf and os.path.exists(chemin_pdf):
            os.remove(chemin_pdf)


if __name__ == "__main__":
    main()
