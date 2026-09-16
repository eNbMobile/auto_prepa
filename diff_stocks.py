#!/usr/bin/env python3
"""
Différence de stocks entre les deux exports Drive j1.xlsx (J-1) et j.xlsx (J).

Reprend le circuit du contrôle de stocks (même périmètre de gencods R1, même
mise en page PDF avec code-barres) mais sans les ventes ni le stock théorique :
le PDF liste le stock J-1, le stock J et la différence entre les deux, et ne
contient que les lignes qui diffèrent.

Les deux exports sont cherchés d'abord dans le dépôt lui-même (racine, stocks/
ou WORK_DIR). À défaut, ils sont téléchargés depuis Drive : d'abord le dossier
de dépôt ("GITHUB" par défaut, ou DRIVE_STOCKS_FOLDER_ID), puis le dossier du
contrôle de stocks, puis n'importe où sur le Drive (fichier le plus récent), et
enfin — pour j1.xlsx seulement — les archives des stocks du soir.

Usage :
  python3 diff_stocks.py [j1.xlsx [j.xlsx]] [--date JJ/MM/AAAA] [--tous]

  --date  date du stock J-1 (défaut : hier, ou samedi si on est lundi). Sert au
          titre/nom du PDF et au repli sur les archives Drive.
  --tous  compare tous les gencods des deux fichiers, sans le filtre R1.
"""

import os
import sys
from datetime import date, timedelta

import controle_stocks as cs


# Emplacements fouillés dans le dépôt, dans l'ordre : racine du checkout,
# sous-dossier stocks/, puis le répertoire de travail habituel ("v 4.0.0").
DOSSIERS_LOCAUX = ("", "stocks", cs.WORK_DIR)


def chercher_local(nom, chemin_demande=None):
    """Cherche un export dans le dépôt. Retourne le chemin trouvé ou None."""
    candidats = [chemin_demande] if chemin_demande else []
    candidats += [os.path.join(d, nom) for d in DOSSIERS_LOCAUX]
    for chemin in candidats:
        if chemin and os.path.exists(chemin):
            return chemin
    return None


def _emplacements_attendus(nom):
    return ", ".join(os.path.join(d, nom) or nom for d in DOSSIERS_LOCAUX)


# Dossier Drive où les exports sont déposés à la main pour ce traitement. Le
# dossier du contrôle de stocks (config.json) ne reçoit que ses propres
# exports : les fichiers déposés pour la comparaison le sont dans un dossier
# dédié, "GITHUB" sauf indication contraire.
DRIVE_STOCKS_FOLDER_ID   = os.environ.get("DRIVE_STOCKS_FOLDER_ID", "").strip()
DRIVE_STOCKS_FOLDER_NAME = os.environ.get("DRIVE_STOCKS_FOLDER_NAME", "GITHUB").strip()


def _drive_id_dossier(svc, nom):
    """ID du dossier Drive portant ce nom, ou None."""
    res = svc.files().list(
        q=(f"name='{nom}' and mimeType='application/vnd.google-apps.folder' "
           f"and trashed=false"),
        fields="files(id)", pageSize=10).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _drive_fichier_recent(svc, nom, parent_id=None):
    """(file_id, nom du dossier parent) du fichier le plus récemment modifié
    portant ce nom, dans parent_id si fourni, sinon sur tout le Drive."""
    q = f"name='{nom}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = svc.files().list(q=q, fields="files(id,parents)",
                           orderBy="modifiedTime desc", pageSize=10).execute()
    files = res.get("files", [])
    if not files:
        return None, None
    parents = files[0].get("parents") or []
    dossier = ""
    if parents:
        try:
            dossier = svc.files().get(fileId=parents[0], fields="name").execute().get("name", "")
        except Exception:
            pass
    return files[0]["id"], dossier


def telecharger_depuis_drive(nom, dest):
    """Télécharge un export depuis Drive dans dest. Retourne dest ou None.

    Ordre de recherche : dossier de dépôt (DRIVE_STOCKS_FOLDER_ID, sinon le
    dossier nommé DRIVE_STOCKS_FOLDER_NAME), dossier du contrôle de stocks,
    puis tout le Drive — le fichier le plus récemment modifié l'emporte. Le
    dossier d'où vient le fichier est affiché.
    """
    try:
        import io as _io
        from googleapiclient.http import MediaIoBaseDownload
        svc = cs._get_drive_service()
        if not svc:
            return None

        parents = []
        if DRIVE_STOCKS_FOLDER_ID:
            parents.append(DRIVE_STOCKS_FOLDER_ID)
        elif DRIVE_STOCKS_FOLDER_NAME:
            depot = _drive_id_dossier(svc, DRIVE_STOCKS_FOLDER_NAME)
            if depot:
                parents.append(depot)
        if cs.DRIVE_CONTROLE_FOLDER_ID:
            parents.append(cs.DRIVE_CONTROLE_FOLDER_ID)

        file_id, dossier = None, None
        for parent_id in parents:
            file_id, dossier = _drive_fichier_recent(svc, nom, parent_id)
            if file_id:
                break
        if not file_id:
            # Dernier recours : n'importe où sur le Drive, le plus récent.
            file_id, dossier = _drive_fichier_recent(svc, nom)
        if not file_id:
            return None

        buf = _io.BytesIO()
        dl  = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        with open(dest, "wb") as f:
            f.write(buf.getvalue())
        print(f"  → {nom} téléchargé depuis le dossier Drive "
              f"{dossier or '(inconnu)'} ({os.path.getsize(dest):,} octets)")
        return dest
    except Exception as e:
        print(f"  Téléchargement de {nom} depuis Drive échoué : {e}")
        return None


def resoudre_fichiers(fichier_j1, fichier_j, date_j1):
    """Localise les deux exports et retourne (chemin_j1, chemin_j).

    Priorité au dépôt lui-même (chemin passé en argument, racine, stocks/,
    WORK_DIR), puis repli sur le dossier Drive du contrôle de stocks et enfin
    sur les archives. Quitte en erreur si l'un des deux reste introuvable.
    """
    chemin_j = chercher_local("j.xlsx", fichier_j)
    if chemin_j:
        print(f"Stock J   trouvé dans le dépôt : {chemin_j}")
    else:
        print("j.xlsx absent du dépôt — recherche sur Drive …")
        if telecharger_depuis_drive("j.xlsx", "j.xlsx"):
            chemin_j = "j.xlsx"
        else:
            print("ERREUR : j.xlsx introuvable — stock J indisponible.\n"
                  f"  Déposez-le dans le dépôt ({_emplacements_attendus('j.xlsx')}) "
                  f"ou dans le dossier Drive {DRIVE_STOCKS_FOLDER_NAME}.")
            sys.exit(1)

    chemin_j1 = chercher_local("j1.xlsx", fichier_j1)
    if chemin_j1:
        print(f"Stock J-1 trouvé dans le dépôt : {chemin_j1}")
        return chemin_j1, chemin_j

    print("j1.xlsx absent du dépôt — recherche sur Drive …")
    if telecharger_depuis_drive("j1.xlsx", "j1.xlsx"):
        return "j1.xlsx", chemin_j
    # Repli : stocks du soir de J-1 archivés ("_j" pour les archives antérieures
    # au découpage matin/soir), comme dans download_stocks.py.
    jour = date_j1.strftime('%d_%m_%Y')
    for nom in (cs.nom_archive_stock(date_j1, "soir"), f"stock_{jour}_j.xlsx"):
        if cs.telecharger_fichier_archive("stocks", nom, "j1.xlsx",
                                          root_id=cs.DRIVE_CONFIG_FOLDER_ID):
            return "j1.xlsx", chemin_j
    print("ERREUR : j1.xlsx introuvable (dépôt, Drive et archives) — "
          "stock de départ indisponible.\n"
          f"  Déposez-le dans le dépôt ({_emplacements_attendus('j1.xlsx')}) "
          f"ou dans le dossier Drive {DRIVE_STOCKS_FOLDER_NAME}.")
    sys.exit(1)


def comparer_stocks(stock_j1, stock_j, gencods=None, libelles=None):
    """Compare le stock UC des deux exports, sans ventes ni théorique.

    gencods : périmètre à comparer (None → tous les gencods des deux fichiers).
    Retourne (differences, orphelins, nb_communs) où chaque ligne suit le tuple
    de controle_stocks — (gencod, s_j1, ventes, théo, s_j, écart, statut,
    libellé) — avec ventes et théorique laissés à 0 et écart = stock J - stock
    J-1. Les gencods absents d'un des deux exports sont écartés (orphelins) :
    sans stock de référence, la différence ne veut rien dire.
    """
    libelles = libelles or {}
    tous = gencods if gencods is not None else (set(stock_j1) | set(stock_j))

    differences, orphelins, nb_communs = [], [], 0
    for gencod in sorted(tous):
        present_j1 = gencod in stock_j1
        present_j  = gencod in stock_j
        s_j1 = stock_j1.get(gencod, 0.0)
        s_j  = stock_j.get(gencod, 0.0)
        lib  = libelles.get(gencod, '')

        absents = []
        if not present_j1: absents.append("J-1")
        if not present_j:  absents.append("J")
        if absents:
            orphelins.append((gencod, s_j1, 0.0, 0.0, s_j, 0.0,
                              f"ABSENT_{'+'.join(absents)}", lib))
            continue

        nb_communs += 1
        ecart = s_j - s_j1
        if abs(ecart) < 0.001:
            continue
        differences.append((gencod, s_j1, 0.0, 0.0, s_j, ecart, "DIFF", lib))

    differences.sort(key=lambda r: abs(r[5]), reverse=True)
    orphelins.sort(key=lambda r: r[0])
    return differences, orphelins, nb_communs


def generer_pdf_diff(differences, date_j1, date_j):
    """Génère le PDF des seules lignes qui diffèrent. Retourne le chemin ou None."""
    if not differences:
        return None
    nom_pdf = f"diff_stocks_{date_j.strftime('%Y%m%d')}.pdf"
    nb = len(differences)
    titre_html = (f"<b>Différence de stocks — {date_j1.strftime('%d/%m/%Y')} → "
                  f"{date_j.strftime('%d/%m/%Y')}</b>"
                  f"&nbsp;&nbsp;({nb} différence{'s' if nb > 1 else ''})")
    return cs._construire_pdf_tableau(differences, titre_html, nom_pdf, diff=True)


def envoyer_email_diff(pdf, date_j1, date_j, nb, baisse, hausse):
    """Envoie le PDF des différences de stocks (Gmail API)."""
    try:
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication

        svc = cs._get_gmail_service()
        if not svc:
            return

        label = f"{date_j1.strftime('%d/%m/%Y')} → {date_j.strftime('%d/%m/%Y')}"
        msg = MIMEMultipart()
        msg['To']      = cs.EMAIL_DESTINATAIRE
        msg['Cc']      = cs.EMAIL_COPIE_STOCK
        msg['Subject'] = (f"Différence de stocks {label} — "
                          f"{nb} différence{'s' if nb > 1 else ''}")

        corps = (f"Différence de stocks {label}\n\n"
                 f"  Différences : {nb}\n"
                 f"  En baisse   : {baisse:.0f} unités\n"
                 f"  En hausse   : +{hausse:.0f} unités\n\n"
                 f"Détail en pièce jointe (uniquement les lignes qui diffèrent).")
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))

        with open(pdf, 'rb') as f:
            part = MIMEApplication(f.read(), 'pdf')
        part.add_header('Content-Disposition', 'attachment',
                        filename=os.path.basename(pdf))
        msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"  Email envoyé → {cs.EMAIL_DESTINATAIRE} (cc: {cs.EMAIL_COPIE_STOCK})")
    except Exception as e:
        print(f"  Email échoué : {e}")


def main():
    args = sys.argv[1:]

    tous = "--tous" in args
    args = [a for a in args if a != "--tous"]

    # Dernier jour de stock J-1 : hier, ou samedi le lundi (pas de ventes le
    # dimanche), comme dans download_stocks.py / controle_stocks.py.
    delta = timedelta(days=2) if date.today().weekday() == 0 else timedelta(days=1)
    date_j1 = date.today() - delta
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            try:
                j, m, a = args[i + 1].split("/")
                date_j1 = date(int(a), int(m), int(j))
            except Exception:
                print(f"Format de date invalide : {args[i + 1]} (attendu JJ/MM/AAAA)")
                sys.exit(1)
            args.pop(i + 1)
            args.pop(i)

    if len(args) > 2:
        print(__doc__)
        sys.exit(1)
    fichier_j1 = args[0] if len(args) >= 1 else None
    fichier_j  = args[1] if len(args) == 2 else None

    date_j = date.today()

    cs._charger_config()
    fichier_j1, fichier_j = resoudre_fichiers(fichier_j1, fichier_j, date_j1)

    print(f"\nLecture stock J-1 : {fichier_j1}")
    stock_j1, libelles_j1, _ = cs.lire_stock(fichier_j1, classeur_requis=False)
    print(f"  → {len(stock_j1)} gencods")

    print(f"Lecture stock J   : {fichier_j}")
    stock_j, libelles_j, _ = cs.lire_stock(fichier_j, classeur_requis=False)
    print(f"  → {len(stock_j)} gencods")

    # Priorité : dict coursesu > libellés xlsx (souvent tronqués)
    print("\nChargement libellés coursesu …")
    libelles = dict(libelles_j1)
    libelles.update(libelles_j)
    libelles.update({g: l for g, l in cs.charger_libelles_dict().items() if l})

    gencods = None
    if not tous:
        gencods = cs.charger_gencods_r1()
        if gencods is None:
            print("  Périmètre R1 indisponible — comparaison sur tous les gencods.")

    differences, orphelins, nb_communs = comparer_stocks(stock_j1, stock_j,
                                                         gencods, libelles)

    baisse = sum(r[5] for r in differences if r[5] < 0)
    hausse = sum(r[5] for r in differences if r[5] > 0)

    print(f"\n── Résultats ──────────────────────────────────────")
    print(f"  Gencods comparés  : {nb_communs}")
    print(f"    Identiques      : {nb_communs - len(differences)}")
    print(f"    Différents      : {len(differences)}")
    if orphelins:
        print(f"  Gencods orphelins : {len(orphelins)} (absents d'un des deux exports)")
    print(f"  Total en baisse   : {baisse:.0f} unités")
    print(f"  Total en hausse   : +{hausse:.0f} unités")

    if not differences:
        print("\nAucune différence de stock — pas de PDF ni d'email.")
        return

    print(f"\n  Top 10 différences (|diff| décroissant) :")
    for r in differences[:10]:
        print(f"    {r[0]}  J-1={r[1]:.0f}  J={r[4]:.0f}  diff={r[5]:+.0f}")

    print("\nGénération PDF différences …")
    pdf = generer_pdf_diff(differences, date_j1, date_j)
    if pdf:
        print("\nEnvoi email …")
        envoyer_email_diff(pdf, date_j1, date_j, len(differences), baisse, hausse)


if __name__ == "__main__":
    main()
