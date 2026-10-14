#!/usr/bin/env python3
"""Portage Python de prepa_drive_degrade (C, prepa_drive_degrade/*.c).

Transforme le BonDeCommande_NUMERO.pdf present dans le dossier courant en
bon_prepa.txt (produits ranges dans l'ordre du chemin de preparation, avec
adresse, emplacement et DLC) et bon_anticipation.txt (produits a sortir la
veille, par rayon), exactement comme le binaire C.

Choix de portage : transposition FIDELE, pas reecriture. Le C lit le texte du
PDF (pdftotext -layout) caractere par caractere a des positions fixes ; ses
regles implicites (decalages, cas limites, ordre des tests) font le resultat
actuel des bons. Chaque fonction ci-dessous reprend donc la fonction C du meme
nom, dans le meme ordre, avec les memes etats, et les fichiers intermediaires
du C (temp, gentemp.txt, base_client.txt...) sont remplaces par des tampons en
memoire de meme comportement. La comparaison automatique C / Python sur de
vrais bons (WF « Comparer moteurs de prepa ») sert de garde-fou.

Ecarts volontaires avec le C, tous limites a des cas ou le C plante, boucle ou
lit de la memoire hors de ses tableaux :
- fins de ligne des CSV : le dernier caractere n'est retire que s'il s'agit
  d'un \\r (le C le retirait toujours, d'ou l'incident du « -0 » quand
  gencod_adresses.csv etait passe en LF) ;
- tableaux de taille fixe du C (position[5] dans rangement_produits, lignes de
  plus de 200/500 caracteres...) : pas de debordement memoire en Python ;
- lecture hors tableau (index negatif) : vaut 0 ;
- fin de fichier atteinte au milieu d'une lecture : arret propre au lieu d'une
  boucle infinie ;
- n° de commande de longueur autre que 8 chiffres accepte.
Seul le mode MONO (un seul PDF, cas d'auto_prepa.py) est porte ; le mode
RAMASSE (plusieurs PDF) du C n'est utilise par aucun workflow.

Les fichiers de config lus sont ceux du C : gencod_adresses.csv,
gencod_nomenclatures.csv, chemin_prepa_mono.csv (dossier courant).
"""
import glob
import os
import struct
import subprocess
import sys

NL = 10      # '\n'
SP = 32      # ' '
SEMI = 59    # ';'


def _o(c):
    return ord(c)


def _s(b):
    """Octet (0..255) -> char signe du C (-128..127)."""
    return b - 256 if b > 127 else b


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


# ─────────────────────────────────────────────────────────────────
# Emulation des E/S du C
# ─────────────────────────────────────────────────────────────────

class Flux:
    """FILE* en lecture : getc() et un fscanf() limite a %d %c %f, aux
    caracteres litteraux et aux blancs, avec l'arret au premier echec du C."""

    def __init__(self, data):
        self.d = data if data is not None else b""
        self.p = 0

    def getc(self):
        if self.p < len(self.d):
            c = self.d[self.p]
            self.p += 1
            return _s(c)
        return -1

    def eof(self):
        return self.p >= len(self.d)

    def _peek(self):
        return self.d[self.p] if self.p < len(self.d) else None

    def _blancs(self):
        while self._peek() is not None and self._peek() in b" \t\n\v\f\r":
            self.p += 1

    def scanf(self, fmt):
        """Valeurs lues, None pour celles que le C n'aurait pas affectees."""
        vals = []
        i = 0
        echec = False
        while i < len(fmt):
            f = fmt[i]
            if echec:
                if f == "%":
                    vals.append(None)
                    i += 2
                else:
                    i += 1
                continue
            if f == "%":
                t = fmt[i + 1]
                i += 2
                if t == "c":
                    c = self._peek()
                    if c is None:
                        echec = True
                        vals.append(None)
                    else:
                        self.p += 1
                        vals.append(_s(c))
                elif t == "d":
                    self._blancs()
                    debut = self.p
                    if self._peek() is not None and self._peek() in b"+-":
                        self.p += 1
                    d0 = self.p
                    while self._peek() is not None and 48 <= self._peek() <= 57:
                        self.p += 1
                    if self.p == d0:
                        echec = True
                        vals.append(None)
                    else:
                        vals.append(int(self.d[debut:self.p]))
                elif t == "f":
                    self._blancs()
                    debut = self.p
                    if self._peek() is not None and self._peek() in b"+-":
                        self.p += 1
                    nb = 0
                    while self._peek() is not None and 48 <= self._peek() <= 57:
                        self.p += 1
                        nb += 1
                    if self._peek() == 46:
                        self.p += 1
                        while self._peek() is not None and 48 <= self._peek() <= 57:
                            self.p += 1
                            nb += 1
                    if nb == 0:
                        texte = self.d[debut:debut + 3].lower()
                        if texte in (b"inf", b"nan"):
                            self.p = debut + 3
                            vals.append(_f32(float(texte.decode())))
                            continue
                        echec = True
                        vals.append(None)
                    else:
                        if self._peek() is not None and self._peek() in b"eE":
                            sauve = self.p
                            self.p += 1
                            if self._peek() is not None and self._peek() in b"+-":
                                self.p += 1
                            e0 = self.p
                            while self._peek() is not None and 48 <= self._peek() <= 57:
                                self.p += 1
                            if self.p == e0:
                                self.p = sauve
                        vals.append(_f32(float(self.d[debut:self.p])))
                else:
                    raise ValueError(fmt)
            elif f in " \t\n":
                self._blancs()
                i += 1
            else:
                if self._peek() == ord(f):
                    self.p += 1
                else:
                    echec = True
                i += 1
        return vals


class Buf:
    """Tableau char du C initialise a 0 : lecture hors bornes = 0."""

    def __init__(self):
        self.t = []

    def __getitem__(self, i):
        return self.t[i] if 0 <= i < len(self.t) else 0

    def __setitem__(self, i, v):
        if i < 0:
            return
        if i >= len(self.t):
            self.t.extend([0] * (i + 1 - len(self.t)))
        self.t[i] = v

    def cstr(self):
        """Contenu jusqu'au premier octet nul (%s du C)."""
        out = bytearray()
        for v in self.t:
            if v == 0:
                break
            out.append(v & 0xFF)
        return bytes(out)


def lire_jusqua(flux, fin, buf=None):
    """Boucle C : buf[0]=getc ; while (buf[j] != fin) { j++; buf[j]=getc; }.
    Retourne (buf, j) ; buf[j] vaut `fin` (ou -1 a la fin du fichier)."""
    buf = buf if buf is not None else Buf()
    j = 0
    buf[j] = flux.getc()
    while buf[j] != fin and buf[j] != -1:
        j += 1
        buf[j] = flux.getc()
    return buf, j


def champ(flux, fin):
    """Champ lu jusqu'a `fin` (exclu), comme une chaine C terminee a cet endroit."""
    buf, j = lire_jusqua(flux, fin)
    buf[j] = 0
    return buf.cstr()


def nb_lignes(data):
    """wc -l"""
    return data.count(b"\n") if data else 0


class Fichier:
    """Fichier ouvert en ajout ("a") par le C, relu depuis le debut."""

    def __init__(self):
        self.data = None

    def ajouter(self, b):
        if isinstance(b, str):
            b = b.encode("utf-8")  # litteraux du source C, ecrit en UTF-8
        self.data = (self.data or b"") + b

    def car(self, v):
        self.ajouter(bytes([v & 0xFF]))

    def lire(self):
        return Flux(self.data)

    def supprimer(self):
        self.data = None

    def premiere_ligne(self):
        """Lecture d'une ligne (jusqu'au '\\n') depuis le debut."""
        return champ(self.lire(), NL)


def _p(fmt, *args):
    """fprintf : %s / %c / %d / %02d / %.2f sur des octets."""
    out = bytearray()
    i = 0
    a = 0
    while i < len(fmt):
        c = fmt[i]
        if c != "%":
            out += c.encode("utf-8")
            i += 1
            continue
        if fmt[i + 1] == "s":
            v = args[a]
            out += v if isinstance(v, (bytes, bytearray)) else str(v).encode("utf-8")
            i += 2
        elif fmt[i + 1] == "c":
            out.append(args[a] & 0xFF)
            i += 2
        elif fmt[i + 1] == "d":
            out += str(args[a]).encode()
            i += 2
        elif fmt[i + 1:i + 4] == "02d":
            out += f"{args[a]:02d}".encode()
            i += 4
        elif fmt[i + 1:i + 4] == ".2f":
            out += (b"%.2f" % args[a])
            i += 4
        else:
            raise ValueError(fmt)
        a += 1
    return bytes(out)


# ─────────────────────────────────────────────────────────────────
# Comparaison des gencods (gencod_correspond) et index des CSV
# ─────────────────────────────────────────────────────────────────

def gencod_correspond(produit, ref):
    """Identique au C : 12 premiers chiffres, puis sans les 0 de tete du
    produit (ref d'au moins 8 caracteres, cle de controle ignoree)."""
    def pc(i):
        return produit[i] if i < len(produit) else 0
    lr = len(ref)
    if lr >= 12 and all(pc(i) == ref[i] for i in range(12)):
        return True
    d = 0
    while pc(d) == 48:
        d += 1
    if d > 0 and lr >= 8 and d + lr < 19:
        if all(pc(d + i) == ref[i] for i in range(lr - 1)):
            return True
    return False


class TableGencods:
    """Lignes « gencod;valeur » d'un CSV, avec recherche de la PREMIERE ligne
    dont le gencod correspond (meme resultat que le parcours lineaire du C,
    sans relire 15 Mo par produit).

    `valeur_c` : valeur brute lue jusqu'au \\n (comme le C, \\r compris) ;
    `valeur` : valeur sans le \\r final (le C retirait le dernier caractere)."""

    def __init__(self, data):
        brutes = (data or b"").split(b"\n")[:nb_lignes(data)]
        if all(b";" in l for l in brutes):
            # Cas normal : une ligne = « gencod;valeur ». Lecture directe,
            # identique a la lecture caractere par caractere du C.
            self.lignes = [tuple(l.split(b";", 1)) for l in brutes]
        else:
            # Ligne sans ';' : le C lit alors le gencod a cheval sur la
            # ligne suivante ; on reproduit sa lecture exacte.
            flux = Flux(data)
            self.lignes = []
            for _ in range(nb_lignes(data)):
                g = champ(flux, SEMI)
                v = champ(flux, NL)
                self.lignes.append((g, v))
        self._p12 = {}
        self._court = {}
        for idx, (g, _) in enumerate(self.lignes):
            if len(g) >= 12:
                self._p12.setdefault(g[:12], idx)
            if len(g) >= 8:
                self._court.setdefault((len(g), g[:len(g) - 1]), idx)

    def chercher(self, produit):
        """Index de la premiere ligne correspondante, ou None."""
        candidats = []
        p12 = bytes((produit[i] if i < len(produit) else 0) for i in range(12))
        if p12 in self._p12:
            candidats.append(self._p12[p12])
        d = 0
        while d < len(produit) and produit[d] == 48:
            d += 1
        if d > 0:
            for lr in range(8, 19 - d):
                cle = (lr, produit[d:d + lr - 1])
                if len(cle[1]) == lr - 1 and cle in self._court:
                    candidats.append(self._court[cle])
        return min(candidats) if candidats else None


def _sans_cr(v):
    return v[:-1] if v.endswith(b"\r") else v


# ─────────────────────────────────────────────────────────────────
# Moteur
# ─────────────────────────────────────────────────────────────────

class Moteur:
    def __init__(self, dossier="."):
        self.dossier = dossier
        self.sortie = []           # messages console (printf)
        self.qte_totale = 0
        self.subs_mono = 0
        self.nb_files_def = 1
        self.jour2 = self.mois2 = self.annee2 = 0
        self.f = {}                # fichiers intermediaires

    # -- utilitaires
    def chemin(self, nom):
        return os.path.join(self.dossier, nom)

    def lire_csv(self, nom):
        try:
            with open(self.chemin(nom), "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return b""

    def printf(self, texte):
        self.sortie.append(texte)
        print(texte, end="", flush=True)

    # -- 1. change_format_fichier
    def change_format_fichier(self):
        self.printf("Conversion du fichier...\n")
        pdfs = sorted(glob.glob(self.chemin("*.pdf")))
        self.nb_files_def = len(pdfs)
        if len(pdfs) != 1:
            raise SystemExit(
                f"prepa_drive_degrade.py : {len(pdfs)} PDF dans le dossier, seul le mode "
                f"MONO (1 PDF) est porte.")
        pdf = pdfs[0]
        r = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True)
        os.remove(pdf)
        self.encaissement = r.stdout.replace(b";", b"")
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- 2. test_bon_encaissement
    def test_bon_encaissement(self):
        self.printf("Test du fichier...\n")
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")
        if b"SUBSTI." in self.encaissement:
            self.rewrite_bon_encaissement_agp()
        else:
            self.rewrite_bon_encaissement_sgp()

    # -- commun SGP/AGP
    @staticmethod
    def _nom_client(L, j, base):
        """Blocs « nom du client » : caracteres j-50..j-10, un espace double
        n'en laisse qu'un."""
        for p in range(j - 50, j - 9):
            if not (L[p] == SP and L[p + 1] == SP):
                base.car(L[p])

    @staticmethod
    def _prix_kg(L, j, sortie, prefixe):
        """Lignes « K;O;/N; prix au kilo » communes aux parseurs."""
        sortie.ajouter(prefixe + ("O;" if L[j - 1] == _o("K") and L[j] == _o("G") else "N;"))
        if L[j - 12] == SP:
            if L[j - 11] == SP:
                sortie.ajouter(_p("%c.%c%c;", L[j - 10], L[j - 8], L[j - 7]))
            else:
                sortie.ajouter(_p("%c%c.%c%c;", L[j - 11], L[j - 10], L[j - 8], L[j - 7]))
        else:
            sortie.ajouter(_p("%c%c%c.%c%c;", L[j - 12], L[j - 11], L[j - 10], L[j - 8], L[j - 7]))

    @staticmethod
    def _euro_kg(L, j):
        return (L[j - 6] == SP and L[j - 5] == -30 and L[j - 4] == -126
                and L[j - 3] == -84 and L[j - 2] == _o("/"))

    @staticmethod
    def _prix_pu(L, j, sortie, prefixe=""):
        """Prix unitaire en fin de ligne (« 12,34 € »)."""
        if L[j - 10] == SP:
            if L[j - 9] == SP and (L[j - 8] != _o("0") or L[j - 6] != _o("0")):
                sortie.ajouter(prefixe.encode() + _p("%c.%c%c;", L[j - 8], L[j - 6], L[j - 5]))
            elif L[j - 9] != SP and L[j - 9] != _o("0"):
                sortie.ajouter(prefixe.encode() + _p("%c%c.%c%c;", L[j - 9], L[j - 8], L[j - 6], L[j - 5]))
        elif L[j - 10] != _o("0"):
            sortie.ajouter(prefixe.encode() + _p("%c%c%c.%c%c;", L[j - 10], L[j - 9], L[j - 8], L[j - 6], L[j - 5]))

    def _en_tete_commande(self, L, j, i, db, base, type_retrait, etat, agp):
        """Date, heure, n° de commande, type de retrait/paiement (blocs
        identiques en SGP et AGP, a la date pres)."""
        if i < 6 and L[j - 7] == _o("/") and L[j - 4] == _o("/"):
            for p in range(j - 18, j - 10):
                if L[p] != SP:
                    base.car(L[p])
            if agp:
                base.car(L[j - 10])
                for p in range(j - 9, j + 1):
                    if L[p] != SP:
                        base.car(L[p])
            else:
                for p in range(j - 10, j + 1):
                    base.car(L[p])
            base.ajouter(" - ")
        if i < 8 and L[j - 10] == _o("h") and L[j - 6] == _o("-") and L[j - 2] == _o("h"):
            base.ajouter(_p("%c%c%c%c%c%c%c%c%c%c%c,", L[j - 12], L[j - 11], L[j - 10], L[j - 9],
                            L[j - 8], L[j - 6], L[j - 4], L[j - 3], L[j - 2], L[j - 1], L[j]))
        if (i < 10 and L[j - 18] == _o("C") and L[j - 17] == _o("o") and L[j - 11] == _o("e")
                and L[j - 9] == _o(":")):
            for p in range(j - 7, j + 1):
                if L[p] != SP:
                    base.car(L[p])
            base.ajouter(",")
        if i == 8 and L[0] in (_o("R"), _o("L"), _o("P")) and etat["type"] == 0:
            type_retrait[:] = {_o("R"): b"Retrait", _o("L"): b"Livraison",
                               _o("P"): b"Point relais"}[L[0]]
            # Le C lit ici directement dans le fichier la suite de la ligne :
            # tout jusqu'au premier 'P' (Paiement...), puis jusqu'au '\n'.
            pbl0 = db.getc()
            c = db.getc()
            while c != _o("P") and c != -1:
                c = db.getc()
            tp = Buf()
            tp[0] = c
            tp[1] = db.getc()
            a = 1
            while tp[a] != NL and tp[a] != -1:
                a += 1
                tp[a] = db.getc()
            tp[a] = 0
            base.ajouter(bytes(type_retrait) + b"," + tp.cstr() + b",")
            L[j] = NL
            etat["type"] = 1
            del pbl0

    # -- 3a. rewrite_bon_encaissement_sgp
    def rewrite_bon_encaissement_sgp(self):
        self.printf("Réécriture du fichier SGP...\n")
        db = Flux(self.encaissement)
        nbl = nb_lignes(self.encaissement)
        new = self.f["NEW"] = Fichier()
        base = self.f["base"] = Fichier()
        temp = Fichier()
        gentemp = Fichier()
        temp_lib = Fichier()
        etat = {"type": 0}
        type_retrait = bytearray()
        i = 0
        recup_lib = i_lib = subs = offre = lib3 = lib_maison = sacs = 0
        while i < nbl:
            j = gen = compte = 0
            L = Buf()
            pass_ = passe = 0
            L[j] = db.getc()
            if i == 36 and sacs == 0:
                base.ajouter(",Pas de sacs\n")
                sacs = 1
            while L[j] != NL:
                if L[j] == -1 and db.eof():
                    break
                j += 1
                L[j] = db.getc()
                self._en_tete_commande(L, j, i, db, base, type_retrait, etat, agp=False)
                if (i < 15 and i > 9 and L[j - 50] == _o("M")
                        and (L[j - 49] == _o(".") or L[j - 49] == _o("m")) and pass_ == 0):
                    self._nom_client(L, j, base)
                    pass_ = 1
                if (type_retrait[:1] in (b"L", b"P")) and pass_ == 1 and L[j] == NL:
                    base.ajouter(",Sac(s) facturé(s)\n")
                    pass_ = 2
                if (i < 35 and L[j - 6] == _o("i") and L[j - 5] == _o("o")
                        and L[j - 4] == _o("n") and L[j - 2] == _o(">")):
                    if L[j] == _o("R"):
                        subs = 0
                    if L[j] == _o("A"):
                        subs = 1
                if bytes(L[p] & 0xFF for p in range(j - 10, j + 1)) == b"Pas de sacs":
                    base.ajouter(",Pas de sacs\n")
                    sacs = 1
                if bytes(L[p] & 0xFF for p in range(j - 7, j + 1)) == b"Sac(s) f":
                    base.ajouter(",Sac(s) facturé(s)\n")
                    sacs = 1
                if i == 36 and sacs == 0:
                    base.ajouter(",Pas de sacs\n")
                    sacs = 1
                if (L[j - 13] == _o("S") and L[j - 12] == _o("u") and L[j - 11] == _o("r")
                        and L[j - 10] == _o("g") and L[j - 9] == _o("e") and L[j - 8] == _o("l")
                        and L[j - 7] == -61 and L[j - 6] == -87 and L[j - 5] == SP
                        and L[j - 4] == _o(">") and L[j - 3] == SP):
                    if L[j - 2] == _o("O") and L[j - 1] == _o("U") and L[j] == _o("I"):
                        self.subs_mono = 1
                    elif L[j - 2] == _o("N") and L[j - 1] == _o("O") and L[j] == _o("N"):
                        self.subs_mono = 0
                if recup_lib == 42 and i_lib < i:
                    if (L[j - 6] == SP and L[j - 5] == -30 and L[j - 4] == -126
                            and L[j - 3] == -84 and L[j - 2] == _o("/")):
                        self._prix_kg(L, j, new, "")
                        bc = base.premiere_ligne()
                        new.ajouter((b"OUI;" if subs == 1 else b"NON;") + bc + b"\n"
                                    if subs in (0, 1) else b"")
                        recup_lib = 0
                        i_lib = 0
                if recup_lib == 31 and i_lib < i:
                    if L[j] != SP and L[j] != NL and j < 47 and gen < 13:
                        temp.car(L[j])
                        gen += 1
                    if self._euro_kg(L, j):
                        self._prix_kg(L, j, temp, ";")
                        if subs == 1:
                            temp.ajouter("OUI\n")
                        if subs == 0:
                            temp.ajouter("NON\n")
                    if L[j] == NL:
                        t = temp.lire()
                        lib1 = Buf()
                        tt = 0
                        lib1[tt] = t.getc()
                        while lib1[tt] != SEMI and lib1[tt] != -1:
                            tt += 1
                            lib1[tt] = t.getc()
                            if (lib1[tt - 4] == _o("&") and lib1[tt - 3] == _o("a")
                                    and lib1[tt - 2] == _o("m") and lib1[tt - 1] == _o("p")
                                    and lib1[tt] == SEMI):
                                tt -= 4
                        lib1[tt] = 0
                        prix1 = champ(t, SEMI)
                        qte = champ(t, SEMI)
                        lib2 = champ(t, SEMI)
                        reste = champ(t, NL)
                        temp.supprimer()
                        bc = base.premiere_ligne()
                        new.ajouter(prix1 + b";" + qte + b";" + lib1.cstr() + b" " + lib2
                                    + b";" + reste + b";" + bc + b"\n")
                        recup_lib = 0
                        i_lib = 0
                if recup_lib == 3 and i_lib < i:
                    if L[j] != SP and L[j] != NL and j < 47 and gen < 13 and lib_maison == 0:
                        gentemp.car(L[j])
                        gen += 1
                    if lib3 == 2 and j < 70:
                        if L[j - 1] != SP or L[j] != SP:
                            new.car(L[j - 1])
                    if (gen > 0 or lib_maison > 0) and L[j - 1] == SP and L[j] == SP:
                        if gen == 0:
                            gen = lib_maison + 1
                        lib_maison = 0
                        gentemp.ajouter(_p(";%d;", gen))
                        if lib3 == 1:
                            lib3 = 2
                    if self._euro_kg(L, j) or (L[j - 4] == SP and L[j - 3] == -30
                                               and L[j - 2] == -126 and L[j - 1] == -84
                                               and L[j] == NL):
                        g = gentemp.lire()
                        gencod = champ(g, SEMI)
                        v = g.scanf("%d;")
                        if v[0] is not None:
                            gen = v[0]
                        gentemp.supprimer()
                        if lib3 == 2:
                            new.ajouter(";")
                        if 3 <= gen <= 13:
                            new.ajouter(b"0" * (13 - gen) + gencod)
                        if lib3 == 0:
                            self._prix_kg(L, j, new, ";")
                            bc = base.premiere_ligne()
                            if subs == 1:
                                new.ajouter(b"OUI;" + bc + b"\n")
                            if subs == 0:
                                new.ajouter(b"NON;" + bc + b"\n")
                            recup_lib = 0
                            i_lib = 0
                    if L[j] == NL:
                        if lib3 == 0:
                            recup_lib = 0
                            i_lib = 0
                            gen = 0
                        else:
                            recup_lib = 42
                            i_lib = i
                            new.ajouter(";")
                        lib3 = 0
                        lib_maison = 0
                if recup_lib == 21 and i_lib < i:
                    if j == 16:
                        for p in range(j - 16, j + 1):
                            if L[p] != SP:
                                temp.car(L[p])
                        temp.ajouter(";")
                    elif j > 28:
                        if ((L[j - 10] != SP or L[j - 9] != SP) and (L[j - 9] != SP or L[j - 8] != SP)
                                and L[j - 9] != _o('"')):
                            temp.car(L[j - 9])
                        if L[j] == NL:
                            temp.ajouter(";")
                            recup_lib = 31
                            i_lib = i
                if recup_lib == 2 and i_lib < i:
                    tl = temp_lib.lire()
                    lib, a = lire_jusqua(tl, NL)
                    lib[a] = 0
                    lib = lib.cstr()
                    if j == 16:
                        for p in range(j - 16, j + 1):
                            if L[p] != SP:
                                new.car(L[p])
                        new.ajouter(";")
                        passe = 1
                    elif 16 < j <= 32:
                        if L[j - 1] != SP and L[j] != SP:
                            gentemp.car(L[j - 1])
                            lib_maison += 1
                    elif j > 42 and passe == 1:
                        if L[j - 11] == _o("&"):
                            compte = 1
                        if a > 0 and lib3 == 0:
                            new.ajouter(lib)
                            lib3 = 1
                        if ((L[j - 12] != SP or L[j - 11] != SP) and (L[j - 11] != SP or L[j - 10] != SP)
                                and L[j - 11] != _o('"') and compte <= 1):
                            new.car(L[j - 11])
                        if L[j] == NL:
                            for aa in (10, 9):
                                if L[j - aa] != SP:
                                    new.car(L[j - aa])
                            passe = 2
                        if compte >= 1:
                            compte += 1
                        if compte == 6:
                            compte = 0
                    if passe == 2:
                        if a == 0:
                            new.ajouter(";")
                        recup_lib = 3
                        i_lib = i
                        passe = 0
                        temp_lib.supprimer()
                if recup_lib == 1 and i_lib < i:
                    if i_lib == i - 1:
                        if L[j] == NL and (L[j - 3] == -30 or L[j - 3] == _o(".")):
                            self._prix_pu(L, j, new)
                            for aa in range(42, j - 16):
                                if L[aa] != SP or L[aa + 1] != SP:
                                    temp_lib.car(L[aa + 1])
                            temp_lib.ajouter("\n")
                            recup_lib = 2
                            i_lib = i
                    elif i_lib == i - 2:
                        if L[j - 11] == _o("&"):
                            compte = 1
                        if ((L[j - 12] != SP or L[j - 11] != SP) and (L[j - 11] != SP or L[j - 10] != SP)
                                and L[j - 11] != _o('"') and j > 30 and compte <= 1):
                            temp.car(L[j - 11])
                        if L[j] == NL:
                            temp.ajouter(";")
                            self._prix_pu(L, j, temp)
                            recup_lib = 21
                            i_lib = i
                        if compte >= 1:
                            compte += 1
                        if compte == 6:
                            compte = 0
                if (L[j - 2] == SP and L[j - 1] == _o("P") and L[j] == _o("U") and recup_lib == 0
                        and i > 34 and offre == 0 and j > 20):
                    recup_lib = 1
                    i_lib = i
                if bytes(L[p] & 0xFF for p in range(j - 8, j + 1)) == b"AVANTAGES" and i < 40:
                    offre = 1
                if i >= 40:
                    offre = 0
            i += 1
        self.f.pop("base", None)
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- 3b. rewrite_bon_encaissement_agp
    def rewrite_bon_encaissement_agp(self):
        self.printf("Réécriture du fichier AGP...\n")
        db = Flux(self.encaissement)
        nbl = nb_lignes(self.encaissement)
        new = self.f["NEW"] = Fichier()
        base = self.f["base"] = Fichier()
        temp = Fichier()
        etat = {"type": 0}
        type_retrait = bytearray()
        i = recup_lib = i_lib = 0
        while i < nbl:
            j = gen = passage = compte = 0
            L = Buf()
            pass_ = 0
            L[j] = db.getc()
            while L[j] != NL:
                if L[j] == -1 and db.eof():
                    break
                j += 1
                L[j] = db.getc()
                self._en_tete_commande(L, j, i, db, base, type_retrait, etat, agp=True)
                if (i < 12 and i > 9 and L[j - 51] == SP and L[j - 50] == _o("M")
                        and (L[j - 49] == _o(".") or L[j - 49] == _o("m")) and pass_ == 0):
                    self._nom_client(L, j, base)
                    pass_ = 1
                if type_retrait[:1] in (b"L", b"P") and i == 30 and L[j] == NL:
                    base.ajouter(",Sac(s) facturé(s)\n")
                if bytes(L[p] & 0xFF for p in range(j - 10, j + 1)) == b"Pas de sacs":
                    base.ajouter(",Pas de sacs\n")
                if bytes(L[p] & 0xFF for p in range(j - 7, j + 1)) == b"Sac(s) f":
                    base.ajouter(",Sac(s) facturé(s)\n")
                if recup_lib == 41 and i_lib < i:
                    if passage == 0:
                        t = temp.lire()
                        gencod = champ(t, SEMI)
                        temp.supprimer()
                        new.ajouter(gencod)
                        passage = 1
                    if bytes(L[p] & 0xFF for p in range(j - 5, j + 1)) == b".(Oui)":
                        new.ajouter(";OUI\n")
                    elif bytes(L[p] & 0xFF for p in range(j - 4, j + 1)) == b"(Non)":
                        new.ajouter(";NON\n")
                    if L[j] == NL:
                        recup_lib = 0
                        i_lib = 0
                if recup_lib == 31 and i_lib < i:
                    if passage == 0:
                        t = temp.lire()
                        prix = champ(t, SEMI)
                        qte = champ(t, SEMI)
                        temp.supprimer()
                        passage = 1
                        new.ajouter(prix + b";" + qte + b";")
                    if L[j] != SP and gen < 13:
                        temp.car(L[j])
                        gen += 1
                    if gen == 13:
                        if self._euro_kg(L, j):
                            self._prix_kg(L, j, new, "")
                            recup_lib = 41
                            i_lib = i
                            temp.ajouter(";")
                            passage = 0
                if recup_lib == 3 and i_lib < i:
                    if L[j] != SP and gen < 13:
                        new.car(L[j])
                        gen += 1
                    if gen == 13:
                        if bytes(L[p] & 0xFF for p in range(j - 5, j + 1)) == b".(Oui)":
                            new.ajouter(";OUI\n")
                        elif bytes(L[p] & 0xFF for p in range(j - 4, j + 1)) == b"(Non)":
                            new.ajouter(";NON\n")
                        if L[j] == NL:
                            recup_lib = 0
                            i_lib = 0
                if recup_lib == 21 and i_lib < i:
                    if j == 14:
                        for p in range(j - 14, j + 1):
                            if L[p] != SP:
                                temp.car(L[p])
                        temp.ajouter(";")
                    elif j > 14:
                        if bytes(L[p] & 0xFF for p in range(j - 8, j + 1)) == b"dont TVA\n":
                            new.ajouter(";")
                            recup_lib = 31
                            i_lib = 1
                        elif ((L[j - 9] != SP or L[j - 8] != SP) and (L[j - 8] != SP or L[j - 7] != SP)
                              and L[j - 8] != _o('"') and j > 20):
                            new.car(L[j - 8])
                if recup_lib == 2 and i_lib < i:
                    if j == 14:
                        for p in range(j - 14, j + 1):
                            if L[p] != SP:
                                new.car(L[p])
                    else:
                        if self._euro_kg(L, j):
                            self._prix_kg(L, j, new, ";")
                            recup_lib = 3
                            i_lib = i
                if recup_lib == 1 and i_lib < i:
                    if i_lib + 2 == i:
                        if L[j - 11] == _o("&"):
                            compte = 1
                        if ((L[j - 12] != SP or L[j - 11] != SP) and (L[j - 11] or L[j - 10] != SP)
                                and L[j - 11] != _o('"') and L[j - 11] != 0 and L[j - 11] != 1
                                and compte <= 1):
                            new.car(L[j - 11])
                        if L[j] == NL and L[j - 3] == -30:
                            self._prix_pu(L, j, new, ";")
                            if L[j - 8] != _o("0") or L[j - 6] != _o("0"):
                                recup_lib = 2
                                i_lib = i
                            else:
                                recup_lib = 0
                                i_lib = 0
                        if compte >= 1:
                            compte += 1
                        if compte == 6:
                            compte = 0
                    elif i_lib + 1 == i:
                        if L[j - 11] == _o("&"):
                            compte = 1
                        if ((L[j - 12] != SP or L[j - 11] != SP) and (L[j - 11] != SP or L[j - 10] != SP)
                                and L[j - 11] != _o('"') and L[j - 11] != 0 and L[j - 11] != 1
                                and compte <= 1):
                            new.car(L[j - 11])
                        if L[j] == NL and L[j - 3] == -30:
                            self._prix_pu(L, j, temp)
                            if L[j - 8] != _o("0") or L[j - 6] != _o("0"):
                                recup_lib = 21
                                i_lib = i
                                new.ajouter(" ")
                            else:
                                recup_lib = 0
                                i_lib = 0
                        if compte >= 1:
                            compte += 1
                        if compte == 6:
                            compte = 0
                if (L[j - 2] == SP and L[j - 1] == _o("P") and L[j] == _o("U") and recup_lib == 0
                        and i > 36):
                    recup_lib = 1
                    i_lib = i
            i += 1
        self.inverse_data()
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    def inverse_data(self):
        donnees = self.f["NEW"].data or b""
        db = Flux(donnees)
        cbc = self.f["base"].premiere_ligne()
        self.f.pop("base", None)
        out = Fichier()
        for _ in range(nb_lignes(donnees)):
            libelle = champ(db, SEMI)
            prix = champ(db, SEMI)
            qte = champ(db, SEMI)
            type_prix = champ(db, SEMI)
            prix_kg = champ(db, SEMI)
            gencod = champ(db, SEMI)
            subs = champ(db, NL)
            out.ajouter(b";".join([prix, qte, libelle, gencod, type_prix, prix_kg, subs, cbc]) + b"\n")
        self.f["NEW"] = out

    # -- 4. rewrite_bon_encaissement_02
    def rewrite_bon_encaissement_02(self):
        self.printf("Réécriture du fichier (2)...\n")
        donnees = self.f["NEW"].data or b""
        db = Flux(donnees)
        final = self.f["final"] = Fichier()
        nb_produits = 0
        for _ in range(nb_lignes(donnees)):
            temp = Fichier()
            qte = kilos = grammes = 0
            prix_b, j = lire_jusqua(db, SEMI)
            temp.ajouter(bytes(prix_b[p] & 0xFF for p in range(j + 1)))
            for p in range(1, j + 1):
                if prix_b[p] == _o("."):
                    prix_b[p] = _o(",")
            prix_b[j] = 0
            prix = prix_b.cstr()
            v = db.scanf("%d;")
            if v[0] is not None:
                qte = v[0]
            self.qte_totale += qte
            nb_produits += qte
            lib = Buf()
            j = 0
            lib[j] = db.getc()
            while lib[j] != SEMI and lib[j] != -1:
                j += 1
                lib[j] = db.getc()
                if lib[j - 1] == SP and lib[j] == SP:
                    j -= 1
                if (lib[j - 4] == _o("&") and lib[j - 3] == _o("a") and lib[j - 2] == _o("m")
                        and lib[j - 1] == _o("p") and lib[j] == SEMI):
                    j -= 4
            if lib[j - 1] == SP:
                lib[j - 1] = 0
            else:
                lib[j] = 0
            libelle = lib.cstr()
            gencod = champ(db, SEMI)
            v = db.scanf("%c;")
            poids = v[0] if v[0] is not None else 0
            prix2_b, j = lire_jusqua(db, SEMI)
            temp.ajouter(bytes(prix2_b[p] & 0xFF for p in range(j + 1)))
            for p in range(1, j + 1):
                if prix2_b[p] == _o("."):
                    prix2_b[p] = _o(",")
            prix2_b[j] = 0
            prix2 = prix2_b.cstr()
            sub = champ(db, SEMI)
            infos = champ(db, NL)
            g = gencod + b"\0" * 13

            def gc(k):
                return g[k]
            if not (gencod[:13] == b"3368958467809" and len(gencod) >= 13) and not (gc(0) == 57 and gc(1) == 57):
                if poids == _o("O") and (gc(0) == 48 or (gc(0) == 50 and (gc(1) != 48 or gc(2) != 48
                                                                          or gc(3) != 48 or gc(4) != 48))):
                    vals = temp.lire().scanf("%f;%f;")
                    prix3 = vals[0] if vals[0] is not None else 0.0
                    prix4 = vals[1] if vals[1] is not None else 0.0
                    try:
                        prixf = _f32(prix3 / prix4)
                    except ZeroDivisionError:
                        prixf = float("nan") if prix3 == 0 else float("inf") * (1 if prix3 > 0 else -1)
                    t2 = Fichier()
                    t2.ajouter(b"%.2f\n" % prixf)
                    vals = t2.lire().scanf("%d.%d\n")
                    if vals[0] is not None:
                        kilos = vals[0]
                    if vals[1] is not None:
                        grammes = vals[1]
                    kilos_t = qte * kilos
                    grammes_t = qte * grammes
                    if grammes_t >= 100:
                        grammes_t -= 100
                        kilos_t += 1
                    if grammes < 10:
                        final.ajouter(gencod + b";" + libelle + b";" + prix + b";" + prix2 + b";"
                                      + _p("%d;", qte) + sub
                                      + _p(";%d,0%d;%d,%d;N;", kilos, grammes * 10, kilos_t, grammes_t * 10)
                                      + infos + b"\n")
                    else:
                        final.ajouter(gencod + b";" + libelle + b";" + prix + b";" + prix2 + b";"
                                      + _p("%d;", qte) + sub
                                      + _p(";%d,%d;%d,%d;N;", kilos, grammes * 10, kilos_t, grammes_t * 10)
                                      + infos + b"\n")
                else:
                    final.ajouter(gencod + b";" + libelle + b";" + prix + b";" + prix2 + b";"
                                  + _p("%d;", qte) + sub + b";0;0;N;" + infos + b"\n")
            else:
                self.qte_totale -= 1
        self.f.pop("NEW", None)
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- 5. match_adresses
    def match_adresses(self):
        self.printf("Rajout des adresses...\n")
        donnees = self.f["final"].data or b""
        db = Flux(donnees)
        sortie = self.f["prepa1"] = Fichier()
        for _ in range(nb_lignes(donnees)):
            gencod1 = bytearray(champ(db, SEMI))
            r = Buf()
            j = 0
            r[j] = db.getc()
            while r[j] != NL and r[j] != -1:
                if r[j - 1] == SEMI and r[j] == SP:
                    j -= 1
                j += 1
                r[j] = db.getc()
            r[j] = 0
            reste1 = r.cstr()
            trouve = False
            if self.adresses.lignes:
                g = gencod1 + bytearray(b"\0" * max(0, 13 - len(gencod1)))
                if (g[0] == 48 and g[1] == 50) or (g[0] == 50 and g[1] != 48):
                    d = [g[k] - 48 for k in range(7)]
                    somme = d[0] + d[1] * 3 + d[2] + d[3] * 3 + d[4] + d[5] * 3 + d[6]
                    reste_c = abs(somme) % 10 * (-1 if somme < 0 else 1)  # % du C
                    cle = 10 - reste_c
                    g[7:12] = b"00000"
                    g[12] = (48 if cle == 10 else cle + 48) & 0xFF
                    gencod1 = bytes(g).split(b"\0")[0]
                idx = self.adresses.chercher(bytes(gencod1))
                if idx is not None:
                    adresse = _sans_cr(self.adresses.lignes[idx][1])
                    sortie.ajouter(adresse + b";" + bytes(gencod1) + b";" + reste1 + b"\n")
                    trouve = True
            if not trouve:
                idx = self.nomenclatures.chercher(bytes(gencod1))
                if idx is not None:
                    nom = _sans_cr(self.nomenclatures.lignes[idx][1])
                    sortie.ajouter(nom + b";" + bytes(gencod1) + b";" + reste1 + b"\n")
                else:
                    sortie.ajouter(b"M1-ZZ-0-0;" + bytes(gencod1) + b";" + reste1 + b"\n")
        self.f.pop("final", None)
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- chemin de preparation (mono)
    def _lignes_chemin(self):
        """Pour chaque ligne de chemin_prepa_mono.csv : (choix, no_mag, zone,
        gondole, element, nomenclature, nom_adr), lue comme le C."""
        if hasattr(self, "_chemin_cache"):
            return self._chemin_cache
        data = self.chemin_mono
        flux = Flux(data)
        lignes = []
        for _ in range(nb_lignes(data)):
            choix = flux.getc()
            no_mag = gondole = element = 0
            zone = b""
            nomenclature = b""
            if choix in (_o("M"), _o("R")):
                v = flux.scanf("%d-")
                no_mag = v[0] if v[0] is not None else 0
                v = flux.scanf("%c%c-%d-%d;")
                zone = bytes((x if x is not None else 0) & 0xFF for x in v[:2]).split(b"\0")[0]
                gondole = v[2] if v[2] is not None else 0
                element = v[3] if v[3] is not None else 0
            elif choix == _o("0"):
                nb = Buf()
                nb[0] = choix
                l = 0
                while nb[l] != SEMI and nb[l] != -1:
                    l += 1
                    nb[l] = flux.getc()
                nb[l] = 0
                nomenclature = nb.cstr()
            nom_adr = champ(flux, NL)
            lignes.append((choix, no_mag, zone, gondole, element, nomenclature, nom_adr))
        self._chemin_cache = lignes
        return lignes

    @staticmethod
    def _precision(n1, n2):
        """Profondeur de correspondance des nomenclatures (caracteres 1 a 10,
        octets nuls compris, comme les tableaux du C)."""
        def c(n, k):
            return n[k] if k < len(n) else 0
        precision = 1
        for k in range(1, 11):
            if c(n1, k) == c(n2, k):
                precision = k + 1
            else:
                break
        return precision

    # -- 6. match_position_2
    def match_position_2(self):
        self.printf("Récupération des noms de nomenclatures et d'adresses...\n")
        donnees = self.f["prepa1"].data or b""
        db = Flux(donnees)
        self.f["prepaNEW"] = Fichier()
        chemin = self._lignes_chemin()
        nb2 = len(chemin)
        for i in range(nb_lignes(donnees)):
            no_mag1 = gondole1 = element1 = 0
            zone1 = b""
            nomenclature1 = b""
            choix1 = db.getc()
            if choix1 in (_o("M"), _o("R")):
                v = db.scanf("%d-")
                no_mag1 = v[0] if v[0] is not None else 0
                if no_mag1 in (1, 2):
                    v = db.scanf("%c%c-%d-%d;")
                    element1 = v[3] if v[3] is not None else 0
                else:
                    v = db.scanf("%c%c-%d;")
                zone1 = bytes((x if x is not None else 0) & 0xFF for x in v[:2]).split(b"\0")[0]
                gondole1 = v[2] if v[2] is not None else 0
            elif choix1 == _o("0"):
                nb = Buf()
                nb[0] = choix1
                j = 0
                while nb[j] != SEMI and nb[j] != -1:
                    j += 1
                    nb[j] = db.getc()
                nb[j] = 0
                nomenclature1 = nb.cstr()
            else:
                self.printf(f"Aucune adresse ni aucune nomenclature récupérée pour la ligne {i + 2}.\n")
            gencod = champ(db, SEMI)
            reste = champ(db, NL)
            k = count = 0
            detail = nom_save_2 = 0
            while k < nb2:
                choix2, no_mag2, zone2, gondole2, element2, nomenclature2, nom_adr = chemin[k]
                if choix1 == choix2:
                    precision = 0
                    nom_save = 0
                    if choix1 in (_o("M"), _o("R")):
                        if (no_mag1 == no_mag2 and zone1[:1] == zone2[:1] and zone1[1:2] == zone2[1:2]
                                and gondole1 == gondole2 and element1 == element2):
                            if no_mag1 in (1, 2):
                                ligne = _p("%s;%d;%s;%c%d-%s-%d-%d;%s\n", gencod, k, reste, choix1,
                                           no_mag1, zone1, gondole1, element1, nom_adr)
                            else:
                                ligne = _p("%s;%d;%s;%c%d-%s-%d;%s\n", gencod, k, reste, choix1,
                                           no_mag1, zone1, gondole1, nom_adr)
                            self.f["prepaNEW"].ajouter(ligne)
                            k = nb2
                        else:
                            count += 1
                    elif choix1 == _o("0"):
                        nom_save = k
                        precision = self._precision(nomenclature1, nomenclature2)
                    else:
                        count += 1
                    if precision > detail:
                        detail = precision
                        nom_save_2 = nom_save
                else:
                    count += 1
                k += 1
            if k == count:
                replace = False
                if choix1 in (_o("M"), _o("R")):
                    replace = self.repli_nomenclature(gencod, reste)
                if replace:
                    self.printf(f"La ligne {i + 2} ({gencod.decode('latin-1')}) : adresse absente, "
                                f"produit replacé automatiquement grace a sa nomenclature.\n")
                else:
                    self.printf(f"La ligne {i + 2} ({gencod.decode('latin-1')}) a une adresse ou une "
                                f"nomenclature qui ne fait pas partie du chemin de préparation.\n")
                    if choix1 in (_o("M"), _o("R")):
                        if no_mag1 in (1, 2):
                            ligne = _p("%s;%d;%s;M%d-%s-%d-%d;ADRESSE INCONNUE;W\n", gencod, k, reste,
                                       no_mag1, zone1, gondole1, element1)
                        else:
                            ligne = _p("%s;%d;%s;M%d-%s-%d;ADRESSE INCONNUE;W\n", gencod, k, reste,
                                       no_mag1, zone1, gondole1)
                        self.f["prepaNEW"].ajouter(ligne)
                        self.printf(f"L'adresse M{no_mag1}-{zone1.decode('latin-1')}-{gondole1}-"
                                    f"{element1} ne fait pas partie du chemin de préparation.\n")
                    elif choix1 == _o("0"):
                        self.f["prepaNEW"].ajouter(
                            _p("%s;%d;%s;AUCUNE ADRESSE;AUCUNE ADRESSE;L\n", gencod, k, reste))
            if choix1 == _o("0") and k != count:
                self.recup_nom_adr(nom_save_2, gencod, reste)
        self.f.pop("prepa1", None)
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    def repli_nomenclature(self, gencod, reste):
        """Adresse hors chemin : place le produit d'apres sa nomenclature.
        (Le tampon `nomenclature` du C, declare hors de sa boucle, garde des
        restes d'une ligne precedente au-dela du \n ; la comparaison s'arrete
        toujours avant eux, ils n'ont donc aucun effet.)"""
        idx = self.nomenclatures.chercher(gencod)
        if idx is None:
            return False
        nomenclature = _sans_cr(self.nomenclatures.lignes[idx][1])
        detail = 0
        nom_save_2 = -1
        for k, (choix2, _, _, _, _, nomenclature2, _) in enumerate(self._lignes_chemin()):
            if choix2 == _o("0"):
                precision = self._precision(nomenclature, nomenclature2)
                if precision > detail:
                    detail = precision
                    nom_save_2 = k
        if detail > 0 and nom_save_2 >= 0:
            self.recup_nom_adr(nom_save_2, gencod, reste)
            return True
        return False

    def recup_nom_adr(self, idx_ligne, gencod, reste):
        data = self.chemin_mono
        flux = Flux(data)
        for i in range(nb_lignes(data)):
            lire_jusqua(flux, SEMI)
            libelle = champ(flux, NL)
            if i == idx_ligne:
                self.f["prepaNEW"].ajouter(
                    _p("%s;%d;%s;AUCUNE ADRESSE;%s\n", gencod, idx_ligne, reste, libelle))
                break

    # -- 7. rangement_produits (deux passes)
    def rangement_produits(self, passe):
        if passe == 0:
            self.printf("Rangement des articles par gencod...\n")
        else:
            self.printf("Rangement des articles dans l'ordre du chemin de préparation...\n")
        donnees = self.f["prepaNEW"].data or b""
        db = Flux(donnees)
        n = nb_lignes(donnees)
        gencods, positions, restes = [], [], []
        for _ in range(n):
            if passe == 0:
                g, j = lire_jusqua(db, SEMI)
                gencods.append(bytes(g[p] & 0xFF for p in range(j + 1)))
                v = db.scanf("%d;")
                positions.append(v[0] if v[0] is not None else 0)
            else:
                v = db.scanf("%d;")
                positions.append(v[0] if v[0] is not None else 0)
            restes.append(champ(db, NL))

        def signe(b, k):
            return _s(b[k]) if k < len(b) else 0
        for _ in range(n - 1):
            for k in range(n):
                if k == n - 1:
                    continue
                if passe == 0:
                    a, b = gencods[k], gencods[k + 1]
                    plus_grand = False
                    for c in range(13):
                        if signe(a, c) != signe(b, c):
                            plus_grand = signe(a, c) > signe(b, c)
                            break
                    if plus_grand:
                        gencods[k], gencods[k + 1] = b, a
                        positions[k], positions[k + 1] = positions[k + 1], positions[k]
                        restes[k], restes[k + 1] = restes[k + 1], restes[k]
                else:
                    if positions[k] > positions[k + 1]:
                        positions[k], positions[k + 1] = positions[k + 1], positions[k]
                        restes[k], restes[k + 1] = restes[k + 1], restes[k]
        out = Fichier()
        for d in range(n):
            if passe == 0:
                out.ajouter(_p("%d;", positions[d]) + gencods[d] + restes[d] + b"\n")
            else:
                out.ajouter(restes[d] + _p(";%d\n", positions[d]))
        self.f["prepaNEW"] = out
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- 8. ajout_DLC
    def get_dlc(self, jour, mois, annee, addj):
        nb_jours = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        jour += addj
        if 1 <= mois <= 12 and jour > nb_jours[mois - 1]:
            jour -= nb_jours[mois - 1]
            if mois <= 11:
                mois += 1
            else:
                mois = 1
                annee += 1
        self.jour2, self.mois2, self.annee2 = jour, mois, annee

    def _dlc(self, nom, jour1, mois1, annee1):
        """Nombre de jours de DLC selon la nomenclature (None = 00/00/0000)."""
        n = nom + b"\0" * 10

        def c(k, ch):
            return n[k] == ord(ch)
        if not (c(0, "0") and c(1, "2")):
            return None
        if c(2, "0") and c(3, "5") and c(4, "2") and c(5, "0"):
            return 2
        if ((c(2, "2") and c(3, "5") and ((c(4, "3") and c(5, "3")) or (c(4, "2") and c(5, "8"))))
                or (c(2, "4") and ((c(3, "0") and ((c(4, "3") and (c(5, "8") or (c(5, "9")
                    and not c(6, "1") and not c(7, "5")))) or (c(4, "4") and (c(5, "0") or c(5, "1")))))
                    or c(3, "5")))):
            return 10
        if c(2, "2") and c(3, "5") and c(4, "3") and (c(5, "0") or c(5, "1")):
            return 20
        if (c(2, "1") or c(2, "2")) and (c(3, "0") or (c(3, "5") and c(4, "3") and c(5, "2")
                                                      and c(6, "0") and c(7, "5"))):
            return 7
        if c(2, "2") and c(3, "5") and c(4, "2") and c(5, "9"):
            return 8
        if c(2, "3") and c(3, "0") and c(4, "3") and c(5, "5") and c(6, "0") and c(7, "5"):
            return 5
        if c(2, "4") and c(3, "0") and c(4, "3") and c(5, "9") and c(6, "1") and c(7, "5"):
            return 6
        if c(2, "4") and c(3, "0") and c(4, "3") and c(5, "9"):
            return 10
        if (c(2, "5") or c(2, "6")) and (c(3, "0") or c(3, "5")):
            return 4
        return None

    def ajout_dlc(self):
        self.printf("Ajout de la DLC...\n")
        donnees = self.f["prepaNEW"].data or b""
        n = nb_lignes(donnees)
        db = Flux(donnees)
        db.getc()
        count = 0
        while count < 8 and not db.eof():
            if db.getc() == SEMI:
                count += 1
        lire_jusqua(db, SP)
        v = db.scanf("%d/%d/%d -")
        jour1 = v[0] or 0
        mois1 = v[1] or 0
        annee1 = v[2] or 0
        db = Flux(donnees)
        out = Fichier()
        out.ajouter(_p("M,%d,%d,%d,%d\n", self.nb_files_def, n, self.qte_totale, self.subs_mono))
        for _ in range(n):
            gencod1 = champ(db, SEMI)
            reste1 = champ(db, NL)
            if b"\r" in reste1:
                p = reste1.index(b"\r")
                reste1 = reste1[:p] + reste1[p + 1:]
            idx = self.nomenclatures.chercher(gencod1)
            dlc = b"00/00/0000"
            if idx is not None:
                jours = self._dlc(self.nomenclatures.lignes[idx][1], jour1, mois1, annee1)
                if jours is not None:
                    self.get_dlc(jour1, mois1, annee1, jours)
                    dlc = _p("%02d/%02d/%d", self.jour2, self.mois2, self.annee2)
            out.ajouter(gencod1 + b";" + reste1 + b";" + dlc + b"\n")
        self.f.pop("prepaNEW", None)
        self.bon_prepa = out.data
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- 9. crea_anticipation
    def crea_anticipation(self):
        self.printf("Création du bon d'anticipation...\n")
        donnees = self.bon_prepa or b""
        db = Flux(donnees)
        lire_jusqua(db, NL)
        out = Fichier()
        for _ in range(nb_lignes(donnees) - 1):
            gencod1 = champ(db, SEMI)
            reste = champ(db, NL)
            drive = any(reste[k - 3:k + 1] == b";R1-" for k in range(3, len(reste)))
            deja_classe = 0
            compteur = l = 0
            if not drive:
                if b";M2-JJ-5-1;" in reste:
                    out.ajouter(gencod1 + b";" + reste + b";G\n")
                    deja_classe = 1
                else:
                    idx = self.nomenclatures.chercher(gencod1)
                    if idx is None:
                        compteur = l = len(self.nomenclatures.lignes)
                    else:
                        compteur, l = idx, len(self.nomenclatures.lignes) + 1
                        nom = self.nomenclatures.lignes[idx][1] + b"\0" * 6
                        g = gencod1 + b"\0" * 13
                        lettre = None
                        if nom[0] == 48 and nom[1] in (51, 52):
                            lettre = b"A"
                        elif nom[:4] == b"0260":
                            lettre = b"B"
                        elif ((nom[:4] == b"0205" and g[:6] == b"200000") or gencod1 == b"3486850001645"
                              or g[:6] == b"200000" or gencod1 == b"3289664281803"):
                            lettre = b"C"
                        elif nom[:5] == b"02655" and nom[5] in (49, 50):
                            lettre = b"D"
                        elif nom[:4] == b"0220":
                            lettre = b"F"
                        if lettre:
                            out.ajouter(gencod1 + b";" + reste + b";" + lettre + b"\n")
            if deja_classe == 0 and compteur == l:
                g = gencod1 + b"\0" * 13
                if g[:7] == b"2000000" or gencod1 == b"3289664281803":
                    out.ajouter(gencod1 + b";" + reste + b";C\n")
        self.bon_anticipation = out.data
        self.printf("\t\t\t\t\t\t\t\tTerminé.\n")

    # -- main
    def executer(self, tables=None):
        """`tables` : resultat de charger_tables(), pour enchainer plusieurs
        bons sans relire les CSV (comparaison C / Python)."""
        tables = tables or charger_tables(self.dossier)
        self.adresses, self.nomenclatures, self.chemin_mono = tables
        for nom in ("bon_prepa.txt", "bon_anticipation.txt"):
            if os.path.exists(self.chemin(nom)):
                os.remove(self.chemin(nom))
        self.change_format_fichier()
        self.test_bon_encaissement()
        self.rewrite_bon_encaissement_02()
        self.match_adresses()
        self.match_position_2()
        self.rangement_produits(0)
        self.rangement_produits(1)
        self.ajout_dlc()
        with open(self.chemin("bon_prepa.txt"), "wb") as fh:
            fh.write(self.bon_prepa or b"")
        self.crea_anticipation()
        if self.bon_anticipation:
            with open(self.chemin("bon_anticipation.txt"), "wb") as fh:
                fh.write(self.bon_anticipation)
        self.printf("\n\nProgramme terminé.\n")


def charger_tables(dossier):
    def lire(nom):
        try:
            with open(os.path.join(dossier, nom), "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return b""
    return (TableGencods(lire("gencod_adresses.csv")),
            TableGencods(lire("gencod_nomenclatures.csv")),
            lire("chemin_prepa_mono.csv"))


def main():
    Moteur(".").executer()


if __name__ == "__main__":
    main()
