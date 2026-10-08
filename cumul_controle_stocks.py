#!/usr/bin/env python3
"""
Cumul du contrôle de stocks sur une période (d'une date à une autre, bornes
incluses).

Reprend jour par jour le même calcul que controle_stocks.py (stock du soir
J-1 + ventes du jour vs stock du matin du lendemain, même périmètre de
gencods R1, mêmes exports archivés sur Drive) mais additionne les écarts
« ECART » obtenus chaque jour pour les regrouper par gencod sur toute la
période — uniquement le contrôle de stock proprement dit : ni les stocks
insuffisants, ni les articles à déloter n'entrent dans ce cumul.

Un gencod dont les écarts cumulés s'annulent au final (ex. -3 un jour, +3 un
autre) apparaît tout de même dans le résultat, puisqu'il a bien eu des
écarts significatifs au moins un jour de la période.

Usage :
  python3 cumul_controle_stocks.py --date-debut JJ/MM/AAAA --date-fin JJ/MM/AAAA
"""

import os
import sys
from datetime import date, timedelta

import controle_stocks as cs


def _parser_date(texte, nom_option):
    try:
        j, m, a = texte.split("/")
        return date(int(a), int(m), int(j))
    except Exception:
        print(f"Format de date invalide pour {nom_option} : {texte} (attendu JJ/MM/AAAA)")
        sys.exit(1)


def cumuler_periode(date_debut, date_fin, gencods_r1=None, libelles_dict=None):
    """Additionne par gencod les écarts ECART du contrôle de stocks sur
    [date_debut, date_fin] (bornes incluses).

    Pour chaque jour J de la période, reproduit le calcul de
    controle_stocks.py : stock du soir de J + ventes de J comparés au stock
    du matin de J+1. Un jour dont l'une des deux archives de stock est
    introuvable sur Drive est ignoré (compté séparément).

    Retourne (lignes, jours_ok, jours_ignores) :
      - lignes : [(gencod, nb_jours_ecart, ecart_cumule, libelle), ...] triée
        par |écart cumulé| décroissant ;
      - jours_ok : nombre de jours effectivement comparés ;
      - jours_ignores : liste des dates (date) sans archive disponible.
    """
    if gencods_r1 is None:
        gencods_r1 = cs.charger_gencods_r1()
    if libelles_dict is None:
        libelles_dict = cs.charger_libelles_dict()

    cumul          = {}
    nb_jours_ecart = {}
    libelles       = {}
    jours_ok       = 0
    jours_ignores  = []

    jour = date_debut
    while jour <= date_fin:
        lendemain = jour + timedelta(days=1)
        print(f"\n── {jour.strftime('%d/%m/%Y')} "
              f"(stock soir → stock matin du {lendemain.strftime('%d/%m/%Y')}) ──")

        chemin_soir  = f"_cumul_soir_{jour.strftime('%Y%m%d')}.xlsx"
        chemin_matin = f"_cumul_matin_{lendemain.strftime('%Y%m%d')}.xlsx"

        ok_soir = cs.telecharger_fichier_archive(
            "stocks", cs.nom_archive_stock(jour, "soir"), chemin_soir,
            root_id=cs.DRIVE_CONFIG_FOLDER_ID)
        ok_matin = cs.telecharger_fichier_archive(
            "stocks", cs.nom_archive_stock(lendemain, "matin"), chemin_matin,
            root_id=cs.DRIVE_CONFIG_FOLDER_ID)

        if not ok_soir or not ok_matin:
            print(f"  Archive(s) de stock manquante(s) — jour ignoré.")
            jours_ignores.append(jour)
            jour += timedelta(days=1)
            continue

        try:
            stock_j1, lib_j1, _ = cs.lire_stock(chemin_soir, classeur_requis=False)
            stock_j,  lib_j,  _ = cs.lire_stock(chemin_matin, classeur_requis=False)
        finally:
            for chemin in (chemin_soir, chemin_matin):
                if os.path.exists(chemin):
                    os.remove(chemin)

        ventes, lib_ventes = cs.generer_ventes(jour)

        tous = gencods_r1 if gencods_r1 is not None else (set(stock_j1) | set(stock_j))

        nb_ecarts_jour = 0
        for gencod in tous:
            if gencod not in stock_j1 or gencod not in stock_j:
                continue
            s_j1   = stock_j1.get(gencod, 0.0)
            v      = ventes.get(gencod, 0.0)
            s_theo = max(0.0, s_j1 - v)
            s_j    = stock_j.get(gencod, 0.0)
            ecart  = s_j - s_theo
            if abs(ecart) < 0.001:
                continue

            cumul[gencod]          = cumul.get(gencod, 0.0) + ecart
            nb_jours_ecart[gencod] = nb_jours_ecart.get(gencod, 0) + 1
            nb_ecarts_jour += 1
            if gencod not in libelles:
                lib = (libelles_dict.get(gencod) or lib_j.get(gencod)
                       or lib_j1.get(gencod) or lib_ventes.get(gencod, ''))
                if lib:
                    libelles[gencod] = lib

        print(f"  → {nb_ecarts_jour} écart(s) ce jour-là")
        jours_ok += 1
        jour += timedelta(days=1)

    lignes = [
        (gencod, nb_jours_ecart[gencod], ecart, libelles.get(gencod, ''))
        for gencod, ecart in cumul.items()
    ]
    lignes.sort(key=lambda r: abs(r[2]), reverse=True)
    return lignes, jours_ok, jours_ignores


def _construire_pdf_cumul(lignes, date_debut, date_fin, nom_pdf):
    """Génère le PDF du cumul (code-barres, libellé, jours en écart, écart
    cumulé). Retourne le chemin ou None si reportlab est indisponible."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.graphics.barcode import createBarcodeDrawing
    except Exception as e:
        print(f"  PDF ignoré : {e}")
        return None

    if not lignes:
        return None

    def make_barcode(code):
        try:
            return createBarcodeDrawing('EAN13', value=code, width=100, height=30,
                                        humanReadable=False)
        except Exception:
            return None

    doc = SimpleDocTemplate(nom_pdf, pagesize=A4,
                            topMargin=8 * mm, bottomMargin=8 * mm,
                            leftMargin=3 * mm, rightMargin=3 * mm)
    styles  = getSampleStyleSheet()
    small   = ParagraphStyle('small', fontSize=8, leading=10)
    small_c = ParagraphStyle('small_c', fontSize=8, leading=10, alignment=1)
    tiny_c  = ParagraphStyle('tiny_c', fontSize=7, leading=8, alignment=1)
    header_s = ParagraphStyle('hdr', fontSize=8, leading=10, textColor=colors.white)
    header_c = ParagraphStyle('hdr_c', parent=header_s, alignment=1)

    nb = len(lignes)
    titre_html = (f"<b>Cumul contrôle de stocks — {date_debut.strftime('%d/%m/%Y')} "
                  f"&rarr; {date_fin.strftime('%d/%m/%Y')}</b>"
                  f"&nbsp;&nbsp;({nb} gencod{'s' if nb > 1 else ''})")

    elements = [Paragraph(titre_html, styles['Title']), Spacer(1, 5 * mm)]

    col_widths = [108, 271, 68, 80]  # ≈ 527 pt
    hdr = [Paragraph('Code-barres', header_s), Paragraph('Libellé', header_s),
           Paragraph('Jours en écart', header_c), Paragraph('Écart cumulé', header_c)]
    data = [hdr]

    for gencod, nb_jours, ecart, lib in lignes:
        bc = make_barcode(gencod) if len(gencod) == 13 else None
        if bc:
            bc_cell = Table(
                [[bc], [Paragraph(gencod, tiny_c)]], colWidths=[108],
                style=TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ]),
            )
        else:
            bc_cell = Paragraph(gencod, small)
        data.append([
            bc_cell,
            Paragraph(lib, small),
            Paragraph(str(nb_jours), small_c),
            Paragraph(f"{int(ecart):+d}", small_c),
        ])

    BLEU = colors.HexColor('#006797')
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BLEU),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF6FB')]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ])
    for i, (_, _, ecart, _) in enumerate(lignes, 1):
        c = colors.HexColor('#D32F2F') if ecart < 0 else colors.HexColor('#E65100')
        style.add('TEXTCOLOR', (3, i), (3, i), c)
        style.add('FONTNAME', (3, i), (3, i), 'Helvetica-Bold')

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(style)
    elements.append(table)
    doc.build(elements)
    print(f"  → {nom_pdf} ({nb} ligne(s))")
    return nom_pdf


def envoyer_email_cumul(pdf, date_debut, date_fin, nb, manquant, surplus, jours_ok, jours_ignores):
    """Envoie par email (Gmail API) le PDF du cumul des écarts."""
    try:
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication

        svc = cs._get_gmail_service()
        if not svc:
            return

        label = f"{date_debut.strftime('%d/%m/%Y')} → {date_fin.strftime('%d/%m/%Y')}"
        msg = MIMEMultipart()
        msg['To']      = cs.EMAIL_DESTINATAIRE
        msg['Cc']      = cs.EMAIL_COPIE_STOCK
        msg['Subject'] = f"Cumul contrôle stocks {label} — {nb} écart{'s' if nb > 1 else ''} cumulé{'s' if nb > 1 else ''}"

        corps = (f"Cumul du contrôle de stocks {label}\n\n"
                 f"  Gencods en écart : {nb}\n"
                 f"  Jours comparés   : {jours_ok}\n")
        if jours_ignores:
            dates_ignorees = ", ".join(d.strftime('%d/%m/%Y') for d in jours_ignores)
            corps += f"  Jours ignorés    : {len(jours_ignores)} (archive(s) manquante(s) : {dates_ignorees})\n"
        corps += (f"  Total manquant   : {manquant:.0f} unités\n"
                  f"  Total surplus    : +{surplus:.0f} unités\n\n"
                  f"Détail en pièce jointe.")
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))

        with open(pdf, 'rb') as f:
            part = MIMEApplication(f.read(), 'pdf')
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf))
        msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email envoyé → {cs.EMAIL_DESTINATAIRE} (cc: {cs.EMAIL_COPIE_STOCK})")
    except Exception as e:
        print(f"  Email échoué : {e}")


def main():
    args = sys.argv[1:]

    date_debut = date_fin = None
    if "--date-debut" in args:
        i = args.index("--date-debut")
        if i + 1 < len(args):
            date_debut = _parser_date(args[i + 1], "--date-debut")
            args.pop(i + 1)
            args.pop(i)
    if "--date-fin" in args:
        i = args.index("--date-fin")
        if i + 1 < len(args):
            date_fin = _parser_date(args[i + 1], "--date-fin")
            args.pop(i + 1)
            args.pop(i)

    if date_debut is None or date_fin is None:
        print(__doc__)
        sys.exit(1)
    if date_fin < date_debut:
        print("ERREUR : --date-fin est antérieure à --date-debut.")
        sys.exit(1)

    cs._charger_config()

    print(f"Cumul du contrôle de stocks du {date_debut.strftime('%d/%m/%Y')} "
          f"au {date_fin.strftime('%d/%m/%Y')} …")

    lignes, jours_ok, jours_ignores = cumuler_periode(date_debut, date_fin)

    manquant = sum(r[2] for r in lignes if r[2] < 0)
    surplus  = sum(r[2] for r in lignes if r[2] > 0)

    print(f"\n── Résultats ──────────────────────────────────────")
    print(f"  Jours comparés    : {jours_ok}")
    if jours_ignores:
        print(f"  Jours ignorés     : {len(jours_ignores)} "
              f"({', '.join(d.strftime('%d/%m/%Y') for d in jours_ignores)})")
    print(f"  Gencods en écart  : {len(lignes)}")
    print(f"  Total manquant    : {manquant:.0f} unités")
    print(f"  Total surplus     : +{surplus:.0f} unités")

    if not lignes:
        print("\nAucun écart sur la période — pas de PDF ni d'email.")
        return

    print(f"\n  Top 10 écarts cumulés (|écart| décroissant) :")
    for gencod, nb_jours, ecart, lib in lignes[:10]:
        print(f"    {gencod}  écart_cumulé={ecart:+.0f}  ({nb_jours} jour(s) en écart)  {lib}")

    nom_pdf = f"cumul_ecarts_{date_debut.strftime('%Y%m%d')}_{date_fin.strftime('%Y%m%d')}.pdf"
    print("\nGénération PDF cumul …")
    pdf = _construire_pdf_cumul(lignes, date_debut, date_fin, nom_pdf)
    if pdf:
        print("\nEnvoi email …")
        envoyer_email_cumul(pdf, date_debut, date_fin, len(lignes), manquant, surplus,
                            jours_ok, jours_ignores)


if __name__ == "__main__":
    main()
