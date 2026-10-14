#!/usr/bin/env python3
"""Produits non adresses : relevé au fil de la journée, PDF envoyé le soir.

Un produit est « non adressé » quand prepa_drive_degrade ne trouve pas sa
place dans le chemin de préparation : il apparaît alors dans le bon de
préparation avec la mention ADRESSE INCONNUE (adresse absente de
gencod_adresses.csv, ou présente mais hors chemin, et nomenclature sans
correspondance) ou AUCUNE ADRESSE;AUCUNE ADRESSE (nomenclature hors chemin),
c'est-à-dire dans la zone des produits non adressés de l'appli.

- En cours de journée, auto_prepa.py appelle noter_produits_non_adresses()
  pour chaque bon généré : gencod, libellé, adresse actuelle et n° de commande
  sont ajoutés au fichier texte du jour, sur Drive :
  GITHUB/AdressesInconnues/adresses_inconnues_AAAA-MM-JJ.txt
- Le soir, le workflow « Adresses inconnues » lance ce script (main) : il
  regroupe chaque fichier du jour (et des jours précédents qui n'auraient pas
  été envoyés, run manqué), en fait un PDF (code-barres, libellé, adresse,
  commandes), l'envoie par email pour un traitement le lendemain matin, puis
  renomme le fichier en ..._envoye.txt pour ne jamais l'envoyer deux fois.

Usage : adresses_inconnues.py [--date JJ/MM/AAAA]   (défaut : jusqu'à aujourd'hui)
"""
import io
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Paris")

DOSSIER_GITHUB = "GITHUB"
DOSSIER = "AdressesInconnues"
PREFIXE = "adresses_inconnues_"
SUFFIXE_ENVOYE = "_envoye"
_RE_FICHIER = re.compile(r"^adresses_inconnues_(\d{4}-\d{2}-\d{2})(_envoye)?\.txt$")

# Fenêtre de l'historique affiché dans le PDF (nombre de jours où chaque
# produit est resté sans adresse) : les produits qui reviennent tous les jours
# passent en tête de liste.
JOURS_HISTORIQUE = 14

# Adresse placeholder écrite par prepa_drive_degrade quand le gencod n'a ni
# adresse ni nomenclature connue.
ADRESSE_ABSENTE = "M1-ZZ-0-0"


# ─────────────────────────────────────────────────────────────────
# Extraction depuis le bon de préparation
# ─────────────────────────────────────────────────────────────────

def extraire_produits_non_adresses(lignes_bon_prepa):
    """[(gencod, libelle, adresse)] des produits non adressés d'un
    bon_prepa.txt (liste de lignes, en-tête compris). `adresse` vaut "" quand
    le produit n'a aucune adresse connue (ni dans gencod_adresses.csv ni par
    sa nomenclature), sinon l'adresse actuelle, qui ne figure pas dans le
    chemin de préparation."""
    produits = []
    for ligne in lignes_bon_prepa[1:]:
        champs = ligne.rstrip("\r\n").split(";")
        # Préfixe parasite éventuel ("-N;" ou ";") devant le gencod, retiré
        # par auto_prepa.py au moment de l'écriture finale du bon.
        while champs and not re.fullmatch(r"\d{8,14}", champs[0]):
            champs = champs[1:]
        if len(champs) < 3:
            continue
        if "ADRESSE INCONNUE" in champs:
            idx = champs.index("ADRESSE INCONNUE")
            adresse = champs[idx - 1] if idx > 0 else ""
        elif "AUCUNE ADRESSE" in champs:
            idx = champs.index("AUCUNE ADRESSE")
            if idx + 1 >= len(champs) or champs[idx + 1] != "AUCUNE ADRESSE":
                continue  # replacé via sa nomenclature : il a bien une place
            adresse = ""
        else:
            continue
        if adresse == ADRESSE_ABSENTE or adresse == "AUCUNE ADRESSE":
            adresse = ""
        produits.append((champs[0], champs[1].strip(), adresse))
    return produits


# ─────────────────────────────────────────────────────────────────
# Fichier du jour sur Drive
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


def _dossier_adresses(drive_svc, creer=True):
    github_id = _sous_dossier(drive_svc, "root", DOSSIER_GITHUB, creer)
    return _sous_dossier(drive_svc, github_id, DOSSIER, creer) if github_id else None


def _telecharger_texte(drive_svc, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8")


def _ecrire_texte(drive_svc, dossier_id, nom, contenu, file_id=None):
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(io.BytesIO(contenu.encode("utf-8")),
                              mimetype="text/plain", resumable=False)
    if file_id:
        drive_svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        drive_svc.files().create(body={"name": nom, "parents": [dossier_id]},
                                 media_body=media, fields="id").execute()


def nom_fichier_jour(jour):
    return f"{PREFIXE}{jour.strftime('%Y-%m-%d')}.txt"


def noter_produits_non_adresses(drive_svc, numero, produits, jour=None):
    """Ajoute au fichier texte du jour une ligne
    « gencod;libellé;adresse;n° commande » par produit non adressé.
    Une commande régénérée n'est pas comptée deux fois (ses anciennes lignes
    sont remplacées). Ne lève jamais : un échec ne doit pas bloquer la
    génération du bon."""
    if not produits:
        return
    jour = jour or datetime.now(_TZ).date()
    nom = nom_fichier_jour(jour)
    try:
        dossier_id = _dossier_adresses(drive_svc)
        res = drive_svc.files().list(
            q=f"name='{nom}' and '{dossier_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        lignes = []
        if files:
            lignes = [l for l in _telecharger_texte(drive_svc, files[0]["id"]).splitlines()
                      if l.strip() and l.rsplit(";", 1)[-1] != str(numero)]
        for gencod, libelle, adresse in produits:
            lignes.append(f"{gencod};{libelle.replace(';', ' ')};{adresse};{numero}")
        _ecrire_texte(drive_svc, dossier_id, nom, "\n".join(lignes) + "\n",
                      files[0]["id"] if files else None)
        if files:
            # Le rapport du soir a pu envoyer puis renommer le fichier entre sa
            # lecture et sa réécriture ci-dessus : les lignes de cette commande
            # sont alors reportées dans un nouveau fichier du jour, envoyé au
            # rapport suivant, au lieu de se perdre dans le fichier déjà parti.
            nom_actuel = drive_svc.files().get(fileId=files[0]["id"], fields="name").execute().get("name")
            if nom_actuel != nom:
                nouvelles = [f"{g};{l.replace(';', ' ')};{a};{numero}" for g, l, a in produits]
                _ecrire_texte(drive_svc, dossier_id, nom, "\n".join(nouvelles) + "\n")
        print(f"    {len(produits)} produit(s) non adresse(s) note(s) dans {DOSSIER}/{nom}")
    except Exception as e:
        print(f"    Ecriture {DOSSIER}/{nom} echouee : {e}")


# ─────────────────────────────────────────────────────────────────
# Rapport du soir
# ─────────────────────────────────────────────────────────────────

def regrouper(contenu, annulees=()):
    """{gencod: {"libelle", "adresse", "commandes": [..]}} depuis le texte du
    fichier du jour (un produit vu dans plusieurs commandes n'apparaît qu'une
    fois ; les commandes annulées ou remplacées sont ignorées)."""
    produits = {}
    for ligne in contenu.splitlines():
        champs = ligne.strip().split(";")
        if len(champs) < 4 or not champs[0]:
            continue
        gencod, libelle, adresse, numero = champs[0], champs[1], champs[2], champs[3]
        if numero in annulees:
            continue
        p = produits.setdefault(gencod, {"libelle": libelle, "adresse": adresse,
                                         "commandes": []})
        if adresse and not p["adresse"]:
            p["adresse"] = adresse
        if numero not in p["commandes"]:
            p["commandes"].append(numero)
    return produits


def generer_pdf(produits, jour, chemin):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.graphics.barcode import createBarcodeDrawing

    small = ParagraphStyle("small", fontSize=8, leading=10)
    small_c = ParagraphStyle("small_c", parent=small, alignment=1)
    tiny_c = ParagraphStyle("tiny_c", fontSize=7, leading=8, alignment=1)
    entete = ParagraphStyle("hdr", fontSize=8, leading=10, textColor=colors.white)

    def cellule_code_barres(gencod):
        try:
            if len(gencod) != 13:
                raise ValueError
            dessin = createBarcodeDrawing("EAN13", value=gencod, width=100,
                                          height=30, humanReadable=False)
        except Exception:
            return Paragraph(gencod, small)
        return Table([[dessin], [Paragraph(gencod, tiny_c)]], colWidths=[108],
                     style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")] + [
                         (p, (0, 0), (-1, -1), 0) for p in
                         ("TOPPADDING", "BOTTOMPADDING", "LEFTPADDING", "RIGHTPADDING")]))

    data = [[Paragraph(t, entete) for t in
             ("Code-barres", "Libellé", "Adresse actuelle", "Commande(s)",
              f"Jours sans adresse ({JOURS_HISTORIQUE} j)")]]
    for gencod, p in sorted(produits.items(),
                            key=lambda kv: (-kv[1].get("jours", 1), kv[1]["libelle"])):
        data.append([
            cellule_code_barres(gencod),
            Paragraph(p["libelle"], small),
            Paragraph(p["adresse"] or "aucune", small_c),
            Paragraph("<br/>".join(p["commandes"]), small_c),
            Paragraph(str(p.get("jours", 1)), small_c),
        ])

    doc = SimpleDocTemplate(chemin, pagesize=A4, topMargin=8 * mm, bottomMargin=8 * mm,
                            leftMargin=3 * mm, rightMargin=3 * mm)
    table = Table(data, colWidths=[108, 209, 80, 70, 60], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#006797")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF6FB")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    titre = (f"Produits non adressés — {jour.strftime('%d/%m/%Y')} "
             f"({len(produits)} produit{'s' if len(produits) > 1 else ''})")
    doc.build([Paragraph(titre, getSampleStyleSheet()["Title"]), Spacer(1, 4 * mm), table])
    return chemin


def envoyer_email(gmail_svc, destinataire, copie, pdfs):
    """pdfs : [(jour, chemin, nb_produits)]"""
    import base64
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    total = sum(n for _, _, n in pdfs)
    jours = ", ".join(j.strftime("%d/%m/%Y") for j, _, _ in pdfs)
    msg = MIMEMultipart()
    msg["To"] = destinataire
    if copie:
        msg["Cc"] = copie
    msg["Subject"] = f"Produits non adressés {jours} — {total} produit{'s' if total > 1 else ''}"
    msg.attach(MIMEText(
        f"Bonjour,\n\n{total} produit{'s' if total > 1 else ''} commandé"
        f"{'s' if total > 1 else ''} sur le Drive n'"
        f"{'ont' if total > 1 else 'a'} pas d'adresse dans le chemin de "
        f"préparation ({jours}).\nIl{'s sont' if total > 1 else ' est'} "
        f"passé{'s' if total > 1 else ''} en zone non adressée de l'appli.\n\n"
        f"La liste (code-barres, libellé, adresse actuelle, commandes) est en "
        f"pièce jointe, à traiter demain matin : adresser ces produits dans "
        f"gencod_adresses.csv / chemin_prepa_mono.csv.\n", "plain", "utf-8"))
    for _, chemin, _ in pdfs:
        with open(chemin, "rb") as f:
            part = MIMEApplication(f.read(), "pdf")
        part.add_header("Content-Disposition", "attachment", filename=os.path.basename(chemin))
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()


def _tous_les_fichiers(drive_svc, dossier_id):
    """[(jour, file_id, nom, envoye)] de tous les fichiers du dossier."""
    fichiers, jeton = [], None
    while True:
        res = drive_svc.files().list(
            q=f"'{dossier_id}' in parents and trashed=false and name contains '{PREFIXE}'",
            fields="nextPageToken, files(id,name)", pageSize=1000, pageToken=jeton,
        ).execute()
        fichiers += res.get("files", [])
        jeton = res.get("nextPageToken")
        if not jeton:
            break
    trouves = []
    for f in fichiers:
        m = _RE_FICHIER.match(f["name"])
        if m:
            jour = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            trouves.append((jour, f["id"], f["name"], bool(m.group(2))))
    return sorted(trouves)


def fichiers_a_envoyer(drive_svc, jusqu_au):
    """[(jour, file_id, nom)] des fichiers du dossier non encore envoyés,
    datés au plus tard de `jusqu_au`, du plus ancien au plus récent."""
    dossier_id = _dossier_adresses(drive_svc, creer=False)
    if not dossier_id:
        return dossier_id, []
    return dossier_id, [(j, i, n) for j, i, n, envoye in _tous_les_fichiers(drive_svc, dossier_id)
                        if not envoye and j <= jusqu_au]


def jours_sans_adresse(drive_svc, jusqu_au):
    """{gencod: nombre de jours} où le produit est resté sans adresse sur les
    JOURS_HISTORIQUE derniers jours (fichiers envoyés compris)."""
    from datetime import timedelta
    dossier_id = _dossier_adresses(drive_svc, creer=False)
    if not dossier_id:
        return {}
    debut = jusqu_au - timedelta(days=JOURS_HISTORIQUE - 1)
    vus = {}
    for jour, file_id, _, _ in _tous_les_fichiers(drive_svc, dossier_id):
        if debut <= jour <= jusqu_au:
            for gencod in regrouper(_telecharger_texte(drive_svc, file_id)):
                vus.setdefault(gencod, set()).add(jour)
    return {g: len(j) for g, j in vus.items()}


def main():
    import controle_stocks as cs

    jusqu_au = datetime.now(_TZ).date()
    if "--date" in sys.argv:
        jusqu_au = datetime.strptime(sys.argv[sys.argv.index("--date") + 1], "%d/%m/%Y").date()

    cs._charger_config()
    drive_svc = cs._get_drive_service()
    gmail_svc = cs._get_gmail_service()
    if not drive_svc or not gmail_svc:
        print("ERREUR : Drive ou Gmail inaccessible.")
        sys.exit(1)

    _, fichiers = fichiers_a_envoyer(drive_svc, jusqu_au)
    if not fichiers:
        print("Aucun produit non adressé à signaler.")
        return

    annulees = cs.numeros_annules_registre()
    historique = jours_sans_adresse(drive_svc, jusqu_au)
    pdfs, envoyes = [], []
    for jour, file_id, nom in fichiers:
        produits = regrouper(_telecharger_texte(drive_svc, file_id), annulees)
        for gencod, p in produits.items():
            p["jours"] = max(1, historique.get(gencod, 1))
        envoyes.append((file_id, nom))
        if not produits:
            continue
        chemin = f"produits_non_adresses_{jour.strftime('%d_%m_%Y')}.pdf"
        generer_pdf(produits, jour, chemin)
        pdfs.append((jour, chemin, len(produits)))
        print(f"{nom} : {len(produits)} produit(s) non adressé(s).")

    if pdfs:
        envoyer_email(gmail_svc, cs.EMAIL_DESTINATAIRE, cs.EMAIL_COPIE_STOCK, pdfs)
        print("Email envoyé.")
    for file_id, nom in envoyes:
        drive_svc.files().update(
            fileId=file_id, body={"name": nom.replace(".txt", f"{SUFFIXE_ENVOYE}.txt")},
        ).execute()


if __name__ == "__main__":
    main()
