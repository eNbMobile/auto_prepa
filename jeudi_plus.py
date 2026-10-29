#!/usr/bin/env python3
"""Jeudi Plus : quantités commandées des produits de l'opération.

- La liste des produits suivis (EAN-13) est sur Drive :
  GITHUB/JeudiPlus/jeudi_plus_eans.csv, une ligne « ean;libellé » par produit
  (libellé facultatif). Elle est remplie par le workflow « Collecte Jeudi
  Plus » (collecte_jeudi_plus.py) depuis la page de l'opération sur
  coursesu.com, ou à la main. Sans ce fichier, rien n'est relevé.
- À chaque bon généré, auto_prepa.py appelle noter_commande() : les lignes du
  bon dont le gencod est suivi sont ajoutées au relevé
  GITHUB/JeudiPlus/jeudi_plus_commandes.csv
  (« date de réception;n° commande;date de retrait;ean;libellé;quantité »).
  Une commande régénérée remplace ses anciennes lignes ; une commande annulée
  ou remplacée est retirée (retirer_commande()).
- Après chaque écriture, le récapitulatif du jour de retrait/livraison est
  réécrit : GITHUB/JeudiPlus/jeudi_plus_AAAA-MM-JJ.csv, une ligne par produit
  suivi (« ean;libellé;quantité;nb commandes;commandes », ces dernières
  sous la forme « 56808178 56815857×3 »), produits non commandés compris
  (quantité 0), les plus vendus en tête ; sa version PDF
  (jeudi_plus_AAAA-MM-JJ.pdf) est réécrite à côté.
- rattrapage_jeudi_plus.py relève après coup les bons déjà générés.
- exclure_jeudi_plus.py retire à la main des commandes du relevé et les note
  dans GITHUB/JeudiPlus/jeudi_plus_commandes_exclues.txt : elles ne sont plus
  jamais relevées (ni à leur régénération, ni au rattrapage).
"""
import io
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Paris")

DOSSIER_GITHUB = "GITHUB"
DOSSIER = "JeudiPlus"
FICHIER_EANS = "jeudi_plus_eans.csv"
FICHIER_COMMANDES = "jeudi_plus_commandes.csv"
FICHIER_EXCLUES = "jeudi_plus_commandes_exclues.txt"
PREFIXE_RECAP = "jeudi_plus_"
ENTETE_COMMANDES = "date_reception;commande;date_retrait;ean;libelle;quantite"
ENTETE_RECAP = "ean;libelle;quantite;nb_commandes;commandes"

# Index des champs d'une ligne de bon_prepa (gencod;libellé;prix;prix2;qté;...).
_IDX_GENCOD, _IDX_LIBELLE, _IDX_QTE = 0, 1, 4

_eans_cache = None


def cle_ean(code):
    """Forme normalisée d'un gencod (13 chiffres, zéros de tête compris)."""
    return code.strip().lstrip("0").zfill(13)


def ean13_valide(code):
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


def lire_liste_eans(contenu):
    """{ean: libellé} depuis le contenu de jeudi_plus_eans.csv (en-tête et
    lignes sans EAN ignorés)."""
    eans = {}
    for ligne in (contenu or "").splitlines():
        champs = ligne.strip().split(";")
        if not champs or not re.fullmatch(r"\d{8,14}", champs[0].strip()):
            continue
        libelle = champs[1].strip() if len(champs) > 1 else ""
        eans.setdefault(cle_ean(champs[0]), libelle)
    return eans


def extraire_quantites(lignes_bon_prepa, eans):
    """{ean: (libellé, quantité)} des produits suivis d'un bon_prepa (liste de
    lignes, en-tête compris). Les lignes d'un même produit sont cumulées."""
    produits = {}
    for ligne in lignes_bon_prepa[1:]:
        champs = ligne.rstrip("\r\n").split(";")
        # Préfixe parasite éventuel ("-N;" ou ";") devant le gencod.
        while champs and not re.fullmatch(r"\d{8,14}", champs[0]):
            champs = champs[1:]
        if len(champs) <= _IDX_QTE:
            continue
        ean = cle_ean(champs[_IDX_GENCOD])
        if ean not in eans:
            continue
        try:
            qte = int(champs[_IDX_QTE].strip() or 1)
        except ValueError:
            qte = 1
        libelle, cumul = produits.get(ean, ("", 0))
        produits[ean] = (libelle or champs[_IDX_LIBELLE].strip(), cumul + qte)
    return produits


def jour_recap(ligne_commande):
    """Jour (AAAA-MM-JJ) du récapitulatif d'une ligne du relevé : celui du
    retrait/livraison, à défaut celui de réception de la commande."""
    champs = ligne_commande.split(";")
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", champs[2] if len(champs) > 2 else "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else champs[0]


def date_retrait_bon(lignes_bon_prepa):
    """Date de retrait/livraison (JJ/MM/AAAA) d'un bon_prepa, lue dans les
    infos commande de ses lignes produit (ex. « JEUDI 29/10/2026 - 10h30 »)."""
    for ligne in lignes_bon_prepa[1:]:
        m = re.search(r"\b(?:LUNDI|MARDI|MERCREDI|JEUDI|VENDREDI|SAMEDI|DIMANCHE)\s+"
                      r"(\d{2}/\d{2}/\d{4})", ligne)
        if m:
            return m.group(1)
    return ""


def recapituler(lignes_commandes, eans, jour):
    """Contenu du récapitulatif d'un jour de retrait (AAAA-MM-JJ) à partir
    des lignes du relevé : tous les produits suivis, les plus vendus en tête."""
    totaux = {ean: [libelle, 0, {}] for ean, libelle in eans.items()}
    for ligne in lignes_commandes:
        champs = ligne.split(";")
        if len(champs) < 6 or jour_recap(ligne) != jour:
            continue
        _, numero, _, ean, libelle, qte = champs[:6]
        total = totaux.setdefault(ean, [libelle, 0, {}])
        total[0] = total[0] or libelle
        total[1] += int(qte or 0)
        total[2][numero] = total[2].get(numero, 0) + int(qte or 0)
    ordre = sorted(totaux.items(), key=lambda kv: (-kv[1][1], kv[1][0], kv[0]))
    return "\n".join([ENTETE_RECAP] + [
        f"{ean};{libelle};{qte};{len(numeros)};"
        + " ".join(n if q == 1 else f"{n}×{q}" for n, q in sorted(numeros.items()))
        for ean, (libelle, qte, numeros) in ordre]) + "\n"


# ─────────────────────────────────────────────────────────────────
# Drive
# ─────────────────────────────────────────────────────────────────

def _sous_dossier(drive_svc, parent_id, nom, creer=True):
    res = drive_svc.files().list(
        q=(f"name='{nom}' and '{parent_id}' in parents and "
           f"mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    if not creer:
        return None
    return drive_svc.files().create(
        body={"name": nom, "parents": [parent_id],
              "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()["id"]


def dossier_jeudi_plus(drive_svc, creer=True):
    github_id = _sous_dossier(drive_svc, "root", DOSSIER_GITHUB, creer)
    return _sous_dossier(drive_svc, github_id, DOSSIER, creer) if github_id else None


def _trouver(drive_svc, dossier_id, nom):
    res = drive_svc.files().list(
        q=f"name='{nom}' and '{dossier_id}' in parents and trashed=false",
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _telecharger_texte(drive_svc, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8")


def ecrire_texte(drive_svc, dossier_id, nom, contenu, file_id=None, mimetype="text/csv"):
    from googleapiclient.http import MediaIoBaseUpload
    file_id = file_id or _trouver(drive_svc, dossier_id, nom)
    donnees = contenu if isinstance(contenu, bytes) else contenu.encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(donnees), mimetype=mimetype, resumable=False)
    if file_id:
        drive_svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        drive_svc.files().create(body={"name": nom, "parents": [dossier_id]},
                                 media_body=media, fields="id").execute()


def charger_eans(drive_svc):
    """{ean: libellé} des produits suivis, lu une fois par run ({} si absent
    ou illisible)."""
    global _eans_cache
    if _eans_cache is None:
        try:
            dossier_id = dossier_jeudi_plus(drive_svc, creer=False)
            file_id = _trouver(drive_svc, dossier_id, FICHIER_EANS) if dossier_id else None
            _eans_cache = lire_liste_eans(_telecharger_texte(drive_svc, file_id)) if file_id else {}
        except Exception as e:
            print(f"    Lecture {DOSSIER}/{FICHIER_EANS} echouee : {e}")
            _eans_cache = {}
    return _eans_cache


def _maj_releve(drive_svc, eans, numeros, nouvelles, jours=()):
    """Retire les lignes des commandes `numeros` du relevé, ajoute
    `nouvelles`, puis réécrit le récapitulatif des jours concernés (et de
    `jours`, AAAA-MM-JJ, même sans commande)."""
    numeros = {str(n) for n in numeros}
    dossier_id = dossier_jeudi_plus(drive_svc)
    file_id = _trouver(drive_svc, dossier_id, FICHIER_COMMANDES)
    lignes = []
    if file_id:
        lignes = [l for l in _telecharger_texte(drive_svc, file_id).splitlines()[1:] if l.strip()]
    retirees = [l for l in lignes if l.split(";")[1] in numeros]
    if retirees or nouvelles:
        lignes = [l for l in lignes if l not in retirees] + nouvelles
        ecrire_texte(drive_svc, dossier_id, FICHIER_COMMANDES,
                     "\n".join([ENTETE_COMMANDES] + lignes) + "\n", file_id)
    for jour in sorted({jour_recap(l) for l in retirees + nouvelles} | set(jours)):
        recap = recapituler(lignes, eans, jour)
        ecrire_texte(drive_svc, dossier_id, f"{PREFIXE_RECAP}{jour}.csv", recap)
        _ecrire_pdf_recap(drive_svc, dossier_id, recap, jour)


def _ecrire_pdf_recap(drive_svc, dossier_id, recap, jour):
    """Réécrit jeudi_plus_AAAA-MM-JJ.pdf à côté du CSV (rien si aucun produit
    commandé ce jour-là). Un échec n'empêche pas le relevé."""
    import tempfile
    fichier_pdf = f"{PREFIXE_RECAP}{jour}.pdf"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = generer_pdf_recap(recap, datetime.strptime(jour, "%Y-%m-%d").date(),
                                    os.path.join(tmp, fichier_pdf))
            if pdf:
                with open(pdf, "rb") as f:
                    ecrire_texte(drive_svc, dossier_id, fichier_pdf, f.read(), mimetype="application/pdf")
            else:
                ancien = _trouver(drive_svc, dossier_id, fichier_pdf)
                if ancien:  # plus aucun produit commandé ce jour-là (annulations)
                    drive_svc.files().update(fileId=ancien, body={"trashed": True}).execute()
    except Exception as e:
        print(f"    PDF {DOSSIER}/{fichier_pdf} echoue : {e}")


def noter_commandes(drive_svc, commandes, jours=()):
    """Relève en une seule écriture les produits Jeudi Plus de plusieurs bons :
    `commandes` = [(numéro, lignes du bon_prepa, date de retrait JJ/MM/AAAA ou
    "", date de réception)]. Retourne {numéro: articles relevés}."""
    eans = charger_eans(drive_svc)
    if not eans:
        return {}
    exclues = charger_exclues(drive_svc)
    nouvelles, articles = [], {}
    for numero, lignes_bon_prepa, date_retrait, jour in commandes:
        if str(numero) in exclues:
            articles[numero] = 0
            continue
        produits = extraire_quantites(lignes_bon_prepa, eans)
        date_retrait = date_retrait or date_retrait_bon(lignes_bon_prepa)
        nouvelles += [f"{jour:%Y-%m-%d};{numero};{date_retrait};{ean};{libelle.replace(';', ' ')};{qte}"
                      for ean, (libelle, qte) in sorted(produits.items())]
        articles[numero] = sum(q for _, q in produits.values())
    _maj_releve(drive_svc, eans, [c[0] for c in commandes], nouvelles, jours)
    return articles


def noter_commande(drive_svc, numero, lignes_bon_prepa, date_retrait="", jour=None):
    """Relève les produits Jeudi Plus d'un bon généré. Ne lève jamais : un
    échec ne doit pas bloquer la génération du bon."""
    try:
        jour = jour or datetime.now(_TZ).date()
        nb = noter_commandes(drive_svc, [(numero, lignes_bon_prepa, date_retrait, jour)]).get(numero)
        if nb:
            print(f"    Jeudi Plus : {nb} article(s) notes dans {DOSSIER}/{FICHIER_COMMANDES}")
    except Exception as e:
        print(f"    Releve Jeudi Plus echoue (cde {numero}) : {e}")


def charger_exclues(drive_svc):
    """Numéros des commandes exclues à la main du relevé (set vide si aucun)."""
    dossier_id = dossier_jeudi_plus(drive_svc, creer=False)
    file_id = _trouver(drive_svc, dossier_id, FICHIER_EXCLUES) if dossier_id else None
    if not file_id:
        return set()
    return {l.strip() for l in _telecharger_texte(drive_svc, file_id).splitlines() if l.strip()}


def exclure_commandes(drive_svc, numeros):
    """Exclut définitivement des commandes du relevé : ajoutées à
    jeudi_plus_commandes_exclues.txt, retirées du relevé, récapitulatifs et
    PDF des jours concernés réécrits. Retourne {numéro: articles retirés}."""
    numeros = [str(n) for n in numeros]
    dossier_id = dossier_jeudi_plus(drive_svc)
    exclues = charger_exclues(drive_svc) | set(numeros)
    ecrire_texte(drive_svc, dossier_id, FICHIER_EXCLUES, "\n".join(sorted(exclues)) + "\n",
                 mimetype="text/plain")
    file_id = _trouver(drive_svc, dossier_id, FICHIER_COMMANDES)
    retires = {n: 0 for n in numeros}
    if file_id:
        for l in _telecharger_texte(drive_svc, file_id).splitlines()[1:]:
            champs = l.split(";")
            if len(champs) >= 6 and champs[1] in retires:
                retires[champs[1]] += int(champs[5] or 0)
    eans = charger_eans(drive_svc)
    if eans:
        _maj_releve(drive_svc, eans, numeros, [])
    return retires


def retirer_commande(drive_svc, numero):
    """Retire du relevé une commande annulée ou remplacée. Ne lève jamais."""
    try:
        eans = charger_eans(drive_svc)
        if eans:
            _maj_releve(drive_svc, eans, [numero], [])
    except Exception as e:
        print(f"    Retrait Jeudi Plus echoue (cde {numero}) : {e}")


# ─────────────────────────────────────────────────────────────────
# PDF du récapitulatif (mise en page du contrôle de stocks)
# ─────────────────────────────────────────────────────────────────

def generer_pdf_recap(contenu_recap, jour, nom_pdf):
    """PDF des produits commandés d'un récapitulatif (contenu de
    jeudi_plus_AAAA-MM-JJ.csv) : quantité, code-barres, libellé, numéros de
    commande, les plus vendus en tête. Retourne le chemin, None si aucun
    produit commandé."""
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    rows = []
    for ligne in contenu_recap.splitlines()[1:]:
        champs = ligne.split(";")
        if len(champs) >= 4 and champs[2].isdigit() and int(champs[2]) > 0:
            rows.append((champs[0], champs[1], int(champs[2]),
                         champs[4] if len(champs) > 4 else champs[3]))
    if not rows:
        return None

    small = ParagraphStyle('small', fontSize=8, leading=10)
    small_c = ParagraphStyle('small_c', fontSize=8, leading=10, alignment=1)
    gras_c = ParagraphStyle('gras_c', fontSize=10, leading=12, alignment=1, fontName='Helvetica-Bold')
    tiny_c = ParagraphStyle('tiny_c', fontSize=7, leading=8, alignment=1)
    header_s = ParagraphStyle('hdr', fontSize=8, leading=10, textColor=colors.white)
    header_c = ParagraphStyle('hdr_c', parent=header_s, alignment=1)

    def cellule_code(ean):
        try:
            bc = createBarcodeDrawing('EAN13', value=ean, width=100, height=30, humanReadable=False)
        except Exception:
            return Paragraph(ean, small)
        return Table([[bc], [Paragraph(ean, tiny_c)]], colWidths=[108], style=TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))

    data = [[Paragraph('Quantité', header_c), Paragraph('Code-barres', header_s),
             Paragraph('Libellé', header_s), Paragraph('Commandes', header_c)]]
    for ean, libelle, qte, commandes in rows:
        data.append([Paragraph(str(qte), gras_c), cellule_code(ean), Paragraph(escape(libelle), small),
                     Paragraph(escape(commandes).replace(' ', '<br/>'), small_c)])

    BLEU = colors.HexColor('#006797')
    table = Table(data, colWidths=[50, 108, 259, 110], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BLEU),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF6FB')]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))

    total = sum(r[2] for r in rows)
    titre = (f"<b>Jeudi Plus — retrait du {jour:%d/%m/%Y}</b>&nbsp;&nbsp;"
             f"({len(rows)} produit{'s' if len(rows) > 1 else ''}, "
             f"{total} article{'s' if total > 1 else ''})")
    doc = SimpleDocTemplate(nom_pdf, pagesize=A4, topMargin=8*mm, bottomMargin=8*mm,
                            leftMargin=3*mm, rightMargin=3*mm)
    doc.build([Paragraph(titre, getSampleStyleSheet()['Title']), Spacer(1, 5*mm), table])
    return nom_pdf
