#!/usr/bin/env python3
"""Alerte de consommation R2 (Cloudflare) : mail quand une des 3 limites
gratuites mensuelles atteint 80 % (stockage 10 Go, 1 M operations de classe A,
10 M operations de classe B).

Lit la consommation du mois en cours (UTC) via l'API GraphQL Analytics de
Cloudflare. Le mail n'est envoye que le jour ou le seuil est franchi (valeur
d'aujourd'hui >= 80 % alors que celle arretee a hier soir etait < 80 %), pour
ne pas recevoir le meme mail tous les jours.

Usage : python3 alerte_r2.py [--tester]  (--tester : envoie le recapitulatif
meme sous le seuil, pour verifier l'envoi du mail).

Secrets : CLOUDFLARE_API_TOKEN (permission « Account Analytics : Read »),
CLOUDFLARE_ACCOUNT_ID, GOOGLE_TOKEN_JSON, DRIVE_CONFIG_FOLDER_ID.
"""
import base64
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText

import controle_stocks as cs

SEUIL = 0.80
LIMITES = {
    "Stockage": 10 * 1000 ** 3,           # 10 Go (octets)
    "Opérations de classe A": 1_000_000,  # écritures / listes
    "Opérations de classe B": 10_000_000,  # lectures
}
CLASSE_A = {
    "ListBuckets", "PutBucket", "ListObjects", "PutObject", "CopyObject",
    "CompleteMultipartUpload", "CreateMultipartUpload",
    "LifecycleStorageTierTransition", "ListMultipartUploads", "UploadPart",
    "UploadPartCopy", "ListParts", "PutBucketEncryption", "PutBucketCors",
    "PutBucketLifecycleConfiguration",
}
CLASSE_B = {
    "HeadBucket", "HeadObject", "GetObject", "UsageSummary",
    "GetBucketEncryption", "GetBucketLocation", "GetBucketCors",
    "GetBucketLifecycleConfiguration",
}

REQUETE = """
query($compte: String!, $debut: Time!, $fin: Time!) {
  viewer {
    accounts(filter: {accountTag: $compte}) {
      r2OperationsAdaptiveGroups(limit: 10000,
          filter: {datetime_geq: $debut, datetime_leq: $fin}) {
        sum { requests }
        dimensions { actionType }
      }
      r2StorageAdaptiveGroups(limit: 10000,
          filter: {datetime_geq: $debut, datetime_leq: $fin}) {
        max { payloadSize metadataSize }
        dimensions { bucketName }
      }
    }
  }
}
"""


def _consommation(compte, jeton, debut, fin):
    """Consommation R2 de debut a fin : {nom de limite: valeur}."""
    corps = json.dumps({"query": REQUETE, "variables": {
        "compte": compte,
        "debut": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fin": fin.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }}).encode()
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/graphql", data=corps,
        headers={"Authorization": f"Bearer {jeton}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rep = json.load(resp)
    if rep.get("errors"):
        raise RuntimeError("; ".join(e.get("message", "?") for e in rep["errors"]))
    comptes = rep["data"]["viewer"]["accounts"]
    if not comptes:
        raise RuntimeError("compte Cloudflare introuvable")
    c = comptes[0]
    classe_a = classe_b = 0
    for g in c["r2OperationsAdaptiveGroups"]:
        action, n = g["dimensions"]["actionType"], g["sum"]["requests"]
        if action in CLASSE_A:
            classe_a += n
        elif action in CLASSE_B:
            classe_b += n
    stockage = sum(g["max"]["payloadSize"] + g["max"]["metadataSize"]
                   for g in c["r2StorageAdaptiveGroups"])
    return {"Stockage": stockage,
            "Opérations de classe A": classe_a,
            "Opérations de classe B": classe_b}


def _format(nom, valeur):
    if nom == "Stockage":
        return f"{valeur / 1000 ** 3:.2f} Go"
    return f"{valeur:,}".replace(",", " ")


def _envoyer(sujet, texte):
    cs._charger_config()
    svc = cs._get_gmail_service()
    if not svc or not cs.EMAIL_DESTINATAIRE:
        print("  Gmail indisponible : mail non envoyé.")
        return False
    msg = MIMEText(texte, "plain", "utf-8")
    msg["To"] = cs.EMAIL_DESTINATAIRE
    msg["Subject"] = sujet
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print("  Mail envoyé.")
    return True


def main():
    tester = "--tester" in sys.argv[1:]
    jeton = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    compte = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not jeton or not compte:
        print("ERREUR : CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID manquants.")
        sys.exit(1)

    maintenant = datetime.now(timezone.utc)
    debut_mois = maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)

    actuel = _consommation(compte, jeton, debut_mois, maintenant)
    hier = (_consommation(compte, jeton, debut_mois, debut_jour)
            if debut_jour > debut_mois else {k: 0 for k in LIMITES})

    lignes, franchis = [], []
    for nom, limite in LIMITES.items():
        pct = actuel[nom] / limite
        lignes.append(f"  {nom} : {_format(nom, actuel[nom])} / "
                      f"{_format(nom, limite)} ({pct:.0%})")
        if pct >= SEUIL and hier[nom] / limite < SEUIL:
            franchis.append(nom)
    recap = "\n".join(lignes)
    print(f"Consommation R2 du mois ({debut_mois:%m/%Y}) :\n{recap}")

    if franchis:
        sujet = f"Alerte R2 Cloudflare : {', '.join(franchis)} à 80 % de la limite gratuite"
    elif tester:
        sujet = "Test alerte R2 Cloudflare : consommation du mois"
    else:
        print("Aucun seuil de 80 % franchi aujourd'hui : pas de mail.")
        return
    texte = (f"Consommation R2 du mois en cours ({debut_mois:%m/%Y}) :\n\n{recap}\n\n"
             f"Au-delà des limites gratuites, Cloudflare facture la consommation "
             f"supplémentaire.\nDétail : tableau de bord Cloudflare > R2 object storage.")
    _envoyer(sujet, texte)


if __name__ == "__main__":
    main()
