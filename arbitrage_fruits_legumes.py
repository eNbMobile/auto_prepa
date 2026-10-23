#!/usr/bin/env python3
"""Arbitrage automatique des produits fruits/légumes absents de
gencod_nomenclatures.csv.

Contexte : un produit sans adresse valide (gencod_adresses.csv) ET sans
nomenclature connue (gencod_nomenclatures.csv) finit dans le rapport des
« non adressés » (adresses_inconnues.py), même quand il s'agit en réalité
d'un fruit ou d'un légume — les rayons fruits/légumes ne sont normalement
jamais adressés produit par produit (cf. RAYONS_EXCLUS), mais ça ne joue que
si la nomenclature du gencod est connue. Or chaque changement de calibre,
d'origine ou de variété sur un fruit/légume crée un nouveau gencod, absent
de gencod_nomenclatures.csv, quasi quotidiennement.

Ce module tente de classer automatiquement ces produits-là (uniquement ceux
absents de gencod_nomenclatures.csv) en fruit ou légume, à partir du
libellé seul : il faut y trouver le nom d'un fruit ou d'un légume ET un
pays d'origine (généralement en capitales en fin de libellé). Si les deux
conditions sont réunies sans ambiguïté, le gencod est ajouté à
gencod_nomenclatures.csv avec le code de nomenclature déjà utilisé pour le
rayon fruits ou légumes (cherché dans chemin_prepa_ramasse.csv). Sinon
(pays introuvable, ou fruit/légume ambigu), le produit est signalé par
email pour un arbitrage manuel — le seul destinataire est EMAIL_DESTINATAIRE
(pas de copie), pour ne pas mélanger ça avec le rapport habituel.

Un libellé qui ne contient aucun nom de fruit/légume reconnu n'est pas
concerné par ce module : il reste traité comme un « non adressé » classique.
"""
import re
import unicodedata

# ─────────────────────────────────────────────────────────────────
# Listes de reconnaissance (libellés normalisés : majuscules, sans accents)
# ─────────────────────────────────────────────────────────────────

# Phrases fruit/légume à plusieurs mots, cherchées avant les mots seuls pour
# éviter les faux positifs (ex. "POMMES DE TERRE" ne doit pas déclencher le
# mot seul "POMME", qui est un fruit).
_PHRASES_LEGUMES = (
    r"\bPOMMES?\s+DE\s+TERRE\b",
    r"\bPATATES?\s+DOUCES?\b",
    r"\bPETITS?\s+POIS\b",
    r"\bCHOUX?[\s-]FLEURS?\b",
)

FRUITS_MOTS = {
    "POMME", "POMMES", "POIRE", "POIRES", "BANANE", "BANANES", "ORANGE",
    "ORANGES", "CLEMENTINE", "CLEMENTINES", "MANDARINE", "MANDARINES",
    "CITRON", "CITRONS", "PAMPLEMOUSSE", "PAMPLEMOUSSES", "KIWI", "KIWIS",
    "RAISIN", "RAISINS", "FRAISE", "FRAISES", "FRAMBOISE", "FRAMBOISES",
    "MYRTILLE", "MYRTILLES", "CERISE", "CERISES", "PECHE", "PECHES",
    "NECTARINE", "NECTARINES", "ABRICOT", "ABRICOTS", "PRUNE", "PRUNES",
    "MELON", "MELONS", "PASTEQUE", "PASTEQUES", "MANGUE", "MANGUES",
    "ANANAS", "GRENADE", "GRENADES", "FIGUE", "FIGUES", "DATTE", "DATTES",
    "LITCHI", "LITCHIS", "GOYAVE", "GOYAVES", "KAKI", "KAKIS", "COING",
    "COINGS", "MIRABELLE", "MIRABELLES", "QUETSCHE", "QUETSCHES",
    "GROSEILLE", "GROSEILLES", "CASSIS", "RHUBARBE", "AVOCAT", "AVOCATS",
    "NOIX", "PHYSALIS",
}

LEGUMES_MOTS = {
    "TOMATE", "TOMATES", "CAROTTE", "CAROTTES", "OIGNON", "OIGNONS",
    "ECHALOTE", "ECHALOTES", "AIL", "POIREAU", "POIREAUX", "CHOU", "CHOUX",
    "BROCOLI", "BROCOLIS", "SALADE", "SALADES", "LAITUE", "LAITUES",
    "ENDIVE", "ENDIVES", "CONCOMBRE", "CONCOMBRES", "COURGETTE",
    "COURGETTES", "AUBERGINE", "AUBERGINES", "POIVRON", "POIVRONS",
    "PIMENT", "PIMENTS", "HARICOT", "HARICOTS", "FEVE", "FEVES",
    "CHAMPIGNON", "CHAMPIGNONS", "NAVET", "NAVETS", "BETTERAVE",
    "BETTERAVES", "CELERI", "ARTICHAUT", "ARTICHAUTS", "EPINARD",
    "EPINARDS", "BLETTE", "BLETTES", "FENOUIL", "FENOUILS", "RADIS",
    "PANAIS", "TOPINAMBOUR", "TOPINAMBOURS", "CRESSON", "MACHE",
    "ROQUETTE", "PERSIL", "CIBOULETTE", "COURGE", "COURGES", "POTIRON",
    "POTIRONS", "BUTTERNUT", "MAIS", "ASPERGE", "ASPERGES",
}

PAYS = {
    "FRANCE", "ESPAGNE", "ITALIE", "MAROC", "PORTUGAL", "PAYS-BAS",
    "HOLLANDE", "BELGIQUE", "ALLEMAGNE", "GRECE", "EGYPTE", "TUNISIE",
    "ALGERIE", "ISRAEL", "TURQUIE", "CHYPRE", "PEROU", "CHILI",
    "ARGENTINE", "BRESIL", "COLOMBIE", "EQUATEUR", "COSTA RICA",
    "REPUBLIQUE DOMINICAINE", "MEXIQUE", "PANAMA", "COTE D'IVOIRE",
    "COTE DIVOIRE", "CAMEROUN", "SENEGAL", "KENYA", "AFRIQUE DU SUD",
    "GHANA", "CHINE", "INDE", "THAILANDE", "VIETNAM", "ETATS-UNIS",
    "ETATS UNIS", "USA", "NOUVELLE-ZELANDE", "NOUVELLE ZELANDE",
    "AUSTRALIE", "POLOGNE", "HONGRIE", "SUISSE",
}

LETTRE_FRUIT  = "R"   # cf. adresses_inconnues.RAYONS_EXCLUS
LETTRE_LEGUME = "S"


def _normaliser(texte):
    """Majuscules, sans accents."""
    texte = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c)).upper()


def classifier_fruit_legume(libelle):
    """Tente de classer un libellé en fruit ou légume.

    Retourne (categorie, raison_doute) :
    - ("fruit" | "legume", None) : classé avec confiance ;
    - (None, raison) : ressemble à un fruit/légume mais arbitrage manuel
      nécessaire (pays introuvable, ou fruit/légume ambigu) ;
    - (None, None) : libellé sans fruit/légume reconnu, non concerné par cet
      arbitrage (reste un « non adressé » classique)."""
    norm = _normaliser(libelle)

    est_legume_phrase = any(re.search(p, norm) for p in _PHRASES_LEGUMES)
    sans_phrases = norm
    for p in _PHRASES_LEGUMES:
        sans_phrases = re.sub(p, " ", sans_phrases)
    mots = set(re.findall(r"[A-Z]+", sans_phrases))

    est_fruit  = bool(mots & FRUITS_MOTS)
    est_legume = est_legume_phrase or bool(mots & LEGUMES_MOTS)

    if not est_fruit and not est_legume:
        return None, None
    if est_fruit and est_legume:
        return None, "fruit ou légume ambigu dans le libellé"

    pays_trouve = any(re.search(rf"\b{re.escape(p)}\b", norm) for p in PAYS)
    if not pays_trouve:
        return None, "pays d'origine introuvable dans le libellé"

    return ("fruit" if est_fruit else "legume"), None


def code_nomenclature_rayon(contenu_chemin_ramasse, lettre):
    """Cherche dans chemin_prepa_ramasse.csv ('clé;libellé_rayon;lettre',
    cf. controle_stocks.charger_ordre_chemin_prepa) le premier code de
    nomenclature (clé numérique) déjà routé vers le rayon `lettre`. Retourne
    ce code (à réutiliser pour un nouveau gencod du même rayon), ou None."""
    for ligne in (contenu_chemin_ramasse or "").splitlines():
        champs = ligne.strip().split(";")
        if len(champs) >= 3 and champs[0].isdigit() and champs[2].strip() == lettre:
            return champs[0].strip()
    return None


def arbitrer(produits, nomenclatures):
    """produits : {gencod: {"libelle": ..., ...}} (sortie de
    adresses_inconnues.regrouper). nomenclatures : {gencod: code} déjà connu
    (gencod_nomenclatures.csv).

    Retourne (ajouts, doutes, restants) :
    - ajouts : [(gencod, libelle, "fruit"|"legume")] classés avec confiance ;
    - doutes : [(gencod, libelle, raison)] à arbitrer à la main ;
    - restants : produits non concernés (déjà nomenclaturés, ou libellé sans
      fruit/légume reconnu) — à traiter comme avant."""
    ajouts, doutes, restants = [], [], {}
    for gencod, info in produits.items():
        if gencod in nomenclatures:
            restants[gencod] = info
            continue
        categorie, raison = classifier_fruit_legume(info["libelle"])
        if categorie:
            ajouts.append((gencod, info["libelle"], categorie))
        elif raison:
            doutes.append((gencod, info["libelle"], raison))
        else:
            restants[gencod] = info
    return ajouts, doutes, restants


def ajouter_nomenclatures(cs, ajouts):
    """Ajoute à gencod_nomenclatures.csv (Drive, via controle_stocks `cs`)
    une ligne par produit résolu dans `ajouts` ([(gencod, libelle,
    categorie)]). Les produits dont le code de nomenclature du rayon est
    introuvable (chemin_prepa_ramasse.csv mal configuré) sont renvoyés pour
    arbitrage manuel plutôt que silencieusement ignorés.

    Retourne la liste des (gencod, libelle, raison) à ajouter aux doutes."""
    if not ajouts:
        return []
    contenu_chemin = cs._lire_config_drive("chemin_prepa_ramasse.csv") or ""
    code_fruit  = code_nomenclature_rayon(contenu_chemin, LETTRE_FRUIT)
    code_legume = code_nomenclature_rayon(contenu_chemin, LETTRE_LEGUME)

    a_ecrire, reportes = [], []
    for gencod, libelle, categorie in ajouts:
        code = code_fruit if categorie == "fruit" else code_legume
        if not code:
            reportes.append((gencod, libelle,
                             f"code de nomenclature {categorie} introuvable "
                             f"dans chemin_prepa_ramasse.csv"))
            continue
        a_ecrire.append((gencod, libelle, code))

    if a_ecrire:
        lignes = [f"{gencod};{code}" for gencod, _, code in a_ecrire]
        if cs.ajouter_lignes_config_drive("gencod_nomenclatures.csv", lignes):
            print(f"  {len(lignes)} produit(s) fruit/légume ajouté(s) à "
                  f"gencod_nomenclatures.csv.")
        else:
            print("  Échec de l'ajout à gencod_nomenclatures.csv.")
            reportes.extend((gencod, libelle, "écriture gencod_nomenclatures.csv échouée")
                            for gencod, libelle, _ in a_ecrire)
    return reportes


def envoyer_email_doute(gmail_svc, destinataire, doutes):
    """Envoie, au seul destinataire `destinataire` (pas de copie), un email
    listant les produits fruit/légume dont la catégorie n'a pas pu être
    déterminée automatiquement, pour arbitrage manuel dans
    gencod_nomenclatures.csv. Ne fait rien si `doutes` est vide."""
    import base64
    from email.mime.text import MIMEText

    if not doutes:
        return
    n = len(doutes)
    lignes = "\n".join(f"- {gencod} ; {libelle} ({raison})"
                       for gencod, libelle, raison in doutes)
    corps = (
        f"Bonjour,\n\n{n} produit{'s' if n > 1 else ''} ressemble"
        f"{'nt' if n > 1 else ''} à un fruit ou un légume mais n'"
        f"{'ont' if n > 1 else 'a'} pas pu être classé automatiquement "
        f"(fruit ou légume) dans gencod_nomenclatures.csv :\n\n{lignes}\n\n"
        f"Merci de les arbitrer à la main (ajouter le gencod dans "
        f"gencod_nomenclatures.csv avec le code de nomenclature fruit ou "
        f"légume approprié).\n"
    )
    msg = MIMEText(corps, "plain", "utf-8")
    msg["To"] = destinataire
    msg["Subject"] = (f"Arbitrage fruits/légumes — {n} produit{'s' if n > 1 else ''} "
                      f"à traiter")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail_svc.users().messages().send(userId="me", body={"raw": raw}).execute()
