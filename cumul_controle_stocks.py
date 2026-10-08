#!/usr/bin/env python3
"""
Cumul du contrôle de stocks sur une période (d'une date à une autre, bornes
incluses).

Se base sur les PDF réellement envoyés par email chaque jour où le contrôle
de stocks a tourné (sujet « Contrôle stocks … », cf. controle_stocks.py) —
pas sur un recalcul depuis les archives de stocks : ce sont les écarts
effectivement rapportés qui comptent. Si plusieurs emails concernent le même
jour (relance manuelle), seul le dernier envoyé est retenu. Un jour sans
email (ex. dimanche, pas de contrôle lancé) ou sans PDF d'écarts joint
(aucun écart ce jour-là) ne contribue simplement pas au cumul — ni les
stocks insuffisants, ni les articles à déloter n'en font partie.

Un gencod dont les écarts cumulés s'annulent au final (ex. -3 un jour, +3 un
autre) apparaît tout de même dans le résultat, puisqu'il a bien eu des
écarts significatifs au moins un jour de la période.

Usage :
  python3 cumul_controle_stocks.py --date-debut JJ/MM/AAAA --date-fin JJ/MM/AAAA
"""

import base64
import os
import re
import subprocess
import sys
from datetime import date, timedelta

import controle_stocks as cs

_RE_DATE_SUJET  = re.compile(r'(\d{2}/\d{2}/\d{4})')
_RE_LIGNE_ECART = re.compile(r'^\s*(\S.*)\s+\d+\s+\d+\s+\d+\s+\d+\s+([+-]\d+)\s*$')
_RE_GENCOD_SEUL = re.compile(r'^\s*(\d{8,13})\s*$')

PREFIXE_SUJET = "Contrôle stocks "


def _parser_date(texte, nom_option):
    try:
        j, m, a = texte.split("/")
        return date(int(a), int(m), int(j))
    except Exception:
        print(f"Format de date invalide pour {nom_option} : {texte} (attendu JJ/MM/AAAA)")
        sys.exit(1)


def _trouver_pj_ecarts(payload):
    """Cherche récursivement la pièce jointe 'ecarts_*.pdf' dans le payload
    Gmail d'un message. Retourne (nom_fichier, attachment_id) ou (None, None)."""
    nom = payload.get('filename', '') or ''
    if nom.startswith('ecarts_') and nom.endswith('.pdf'):
        attachment_id = payload.get('body', {}).get('attachmentId')
        if attachment_id:
            return nom, attachment_id
    for part in payload.get('parts', []) or []:
        nom, attachment_id = _trouver_pj_ecarts(part)
        if attachment_id:
            return nom, attachment_id
    return None, None


def lister_emails_controle(date_debut, date_fin):
    """Cherche, parmi les emails « Contrôle stocks … » envoyés, celui (le
    plus récent en cas de doublon) correspondant à chaque jour de
    [date_debut, date_fin] — le jour étant la dernière date mentionnée dans
    le sujet (le dernier jour de ventes du contrôle quotidien).

    Retourne {jour (date): (message_id, nom_pj, attachment_id) | None} —
    None si aucun email « Contrôle stocks » n'a été trouvé pour ce jour.
    attachment_id est None si l'email trouvé n'a pas de PDF d'écarts joint
    (aucun écart ce jour-là).
    """
    svc = cs._get_gmail_service()
    if not svc:
        print("  Gmail inaccessible.")
        return {}

    apres  = (date_debut - timedelta(days=1)).strftime('%Y/%m/%d')
    avant  = (date.today() + timedelta(days=1)).strftime('%Y/%m/%d')
    query  = f'in:sent "Contrôle stocks" after:{apres} before:{avant}'

    messages = []
    page_token = None
    while True:
        params = {'userId': 'me', 'q': query, 'maxResults': 100}
        if page_token:
            params['pageToken'] = page_token
        res = svc.users().messages().list(**params).execute()
        messages.extend(res.get('messages', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break

    print(f"  {len(messages)} email(s) candidat(s) trouvé(s) sur Gmail.")

    retenu_par_jour = {}  # jour -> (internalDate, message_id, nom_pj, attachment_id)
    for m in messages:
        detail = svc.users().messages().get(userId='me', id=m['id'], format='full').execute()
        headers = detail.get('payload', {}).get('headers', [])
        sujet = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        if not sujet.startswith(PREFIXE_SUJET):
            continue

        dates_sujet = _RE_DATE_SUJET.findall(sujet)
        if not dates_sujet:
            continue
        try:
            j, mo, a = dates_sujet[-1].split('/')
            jour = date(int(a), int(mo), int(j))
        except Exception:
            continue
        if jour < date_debut or jour > date_fin:
            continue

        internal_date = int(detail.get('internalDate', '0'))
        nom_pj, attachment_id = _trouver_pj_ecarts(detail.get('payload', {}))

        actuel = retenu_par_jour.get(jour)
        if actuel is None or internal_date > actuel[0]:
            retenu_par_jour[jour] = (internal_date, m['id'], nom_pj, attachment_id)

    resultat = {}
    jour = date_debut
    while jour <= date_fin:
        entree = retenu_par_jour.get(jour)
        resultat[jour] = (entree[1], entree[2], entree[3]) if entree else None
        jour += timedelta(days=1)
    return resultat


def telecharger_piece_jointe(message_id, attachment_id, dest):
    """Télécharge une pièce jointe Gmail (par id de message + d'attachment)
    vers dest. Retourne dest."""
    svc = cs._get_gmail_service()
    pj = svc.users().messages().attachments().get(
        userId='me', messageId=message_id, id=attachment_id).execute()
    data = base64.urlsafe_b64decode(pj['data'])
    with open(dest, 'wb') as f:
        f.write(data)
    return dest


def parser_pdf_ecarts(chemin_pdf):
    """Extrait [(gencod, libelle, ecart), ...] du PDF 'écarts' tel qu'envoyé
    par email (format complet de controle_stocks.py : Code-barres / Libellé /
    J-1 / Ventes / Théo / J / Écart — le gencod est imprimé en texte sous le
    code-barres, sur la ligne suivante)."""
    pt = subprocess.run(["pdftotext", "-layout", chemin_pdf, "-"],
                        capture_output=True, text=True)
    resultats = []
    pending = None
    for ligne in pt.stdout.splitlines():
        m_gencod = _RE_GENCOD_SEUL.match(ligne)
        if m_gencod and pending is not None:
            resultats.append((m_gencod.group(1).zfill(13), pending[0].strip(), pending[1]))
            pending = None
            continue
        m_ecart = _RE_LIGNE_ECART.match(ligne)
        if m_ecart:
            pending = (m_ecart.group(1), int(m_ecart.group(2)))
    return resultats


def cumuler_periode(date_debut, date_fin):
    """Additionne par gencod les écarts des PDF « Contrôle stocks » réellement
    envoyés par email sur [date_debut, date_fin] (bornes incluses) — le
    dernier email envoyé pour un jour donné si plusieurs s'y rapportent.

    Retourne (lignes, jours_avec_ecarts, jours_sans_ecarts, jours_sans_email) :
      - lignes : [(gencod, nb_jours_ecart, ecart_cumule, libelle), ...] triée
        par |écart cumulé| décroissant ;
      - jours_avec_ecarts : jours dont le PDF d'écarts a été trouvé et lu ;
      - jours_sans_ecarts : jours avec un email « Contrôle stocks » envoyé
        mais sans PDF d'écarts joint (aucun écart ce jour-là) ;
      - jours_sans_email : jours sans aucun email « Contrôle stocks » trouvé
        (contrôle non lancé, ou non envoyé — ex. dimanche sans ventes).
    """
    emails_par_jour = lister_emails_controle(date_debut, date_fin)

    cumul          = {}
    nb_jours_ecart = {}
    libelles       = {}
    jours_avec_ecarts = []
    jours_sans_ecarts = []
    jours_sans_email  = []

    jour = date_debut
    while jour <= date_fin:
        entree = emails_par_jour.get(jour)
        if entree is None:
            jours_sans_email.append(jour)
            jour += timedelta(days=1)
            continue

        message_id, nom_pj, attachment_id = entree
        if not attachment_id:
            jours_sans_ecarts.append(jour)
            jour += timedelta(days=1)
            continue

        chemin_pdf = f"_cumul_ecarts_{jour.strftime('%Y%m%d')}.pdf"
        telecharger_piece_jointe(message_id, attachment_id, chemin_pdf)
        try:
            lignes_jour = parser_pdf_ecarts(chemin_pdf)
        finally:
            if os.path.exists(chemin_pdf):
                os.remove(chemin_pdf)

        print(f"  {jour.strftime('%d/%m/%Y')} : {nom_pj} → {len(lignes_jour)} écart(s)")
        jours_avec_ecarts.append(jour)
        for gencod, lib, ecart in lignes_jour:
            cumul[gencod]          = cumul.get(gencod, 0) + ecart
            nb_jours_ecart[gencod] = nb_jours_ecart.get(gencod, 0) + 1
            if lib and gencod not in libelles:
                libelles[gencod] = lib

        jour += timedelta(days=1)

    lignes = [
        (gencod, nb_jours_ecart[gencod], ecart, libelles.get(gencod, ''))
        for gencod, ecart in cumul.items()
    ]
    lignes.sort(key=lambda r: abs(r[2]), reverse=True)
    return lignes, jours_avec_ecarts, jours_sans_ecarts, jours_sans_email


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


def envoyer_email_cumul(pdf, date_debut, date_fin, nb, manquant, surplus,
                        jours_avec_ecarts, jours_sans_ecarts, jours_sans_email):
    """Envoie par email (Gmail API) le PDF du cumul des écarts."""
    try:
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
        msg['Subject'] = (f"Cumul contrôle stocks {label} — "
                          f"{nb} écart{'s' if nb > 1 else ''} cumulé{'s' if nb > 1 else ''}")

        corps = (f"Cumul du contrôle de stocks {label}\n\n"
                 f"  Gencods en écart     : {nb}\n"
                 f"  Jours avec écarts    : {len(jours_avec_ecarts)}\n"
                 f"  Jours sans écart     : {len(jours_sans_ecarts)}\n")
        if jours_sans_email:
            dates_manquantes = ", ".join(d.strftime('%d/%m/%Y') for d in jours_sans_email)
            corps += (f"  Jours sans contrôle envoyé : {len(jours_sans_email)} "
                      f"({dates_manquantes})\n")
        corps += (f"  Total manquant       : {manquant:.0f} unités\n"
                  f"  Total surplus        : +{surplus:.0f} unités\n\n"
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
          f"au {date_fin.strftime('%d/%m/%Y')} (d'après les emails envoyés) …")

    lignes, jours_avec_ecarts, jours_sans_ecarts, jours_sans_email = cumuler_periode(
        date_debut, date_fin)

    manquant = sum(r[2] for r in lignes if r[2] < 0)
    surplus  = sum(r[2] for r in lignes if r[2] > 0)

    print(f"\n── Résultats ──────────────────────────────────────")
    print(f"  Jours avec écarts envoyés : {len(jours_avec_ecarts)}")
    print(f"  Jours sans écart          : {len(jours_sans_ecarts)}")
    if jours_sans_email:
        print(f"  Jours sans contrôle envoyé : {len(jours_sans_email)} "
              f"({', '.join(d.strftime('%d/%m/%Y') for d in jours_sans_email)})")
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
                            jours_avec_ecarts, jours_sans_ecarts, jours_sans_email)


if __name__ == "__main__":
    main()
