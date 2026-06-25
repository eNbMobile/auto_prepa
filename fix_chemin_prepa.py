#!/usr/bin/env python3
"""
Surveille les emails "bon de prepa invalide", extrait les gencods
des lignes invalides, et ajoute leurs adresses manquantes dans
chemin_prepa_mono.csv sur Drive.
"""
import base64
import io
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import controle_stocks as cs

LABEL_NOM    = "chemin_fix_traite"
NOM_CHEMIN   = "chemin_prepa_mono.csv"
NOM_GENCOD   = "gencod_adresses.csv"
EXPECTED_SEP = 13

# Correspond à "ligne N (M sep.) : <contenu>"
RE_DETAIL = re.compile(r'ligne\s+\d+\s*\(\d+\s*sep', re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────
# Gmail helpers
# ─────────────────────────────────────────────────────────────────

def _get_ou_creer_label(svc, nom):
    """Retourne l'id du label Gmail, le crée si absent."""
    res = svc.users().labels().list(userId="me").execute()
    for lbl in res.get("labels", []):
        if lbl["name"].lower() == nom.lower():
            return lbl["id"]
    lbl = svc.users().labels().create(
        userId="me",
        body={"name": nom, "labelListVisibility": "labelHide",
              "messageListVisibility": "hide"},
    ).execute()
    return lbl["id"]


def _decoder_body(payload):
    """Extrait le texte brut d'un payload de message Gmail."""
    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

    if mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            texte = _decoder_body(part)
            if texte:
                return texte

    return ""


def lire_emails_invalides(svc):
    """
    Retourne une liste de (message_id, [gencods]) pour les emails
    "bon de prepa invalide" non encore traités.
    """
    query = f'subject:"bon de prepa invalide" -label:{LABEL_NOM}'
    res = svc.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = res.get("messages", [])
    if not messages:
        return []

    resultats = []
    for m in messages:
        msg = svc.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        texte = _decoder_body(msg["payload"])
        gencods = _extraire_gencods(texte)
        if gencods:
            resultats.append((m["id"], gencods))
        else:
            # Email invalide sans gencod reconnu → marquer quand même
            resultats.append((m["id"], []))
    return resultats


def _extraire_gencods(texte):
    """Extrait les gencods des lignes "ligne N (M sep.) : gencod;..." du texte."""
    gencods = []
    for ligne in texte.splitlines():
        if not RE_DETAIL.search(ligne):
            continue
        # La partie après ":" contient la ligne du bon de prépa
        idx = ligne.find(":")
        if idx == -1:
            continue
        contenu = ligne[idx + 1:].strip()
        if not contenu:
            continue
        premier_champ = contenu.split(";")[0].strip()
        if re.match(r"^\d{5,13}$", premier_champ):
            g = premier_champ.lstrip("0").zfill(13)
            if g not in gencods:
                gencods.append(g)
    return gencods


# ─────────────────────────────────────────────────────────────────
# Drive helpers
# ─────────────────────────────────────────────────────────────────

def _upload_config_drive(nom, contenu_str):
    """Upload/mise à jour d'un fichier texte dans DRIVE_CONFIG_FOLDER_ID."""
    try:
        from googleapiclient.http import MediaFileUpload
        svc = cs._get_drive_service()
        if not svc:
            print(f"  Drive inaccessible — upload {nom} ignoré.")
            return False
        folder_id = cs.DRIVE_CONFIG_FOLDER_ID
        res = svc.files().list(
            q=f"name='{nom}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = res.get("files", [])

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(contenu_str)
            tmp_path = tmp.name

        try:
            media = MediaFileUpload(tmp_path, mimetype="text/plain", resumable=False)
            if existing:
                svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            else:
                svc.files().create(
                    body={"name": nom, "parents": [folder_id]},
                    media_body=media, fields="id",
                ).execute()
            print(f"  {nom} → Drive config OK")
            return True
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        print(f"  Upload config {nom} échoué : {e}")
        return False


def charger_gencod_adresses():
    """Retourne {gencod: adresse} depuis gencod_adresses.csv sur Drive."""
    contenu = cs._lire_config_drive(NOM_GENCOD)
    if contenu is None:
        return {}
    d = {}
    for line in contenu.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(";", 1)
        if len(parts) < 2:
            continue
        g = parts[0].strip()
        if g.isdigit():
            g = g.lstrip("0").zfill(13)
        d[g] = parts[1].strip()
    return d


def charger_chemin_prepa():
    """Retourne la liste des adresses de chemin_prepa_mono.csv (une par ligne)."""
    contenu = cs._lire_config_drive(NOM_CHEMIN)
    if contenu is None:
        return None, None
    lignes = [l.rstrip("\r\n") for l in contenu.splitlines()]
    adresses = [l for l in lignes if l.strip()]
    return adresses, set(a.strip() for a in adresses)


# ─────────────────────────────────────────────────────────────────
# Email de confirmation
# ─────────────────────────────────────────────────────────────────

def envoyer_email_confirmation(adresses_ajoutees, gencods_inconnus):
    """Envoie un email récapitulatif des modifications apportées."""
    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        svc = cs._get_gmail_service()
        if not svc or not cs.EMAIL_DESTINATAIRE:
            return

        nb = len(adresses_ajoutees)
        msg = MIMEMultipart()
        msg["To"] = cs.EMAIL_DESTINATAIRE
        msg["Subject"] = (
            f"[Auto-fix] chemin_prepa_mono — {nb} adresse(s) ajoutée(s)"
        )

        corps = "Correction automatique de chemin_prepa_mono.csv\n"
        corps += "=" * 55 + "\n\n"
        corps += f"{nb} adresse(s) ajoutée(s) en fin de fichier :\n"
        for a in adresses_ajoutees:
            corps += f"  + {a}\n"
        if gencods_inconnus:
            corps += f"\n{len(gencods_inconnus)} gencod(s) absent(s) de gencod_adresses.csv :\n"
            for g in gencods_inconnus:
                corps += f"  ? {g}\n"
            corps += "  → Ces gencods nécessitent une intervention manuelle.\n"
        corps += (
            "\nLes prochains bons de préparation utiliseront les adresses "
            "mises à jour.\n"
        )

        msg.attach(MIMEText(corps, "plain", "utf-8"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Email de confirmation envoyé → {cs.EMAIL_DESTINATAIRE}")
    except Exception as e:
        print(f"  Email de confirmation échoué : {e}")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    if not cs.DRIVE_CONFIG_FOLDER_ID:
        print("DRIVE_CONFIG_FOLDER_ID manquant — abandon.")
        sys.exit(0)

    # 1. Lire les emails non traités
    print("Recherche d'emails 'bon de prepa invalide' non traités …")
    svc_gmail = cs._get_gmail_service()
    if not svc_gmail:
        print("Gmail inaccessible — abandon.")
        sys.exit(0)

    emails = lire_emails_invalides(svc_gmail)
    if not emails:
        print("Aucun email non traité trouvé.")
        sys.exit(0)

    print(f"  {len(emails)} email(s) à traiter.")

    # 2. Collecter tous les gencods uniques
    tous_gencods = set()
    tous_ids = []
    for msg_id, gencods in emails:
        tous_gencods.update(gencods)
        tous_ids.append(msg_id)

    if not tous_gencods:
        print("  Aucun gencod extrait — marquage des emails comme traités.")
        label_id = _get_ou_creer_label(svc_gmail, LABEL_NOM)
        for msg_id in tous_ids:
            svc_gmail.users().messages().modify(
                userId="me", id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        sys.exit(0)

    print(f"  Gencods détectés : {', '.join(sorted(tous_gencods))}")

    # 3. Charger gencod_adresses.csv et chemin_prepa_mono.csv
    print(f"\nChargement {NOM_GENCOD} …")
    gencod_adresses = charger_gencod_adresses()
    if not gencod_adresses:
        print(f"  {NOM_GENCOD} vide ou inaccessible — abandon.")
        sys.exit(0)
    print(f"  {len(gencod_adresses)} entrées chargées.")

    print(f"\nChargement {NOM_CHEMIN} …")
    adresses_chemin, adresses_set = charger_chemin_prepa()
    if adresses_chemin is None:
        print(f"  {NOM_CHEMIN} inaccessible — abandon.")
        sys.exit(0)
    print(f"  {len(adresses_chemin)} adresses existantes.")

    # 4. Identifier les adresses à ajouter
    a_ajouter = []
    gencods_inconnus = []
    for g in sorted(tous_gencods):
        if g not in gencod_adresses:
            print(f"  AVERTISSEMENT : gencod {g} absent de {NOM_GENCOD}")
            gencods_inconnus.append(g)
            continue
        adresse = gencod_adresses[g]
        if adresse not in adresses_set:
            print(f"  Adresse manquante → à ajouter : {adresse!r} (gencod {g})")
            a_ajouter.append(adresse)
            adresses_set.add(adresse)  # éviter les doublons si plusieurs emails
        else:
            print(f"  Adresse déjà présente : {adresse!r} (gencod {g})")

    # 5. Mettre à jour chemin_prepa_mono.csv si nécessaire
    if a_ajouter:
        nouveau_contenu = "\n".join(adresses_chemin + a_ajouter) + "\n"
        print(f"\nAjout de {len(a_ajouter)} adresse(s) dans {NOM_CHEMIN} …")

        # Invalider le cache pour forcer la relecture lors du prochain appel
        cs._config_drive_cache.pop(NOM_CHEMIN, None)

        ok = _upload_config_drive(NOM_CHEMIN, nouveau_contenu)
        if not ok:
            print("  Échec de l'upload — abandon sans marquage des emails.")
            sys.exit(1)
    else:
        print(f"\nAucune nouvelle adresse à ajouter.")

    # 6. Marquer les emails comme traités
    label_id = _get_ou_creer_label(svc_gmail, LABEL_NOM)
    for msg_id in tous_ids:
        svc_gmail.users().messages().modify(
            userId="me", id=msg_id,
            body={"addLabelIds": [label_id]},
        ).execute()
    print(f"  {len(tous_ids)} email(s) marqué(s) '{LABEL_NOM}'.")

    # 7. Envoyer email de confirmation si des adresses ont été ajoutées
    if a_ajouter:
        try:
            cs._charger_config()
        except SystemExit:
            pass
        envoyer_email_confirmation(a_ajouter, gencods_inconnus)

    if a_ajouter:
        print(f"\n✓ {len(a_ajouter)} adresse(s) ajoutée(s) à {NOM_CHEMIN}.")
    else:
        print("\n✓ Aucune modification nécessaire.")


if __name__ == "__main__":
    main()
