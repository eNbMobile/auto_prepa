#!/usr/bin/env python3
"""
Récupération de la distance magasin -> client (colonne "km" de LIVRAISON
DRIVE 2026) auprès du back office pro Shopopop (app.shopopop.com).

Reproduit en HTTP pur (urllib, pas de navigateur) le flux OAuth2
Authorization Code + PKCE que fait le navigateur contre Keycloak
(auth-sso.shopopop.com), puis interroge l'API back-office
(api-backoffice.shopopop.com) qui alimente l'onglet "Livraisons > Programmées"
du site. Identifiants attendus dans config.json (clés "ID_Shopopop" et
"MDP_Shopopop"), chargés par livraison_drive.py.
"""
import base64
import hashlib
import html
import http.cookiejar
import json
import re
import secrets
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time
from zoneinfo import ZoneInfo

_AUTH_BASE = "https://auth-sso.shopopop.com/realms/shopopop"
_API_BASE = "https://api-backoffice.shopopop.com/api/v1"
_CLIENT_ID = "backoffice-externe"
_REDIRECT_URI = "https://app.shopopop.com/"
_TZ = ZoneInfo("Europe/Paris")

# ID du "drive" (magasin) Shopopop (visible dans l'URL app.shopopop.com/deliveries?drive_id=...).
# Utilisé si absent de config.json (clé "shopopop_drive_id") — à mettre à jour si le magasin change.
SHOPOPOP_DRIVE_ID_DEFAUT = "14156"


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Empêche urllib de suivre automatiquement la redirection 302 finale du
    login Keycloak — on a besoin de lire son paramètre `code` nous-mêmes."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _normaliser(texte):
    """Majuscules sans accents, pour comparer les noms insensiblement à la casse/accents."""
    d = unicodedata.normalize('NFD', (texte or '').strip().upper())
    return ''.join(c for c in d if unicodedata.category(c) != 'Mn')


def _tokens(nom_complet):
    return frozenset(_normaliser(nom_complet).split())


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def login(email, mot_de_passe):
    """Réalise le flux OAuth2 Authorization Code + PKCE auprès de Keycloak
    (identique à celui du navigateur) et retourne un access_token, ou None
    si les identifiants sont absents/refusés ou en cas d'erreur réseau."""
    if not email or not mot_de_passe:
        return None

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _SansRedirection())

    verifier, challenge = _pkce_pair()
    auth_url = _AUTH_BASE + "/protocol/openid-connect/auth?" + urllib.parse.urlencode({
        "client_id": _CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "state": secrets.token_hex(16),
        "response_type": "code",
        "scope": "openid profile email",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    try:
        with opener.open(auth_url, timeout=20) as resp:
            page = resp.read().decode("utf-8", errors="replace")

        m = re.search(r'<form[^>]+id="kc-login-form"[^>]+action="([^"]+)"', page)
        if not m:
            print("    Shopopop : formulaire de connexion introuvable (page de login modifiée ?).")
            return None
        form_action = html.unescape(m.group(1))

        payload = urllib.parse.urlencode({"username": email, "password": mot_de_passe}).encode()
        req = urllib.request.Request(
            form_action, data=payload, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            opener.open(req, timeout=20)
            print("    Shopopop : pas de redirection après connexion, identifiants probablement refusés.")
            return None
        except urllib.error.HTTPError as e:
            if e.code not in (302, 303):
                raise
            location = e.headers.get("Location", "")

        code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("code", [None])[0]
        if not code:
            print("    Shopopop : connexion refusée (pas de code d'autorisation retourné).")
            return None

        token_payload = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "client_id": _CLIENT_ID,
            "redirect_uri": _REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }).encode()
        token_req = urllib.request.Request(
            _AUTH_BASE + "/protocol/openid-connect/token", data=token_payload, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with opener.open(token_req, timeout=20) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
        return tokens.get("access_token")
    except Exception as e:
        print(f"    Connexion Shopopop échouée : {e}")
        return None


def distance_km(access_token, drive_id, date_livraison, nom_complet):
    """Cherche, parmi les livraisons "Programmées" du magasin `drive_id`
    prévues pour `date_livraison` (objet date), celle dont le destinataire
    correspond à `nom_complet` (comparaison par ensemble de mots normalisés,
    insensible à l'ordre nom/prénom, aux accents et à la casse), et retourne
    sa distance en km (arrondie à 1 décimale), ou None si non trouvée."""
    if not access_token:
        return None
    cible = _tokens(nom_complet)
    if not cible:
        return None

    debut_paris = datetime.combine(date_livraison, time.min, tzinfo=_TZ)
    fin_paris = datetime.combine(date_livraison, time.max, tzinfo=_TZ)
    debut_utc = debut_paris.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fin_utc = fin_paris.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.999Z")

    page = 1
    try:
        while True:
            url = _API_BASE + "/deliveries?" + urllib.parse.urlencode({
                "drive_id": drive_id, "order": "ASC", "page": page, "per_page": 50,
                "status": "schedule",
                "withdrawal_start_utc": debut_utc,
                "withdrawal_end_utc": fin_utc,
            })
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {access_token}", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            items = data.get("items", [])
            for it in items:
                dest = it.get("recipient") or {}
                nom_dest = f"{dest.get('first_name', '')} {dest.get('last_name', '')}"
                if _tokens(nom_dest) == cible:
                    metres = it.get("delivery_distance")
                    return round(metres / 1000, 1) if isinstance(metres, (int, float)) else None

            if len(items) < 50:
                return None
            page += 1
    except Exception as e:
        print(f"    Recherche distance Shopopop échouée ({nom_complet}) : {e}")
        return None
