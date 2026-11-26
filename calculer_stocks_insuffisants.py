#!/usr/bin/env python3
"""
Stocks insuffisants prévisionnels : stock J1 (export du dossier Drive du
contrôle de stocks, j1.xlsx par défaut) moins les ventes d'un ou plusieurs
jours (BDC du Drive, mêmes règles que generer_ventes : commandes annulées
écartées, gencods R1 uniquement).

Un produit est en stock insuffisant si le stock restant est <=
SEUIL_STOCK_BAS, comme dans le contrôle de stocks : les produits du
classeur « PRODUIT A ENLEVER » sont exclus, ceux du classeur « DÉLOTAGE »
aussi (traités par le délotage). Le PDF (même format que le PDF « Stocks
insuffisant Drive » du contrôle, trié selon le chemin de préparation) est
envoyé par mail aux deux adresses du contrôle de stocks (email_destinataire
et email_destinataire_2 de config.json).

Les ventes d'un jour déjà archivées (Archives/ventes/ventes_JJ_MM.csv) sont
réutilisées si aucun BDC n'est arrivé et aucune annulation n'a été inscrite
depuis ; sinon elles sont recalculées depuis les BDC.

Sans --dates (mode par défaut) : toutes les commandes du jour et toutes les
commandes futures déjà passées, soit les ventes d'aujourd'hui à J+7 (heure
de Paris ; le client ne peut pas commander au-delà de 7 jours), déduites du
stock du jour.

--seuil N : seuil de détection (stock restant <= N), 2 par défaut
(SEUIL_STOCK_BAS).

Le fichier J1 observé est aussi déposé dans MobUDrive_Bons sous le nom
stock.xlsx (l'ancien est mis à la corbeille), après l'envoi du mail.

Usage :
  python3 calculer_stocks_insuffisants.py [--dates "16/11/2026 17/11/2026"] [--j1 j1.xlsx] [--seuil 2]
"""
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import controle_stocks as cs


def parser_dates(texte):
    """« 16/11/2026 17/11/2026 » (séparateurs espace, virgule ou point-virgule)
    → liste de dates triées, sans doublon. ValueError si vide ou invalide."""
    morceaux = [m for m in re.split(r'[\s,;]+', texte or '') if m]
    if not morceaux:
        raise ValueError("aucune date de ventes")
    jours = set()
    for m in morceaux:
        try:
            jours.add(datetime.strptime(m, "%d/%m/%Y").date())
        except ValueError:
            raise ValueError(f"date invalide : {m} (attendu JJ/MM/AAAA)")
    return sorted(jours)


# Le client ne peut pas commander plus de 7 jours à l'avance.
HORIZON_COMMANDES_JOURS = 7


def jours_par_defaut(aujourd_hui=None):
    """Mode par défaut : aujourd'hui et chaque jour jusqu'à J+7 inclus (heure
    de Paris) : toutes les commandes du jour et toutes les commandes futures."""
    j = aujourd_hui or datetime.now(ZoneInfo("Europe/Paris")).date()
    return [j + timedelta(days=i) for i in range(HORIZON_COMMANDES_JOURS + 1)]


def texte_jours(jours):
    """« 26/11/2026 » ou « 26/11/2026 & 27/11/2026 » ; à partir de 3 jours
    consécutifs : « 26/11/2026 au 03/12/2026 »."""
    consecutifs = all((b - a).days == 1 for a, b in zip(jours, jours[1:]))
    if len(jours) >= 3 and consecutifs:
        return f"{jours[0].strftime('%d/%m/%Y')} au {jours[-1].strftime('%d/%m/%Y')}"
    return " & ".join(d.strftime('%d/%m/%Y') for d in jours)


def _ids(svc, q, champs="id"):
    """Fichiers Drive (pagination) répondant à la requête q."""
    fichiers, jeton = [], None
    while True:
        res = svc.files().list(q=q, fields=f"nextPageToken, files({champs})",
                               pageSize=1000, pageToken=jeton).execute()
        fichiers.extend(res.get("files", []))
        jeton = res.get("nextPageToken")
        if not jeton:
            return fichiers


def archive_a_jour(heure_archive, heures_bdc, heure_registre):
    """L'archive des ventes est réutilisable si aucun BDC n'a été créé ou
    modifié après elle et si le registre des annulations n'a pas changé depuis
    (heures RFC 3339 de Drive, comparables comme chaînes)."""
    if not heure_archive:
        return False
    if any(h > heure_archive for h in heures_bdc):
        return False
    return not (heure_registre and heure_registre > heure_archive)


def ventes_archivees(d):
    """({gencod: qty}, {gencod: libellé}) depuis Archives/ventes/ventes_JJ_MM.csv
    (Drive config) si l'archive est à jour (voir archive_a_jour), sinon None :
    les ventes sont alors recalculées depuis les BDC."""
    try:
        svc = cs._get_drive_service()
        if not svc or not cs.DRIVE_CONFIG_FOLDER_ID or not cs.DRIVE_BDC_FOLDER_ID:
            return None
        nom_csv = f"ventes_{d.strftime('%d_%m')}.csv"
        archives = cs._trouver_dossier_drive(svc, cs.DRIVE_CONFIG_FOLDER_ID, "Archives")
        dossier_ventes = archives and cs._trouver_dossier_drive(svc, archives, "ventes")
        if not dossier_ventes:
            return None
        csv = _ids(svc, f"name='{nom_csv}' and '{dossier_ventes}' in parents and trashed=false",
                   "id,modifiedTime")
        if not csv:
            return None
        mois = cs._trouver_dossier_drive(svc, cs.DRIVE_BDC_FOLDER_ID, d.strftime("%m_%Y"))
        jour = mois and cs._trouver_dossier_drive(svc, mois, d.strftime("%d_%m"))
        heures_bdc = []
        if jour:
            for f in _ids(svc, f"'{jour}' in parents and name contains 'BonDeCommande' "
                               f"and trashed=false", "createdTime,modifiedTime"):
                heures_bdc += [f.get("createdTime", ""), f.get("modifiedTime", "")]
        import auto_prepa as ap
        heure_registre = None
        dossier_annul = ap._dossier_annulations(svc, creer=False)
        if dossier_annul:
            reg = _ids(svc, f"name='{ap._FICHIER_ANNULATIONS}' and '{dossier_annul}' "
                            f"in parents and trashed=false", "modifiedTime")
            heure_registre = reg[0].get("modifiedTime") if reg else None
        if not archive_a_jour(csv[0].get("modifiedTime"), heures_bdc, heure_registre):
            print(f"  {nom_csv} archivé mais pas à jour (nouveau BDC ou annulation) — recalcul.")
            return None
        chemin = os.path.join(cs.WORK_DIR, nom_csv)
        if not cs.telecharger_fichier_archive("ventes", nom_csv, chemin,
                                              root_id=cs.DRIVE_CONFIG_FOLDER_ID):
            return None
        print(f"  Aucun nouveau BDC depuis {nom_csv} : ventes archivées réutilisées.")
        return cs._charger_ventes_csv(chemin)
    except Exception as e:
        print(f"  Archive des ventes illisible ({type(e).__name__}) — recalcul.")
        return None


def calculer_stock_insuffisant(stock_j1, classeurs, ventes_jours, gencods_r1, libelles):
    """Lignes (format _construire_pdf_tableau : gencod, s_j1, ventes, 0,
    restant, 0, '', libellé) des gencods R1 présents au J1 dont le stock
    restant après les ventes est <= SEUIL_STOCK_BAS."""
    enlever  = cs._normaliser_classeur(cs.CLASSEUR_A_ENLEVER)
    delotage = cs._normaliser_classeur(cs.CLASSEUR_DELOTAGE)
    rows = []
    for g in sorted(stock_j1):
        if gencods_r1 is not None and g not in gencods_r1:
            continue
        classeur = cs._normaliser_classeur(classeurs.get(g, ''))
        if classeur in (enlever, delotage):
            continue
        vendu = sum(v.get(g, 0) for v in ventes_jours)
        restant = stock_j1[g] - vendu
        if restant <= cs.SEUIL_STOCK_BAS:
            rows.append((g, stock_j1[g], vendu, 0, restant, 0, '', libelles.get(g, '')))
    return rows


def envoyer_par_mail(chemin, dates_txt, nom_j1, nb):
    """Envoie le PDF par mail aux deux adresses du contrôle de stocks."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    svc = cs._get_gmail_service()
    if not svc or not cs.EMAIL_DESTINATAIRE:
        return False
    msg = MIMEMultipart()
    msg['To'] = cs.EMAIL_DESTINATAIRE
    if cs.EMAIL_COPIE_STOCK:
        msg['Cc'] = cs.EMAIL_COPIE_STOCK
    pluriel = 's' if nb > 1 else ''
    msg['Subject'] = f"Stocks insuffisant Drive - ventes du {dates_txt} — {nb} produit{pluriel}"
    corps = (f"Stocks insuffisant Drive - {nom_j1} - ventes du {dates_txt}\n\n"
             f"  {nb} produit{pluriel} (stock restant ≤ {cs.SEUIL_STOCK_BAS})\n\n"
             f"Détail en pièce jointe.")
    msg.attach(MIMEText(corps, 'plain', 'utf-8'))
    with open(chemin, 'rb') as f:
        part = MIMEApplication(f.read(), 'pdf')
    part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(chemin))
    msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId='me', body={'raw': raw}).execute()
    print("  Email envoyé.")
    return True


def publier_mobudrive(chemin_j1):
    """Dépose le fichier J1 observé dans MobUDrive_Bons sous le nom stock.xlsx
    (l'ancien stock.xlsx est mis à la corbeille)."""
    try:
        import stock_mobudrive
        stock_mobudrive.publier(chemin_j1)
    except Exception as e:
        print(f"  Stock MobUDrive non déposé : {type(e).__name__}")


def _option(args, nom, defaut=None):
    if nom in args:
        i = args.index(nom)
        if i + 1 < len(args):
            return args[i + 1]
    return defaut


def main():
    args = sys.argv[1:]
    texte_dates = (_option(args, "--dates", "") or "").strip()
    try:
        jours = parser_dates(texte_dates) if texte_dates else jours_par_defaut()
    except ValueError as e:
        print(f"ERREUR : {e}")
        sys.exit(1)
    nom_j1 = (_option(args, "--j1") or "j1.xlsx").strip()
    texte_seuil = (_option(args, "--seuil", "") or "").strip()
    if texte_seuil:
        try:
            cs.SEUIL_STOCK_BAS = int(texte_seuil)
        except ValueError:
            print(f"ERREUR : seuil invalide : {texte_seuil} (nombre entier attendu)")
            sys.exit(1)

    cs._charger_config()
    os.makedirs(cs.WORK_DIR, exist_ok=True)

    print(f"Téléchargement {nom_j1} (dossier contrôle) …")
    f_j1 = cs.telecharger_fichier_controle(nom_j1, dest=os.path.join(cs.WORK_DIR, "j1_stock.xlsx"))
    if not f_j1:
        print(f"ERREUR : {nom_j1} introuvable dans le dossier du contrôle de stocks.")
        sys.exit(1)
    stock_j1, libelles, classeurs = cs.lire_stock(f_j1, classeur_requis=False)
    print(f"  → {len(stock_j1)} gencods")

    ventes_jours = []
    for d in jours:
        print(f"\nVentes du {d.strftime('%d/%m/%Y')} …")
        v, l = ventes_archivees(d) or cs.generer_ventes(d)
        ventes_jours.append(v)
        for g, lib in l.items():
            libelles.setdefault(g, lib)
    libelles.update(cs.charger_libelles_dict())

    rows = calculer_stock_insuffisant(stock_j1, classeurs, ventes_jours,
                                      cs.charger_gencods_r1(), libelles)
    print(f"\n{len(rows)} produit(s) en stock insuffisant (restant <= {cs.SEUIL_STOCK_BAS}).")
    if not rows:
        print("Aucun stock insuffisant : pas de PDF.")
        publier_mobudrive(f_j1)
        return

    rows.sort(key=cs.cle_tri_chemin_prepa(cs.charger_adresses_magasin(),
                                          cs.charger_gencod_nomenclatures(),
                                          cs.charger_ordre_chemin_prepa()))
    vms_map = cs.calculer_vms([r[0] for r in rows], date.today())

    dates_txt = texte_jours(jours)
    suffixe = (f"{jours[0].strftime('%Y%m%d')}_au_{jours[-1].strftime('%Y%m%d')}"
               if " au " in dates_txt else "_".join(d.strftime('%Y%m%d') for d in jours))
    nom_pdf = os.path.join(cs.WORK_DIR, f"stock_insuffisant_{suffixe}.pdf")
    titre = (f"<b>Stocks insuffisant Drive - {nom_j1} - ventes du {dates_txt}</b>"
             f"&nbsp;&nbsp;({len(rows)} produit{'s' if len(rows) > 1 else ''})")
    # Colonnes : stock du matin (J1), ventes prévisionnelles, stock restant
    prevision_map = {r[0]: (r[2], r[4]) for r in rows}
    rows_pdf = [(g, s, v, 0, s, 0, '', lib) for g, s, v, _, _, _, _, lib in rows]
    pdf = cs._construire_pdf_tableau(rows_pdf, titre, nom_pdf, complet=False, vms_map=vms_map,
                                     prevision_map=prevision_map)
    envoye = bool(pdf) and envoyer_par_mail(pdf, dates_txt, nom_j1, len(rows))
    publier_mobudrive(f_j1)  # après le mail : ne le retarde jamais
    if not envoye:
        print("ERREUR : PDF non généré ou non envoyé par mail.")
        sys.exit(1)


if __name__ == "__main__":
    main()
