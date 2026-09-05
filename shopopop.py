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

# Shopopop est derriere Cloudflare, qui bloque par defaut les requetes sans
# en-tetes de navigateur (le User-Agent par defaut d'urllib, "Python-urllib/x.y",
# est un signal de bot classique) — d'ou les 403 observes sans ces en-tetes.
_HEADERS_NAVIGATEUR = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}

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
    """Ensemble des mots normalises de `nom_complet`, trait d'union traite
    comme un espace : un prenom compose ('JEAN-PIERRE') doit matcher sa
    version sans tiret ('JEAN PIERRE'), le client ne saisissant pas toujours
    le trait d'union de la meme facon d'un systeme a l'autre (PDF de
    commande vs Shopopop)."""
    return frozenset(_normaliser(nom_complet).replace('-', ' ').split())


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def _extraire_form_action(page):
    """Isole le <form> dont l'action pointe vers login-actions, l'URL
    Keycloak qui traite la soumission des identifiants (l'ordre des
    attributs id/action du <form> n'est pas garanti, et l'id exact
    ("kc-login-form") n'est pas fiable sur une page de login personnalisée)."""
    for tag in re.findall(r'<form\b[^>]*>', page, re.DOTALL):
        m = re.search(r'\baction="([^"]*login-actions[^"]*)"', tag)
        if m:
            return html.unescape(m.group(1))
    return None


def _champs_caches(page):
    """Récupère les <input type="hidden"> (jeton CSRF, execution, etc.) à
    reporter tels quels dans la soumission du formulaire suivant."""
    champs = {}
    for tag in re.findall(r'<input\b[^>]*>', page, re.DOTALL):
        if not re.search(r'\btype="hidden"', tag):
            continue
        m_nom = re.search(r'\bname="([^"]*)"', tag)
        if not m_nom:
            continue
        m_val = re.search(r'\bvalue="([^"]*)"', tag)
        champs[html.unescape(m_nom.group(1))] = html.unescape(m_val.group(1)) if m_val else ""
    return champs


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
        auth_req = urllib.request.Request(auth_url, headers=_HEADERS_NAVIGATEUR)
        with opener.open(auth_req, timeout=20) as resp:
            page = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    Connexion Shopopop échouée (page de connexion) : {e}")
        return None

    form_action = _extraire_form_action(page)
    if not form_action:
        print("    Shopopop : formulaire de connexion introuvable (page de login modifiée ?).")
        return None

    # Depuis fin août 2026, Keycloak demande d'abord l'email seul (étape
    # "identifier-first"), puis renvoie une seconde page — identique à
    # l'ancienne page de connexion — avec le champ mot de passe. On ne
    # soumet donc l'email à part que si cette première page n'a pas déjà de
    # champ mot de passe (pour rester compatible si Shopopop revient à
    # l'ancien formulaire unique).
    if not re.search(r'\bname="password"', page):
        try:
            payload = urllib.parse.urlencode({
                **_champs_caches(page), "username": email,
            }).encode()
            req = urllib.request.Request(
                form_action, data=payload, method="POST",
                headers={**_HEADERS_NAVIGATEUR, "Content-Type": "application/x-www-form-urlencoded"})
            with opener.open(req, timeout=20) as resp:
                page = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"    Connexion Shopopop échouée (envoi email) : {e}")
            return None

        form_action = _extraire_form_action(page)
        if not form_action or not re.search(r'\bname="password"', page):
            print("    Shopopop : page de mot de passe introuvable après saisie de l'email "
                  "(email refusé ou page de login modifiée).")
            return None

    try:
        payload = urllib.parse.urlencode({
            **_champs_caches(page), "username": email, "password": mot_de_passe,
        }).encode()
        req = urllib.request.Request(
            form_action, data=payload, method="POST",
            headers={**_HEADERS_NAVIGATEUR, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            opener.open(req, timeout=20)
            print("    Shopopop : pas de redirection après connexion, identifiants probablement refusés.")
            return None
        except urllib.error.HTTPError as e:
            if e.code not in (302, 303):
                raise
            location = e.headers.get("Location", "")
    except Exception as e:
        print(f"    Connexion Shopopop échouée (envoi identifiants) : {e}")
        return None

    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("code", [None])[0]
    if not code:
        print("    Shopopop : connexion refusée (pas de code d'autorisation retourné).")
        return None

    try:
        token_payload = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "client_id": _CLIENT_ID,
            "redirect_uri": _REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }).encode()
        token_req = urllib.request.Request(
            _AUTH_BASE + "/protocol/openid-connect/token", data=token_payload, method="POST",
            headers={**_HEADERS_NAVIGATEUR, "Content-Type": "application/x-www-form-urlencoded"})
        with opener.open(token_req, timeout=20) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
        return tokens.get("access_token")
    except Exception as e:
        print(f"    Connexion Shopopop échouée (échange du token) : {e}")
        return None


def _rechercher_livraison_programmee(access_token, drive_id, date_livraison, nom_complet):
    """Cherche, parmi les livraisons "Programmées" (status="schedule" — seule
    valeur de statut acceptée par l'API back-office pour ce paramètre ; une
    requête sans "status" est refusée avec une erreur HTTP 400) du magasin
    `drive_id` prévues pour `date_livraison` (objet date), celle dont le
    destinataire correspond à `nom_complet` (comparaison par ensemble de mots
    normalisés, insensible à l'ordre nom/prénom, aux accents et à la casse).
    Retourne l'item brut (dict) trouvé, ou None si absent — dans ce cas,
    un message est affiché indiquant le motif precis (aucune livraison
    "Programmee" ce jour-la, ou des livraisons existent mais aucune ne
    correspond au nom, auquel cas les noms rencontres sont listes pour
    faciliter le diagnostic d'un probleme de rapprochement nom/prenom).
    Peut lever une exception en cas d'erreur réseau/API — à la charge de
    l'appelant de la gérer, pour ne pas confondre un échec de vérification
    avec une absence confirmée (livraison sortie de "Programmées")."""
    if not access_token:
        return None
    cible = _tokens(nom_complet)
    if not cible:
        return None

    debut_paris = datetime.combine(date_livraison, time.min, tzinfo=_TZ)
    fin_paris = datetime.combine(date_livraison, time.max, tzinfo=_TZ)
    debut_utc = debut_paris.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fin_utc = fin_paris.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.999Z")

    noms_vus = []
    page = 1
    while True:
        url = _API_BASE + "/deliveries?" + urllib.parse.urlencode({
            "drive_id": drive_id, "order": "ASC", "page": page, "per_page": 50,
            "status": "schedule",
            "withdrawal_start_utc": debut_utc,
            "withdrawal_end_utc": fin_utc,
        })
        req = urllib.request.Request(url, headers={
            **_HEADERS_NAVIGATEUR,
            "Authorization": f"Bearer {access_token}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items", [])
        for it in items:
            dest = it.get("recipient") or {}
            nom_dest = f"{dest.get('first_name', '')} {dest.get('last_name', '')}"
            if _tokens(nom_dest) == cible:
                return it
            noms_vus.append(nom_dest)

        if len(items) < 50:
            break
        page += 1

    if noms_vus:
        print(f"    Shopopop : '{nom_complet}' absent des {len(noms_vus)} livraison(s) "
              f"'Programmees' du {date_livraison.strftime('%d/%m/%Y')} (drive {drive_id}). "
              f"Destinataires vus : {', '.join(noms_vus[:10])}"
              + (", ..." if len(noms_vus) > 10 else "") + ".")
    else:
        print(f"    Shopopop : aucune livraison 'Programmee' pour le "
              f"{date_livraison.strftime('%d/%m/%Y')} (drive {drive_id}) — la commande n'a "
              f"peut-etre pas encore ete synchronisee cote Shopopop.")
    return None


def distance_km(access_token, drive_id, date_livraison, nom_complet):
    """Cherche, parmi les livraisons "Programmées" du magasin `drive_id`
    prévues pour `date_livraison`, celle dont le destinataire correspond à
    `nom_complet`, et retourne sa distance en km (arrondie à 2 décimales),
    ou None si non trouvée/erreur."""
    try:
        it = _rechercher_livraison_programmee(access_token, drive_id, date_livraison, nom_complet)
    except Exception as e:
        print(f"    Recherche distance Shopopop échouée ({nom_complet}) : {e}")
        return None
    if not it:
        return None
    metres = it.get("delivery_distance")
    return round(metres / 1000, 2) if isinstance(metres, (int, float)) else None


def livraison_sortie_programmees(access_token, drive_id, date_livraison, nom_complet):
    """Vérifie si la livraison du destinataire `nom_complet` prévue pour
    `date_livraison` a quitté l'onglet "Programmées" de Shopopop (donc
    vraisemblablement passée en "Livrées" — l'API ne permet pas d'interroger
    un autre statut que "schedule", cf. _rechercher_livraison_programmee).
    Retourne True si absente de "Programmées" (livrée), False si toujours
    "Programmées" (pas encore livrée), ou None si la vérification a échoué
    (connexion/API) — à distinguer d'un True, pour ne pas signaler à tort
    une livraison comme confirmée en cas de panne."""
    try:
        it = _rechercher_livraison_programmee(access_token, drive_id, date_livraison, nom_complet)
    except Exception as e:
        print(f"    Recherche Shopopop échouée ({nom_complet}) : {e}")
        return None
    return it is None
