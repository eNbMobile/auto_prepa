import io, re, os, json, tempfile
import pdfplumber
import barcode
from barcode.writer import ImageWriter
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from datetime import date

FOLDER_ID      = "14m48VX6jTus5l3qNuHxBdc4eRTjZqz9w"
ARCHIVES_ID    = "1WyJ7BVEd485l7tGoURJ3tJZoPb8KeurU"
INPUT_FILENAME = "manquants.pdf"

def get_drive_service():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(token_json)
        tmp.close()
        creds = Credentials.from_authorized_user_file(tmp.name)
        os.unlink(tmp.name)
    else:
        token_file = os.path.expanduser("~/.auto_prepa_token.json")
        creds = Credentials.from_authorized_user_file(token_file)
    return build("drive", "v3", credentials=creds)

def find_file(service, name, parent_id):
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    res = service.files().list(q=q, fields="files(id,name,modifiedTime)").execute()
    files = res.get("files", [])
    return files[0] if files else None

def download_file(service, file_id, dest_path):
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

def copy_to_archives(service, file_id, archive_name):
    body = {"name": archive_name, "parents": [ARCHIVES_ID]}
    service.files().copy(fileId=file_id, body=body).execute()

def upload_to_archives(service, local_path, archive_name):
    body = {"name": archive_name, "parents": [ARCHIVES_ID]}
    media = MediaFileUpload(local_path, mimetype="application/pdf")
    service.files().create(body=body, media_body=media).execute()

def parse_price(text, key):
    m = re.search(re.escape(key) + r'\s*:?\s*([\d,]+)\s*€', text)
    return float(m.group(1).replace(',', '.')) if m else 0.0

def parse_int(text, key):
    m = re.search(re.escape(key) + r'\s*:?\s*(\d+)', text)
    return int(m.group(1)) if m else 0

def parse_libelle(col1_text):
    m = re.search(r'Libellé :(.+?)(?=Substitution autorisée|Prix unitaire)', col1_text, re.DOTALL)
    return ' '.join(m.group(1).split()) if m else ""

def extract_doc_date(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    return (m.group(1) + m.group(2) + m.group(3)) if m else date.today().strftime("%d%m%Y")

def parse_rows(pdf_path):
    produits = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                for row in table:
                    if not row or not row[1]:
                        continue
                    col1 = row[1] or ""
                    col2 = row[2] or ""
                    col3 = row[3] or ""
                    col4 = row[4] or ""
                    ean_m = re.search(r'Ean :(\d{13})', col1)
                    if not ean_m:
                        continue
                    type_m = re.search(r'Type :(Rupture|Substitution)', col3)
                    if not type_m:
                        continue
                    ean             = ean_m.group(1)
                    type_val        = type_m.group(1)
                    libelle         = parse_libelle(col1)
                    qty_a_collecter = parse_int(col2, "Quantité à collecter")
                    qty_collectee   = parse_int(col2, "Quantité collectée")
                    prix_orig       = parse_price(col1, "Prix unitaire")

                    if type_val == "Rupture":
                        qty_rupt = parse_int(col4, "Quantité rupture") or (qty_a_collecter - qty_collectee)
                        produits.append({
                            "ean": ean, "libelle": libelle, "type": "Rupture",
                            "qty_display": qty_rupt, "qty_manquant": qty_rupt,
                            "prix_orig": prix_orig, "qty_subst": None, "prix_subst": None,
                        })
                    else:
                        qty_subst  = parse_int(col4, "Quantité substitution")
                        prix_subst = parse_price(col4, "Prix unitaire substituant")
                        produits.append({
                            "ean": ean, "libelle": libelle, "type": "Substitution",
                            "qty_display": qty_subst,
                            "qty_manquant": qty_a_collecter - qty_collectee,
                            "prix_orig": prix_orig, "qty_subst": qty_subst, "prix_subst": prix_subst,
                        })
    return produits

def calc_ca_perdu(p):
    if p["type"] == "Rupture":
        return p["qty_manquant"] * p["prix_orig"]
    return max(0.0, p["qty_manquant"] * p["prix_orig"] - p["qty_subst"] * p["prix_subst"])

def aggregate(rows):
    merged = {}
    for p in rows:
        ean = p["ean"]
        if ean not in merged:
            merged[ean] = p.copy()
            merged[ean]["ca_perdu"] = calc_ca_perdu(p)
        else:
            merged[ean]["qty_display"]  += p["qty_display"]
            merged[ean]["qty_manquant"] += p["qty_manquant"]
            merged[ean]["ca_perdu"]     += calc_ca_perdu(p)
    return list(merged.values())

def make_barcode_image(ean_str, width_cm=2.9):
    ean_cls = barcode.get_barcode_class("ean13")
    buf = io.BytesIO()
    ean_cls(ean_str, writer=ImageWriter()).write(buf, options={
        "module_width": 0.25, "module_height": 10.0,
        "quiet_zone": 2.0, "font_size": 0,
        "text_distance": 1.0, "write_text": False,
    })
    buf.seek(0)
    img = PILImage.open(buf)
    target_w = width_cm * cm
    target_h = img.size[1] * (target_w / img.size[0])
    buf2 = io.BytesIO()
    img.save(buf2, format="PNG")
    buf2.seek(0)
    return Image(buf2, width=target_w, height=target_h)
cell_style     = ParagraphStyle("cell",     fontSize=8, fontName="Helvetica",      leading=11)
cell_bold      = ParagraphStyle("cellbold", fontSize=8, fontName="Helvetica-Bold", leading=11)
ean_text_style = ParagraphStyle("ean_text", fontSize=7, fontName="Helvetica",
                                alignment=TA_CENTER, spaceBefore=-4)

def ean_cell(ean_str):
    bc = make_barcode_image(ean_str, width_cm=2.9)
    bc.hAlign = "CENTER"
    return [bc, Paragraph(ean_str, ean_text_style)]

def build_pdf(produits, output_path):
    data = [["EAN", "Libellé", "Quantité", "Type", "CA perdu"]]
    for p in produits:
        ca     = p["ca_perdu"]
        ca_str = f"{ca:.2f} €".replace(".", ",") if ca > 0 else "0,00 €"
        data.append([
            ean_cell(p["ean"]),
            Paragraph(p["libelle"], cell_style),
            Paragraph(str(p["qty_display"]), cell_style),
            Paragraph(p["type"], cell_bold),
            Paragraph(ca_str, cell_bold),
        ])

    col_widths = [3.2*cm, 10.7*cm, 1.5*cm, 2.2*cm, 2.0*cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND",    (0, 0), (-1, -1), colors.white),
        ("BACKGROUND",    (0, 0), (-1,  0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,  0), 9),
        ("ALIGN",         (0, 0), (-1,  0), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR",     (4, 1), (4, -1),  colors.HexColor("#C0392B")),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]
    for i, p in enumerate(produits, 1):
        color = colors.HexColor("#C0392B") if p["type"] == "Rupture" else colors.HexColor("#2980B9")
        style.append(("TEXTCOLOR", (3, i), (3, i), color))
    table.setStyle(TableStyle(style))
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=0.7*cm, rightMargin=0.7*cm,
                            topMargin=0.7*cm, bottomMargin=0.7*cm)
    doc.build([table])

if __name__ == "__main__":
    service = get_drive_service()
    print(f"Recherche de '{INPUT_FILENAME}' dans Drive...")
    file_meta = find_file(service, INPUT_FILENAME, FOLDER_ID)
    if not file_meta:
        raise FileNotFoundError(f"'{INPUT_FILENAME}' introuvable dans le dossier Drive.")
    file_id = file_meta["id"]
    print(f"  Trouvé : id={file_id}")
    tmp_path = os.path.join(tempfile.gettempdir(), INPUT_FILENAME)
    print(f"Téléchargement vers {tmp_path}...")
    download_file(service, file_id, tmp_path)
    doc_date     = extract_doc_date(tmp_path)
    archive_name = f"Manquants_{doc_date}.pdf"
    print(f"Archivage sous : {archive_name}")
    copy_to_archives(service, file_id, archive_name)
    print("  Archivé dans le dossier archives.")
    print("Analyse du PDF...")
    produits = aggregate(parse_rows(tmp_path))
    print(f"  {len(produits)} produits uniques trouvés.")
    out_path     = os.path.join(tempfile.gettempdir(), "ruptures_substitutions.pdf")
    out_name     = f"Manquants_2_{doc_date}.pdf"
    build_pdf(produits, out_path)
    print(f"PDF généré : {out_path}")
    upload_to_archives(service, out_path, out_name)
    print(f"Uploadé sur Drive : archives/{out_name}")
