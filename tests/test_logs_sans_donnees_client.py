"""Le depot est public, ses logs GitHub Actions aussi : aucun print ne doit
afficher le nom, le prenom ou l'email d'un client (ni un destinataire).
Les messages ne citent que le n° de commande."""
import ast
import glob
import os
import re
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERDITS = re.compile(
    r"^(nom|prenom|prénom|nom_complet|nom_val|prenom_val|nom_up|prenom_up|civilite|"
    r"client|destinataire|destinataire_2|destinataire_cc|email|EMAIL_DESTINATAIRE|"
    r"EMAIL_COPIE_STOCK|EMAIL_ANTICIPATION|EMAIL_ANTICIPATION_2)$")
# Fichiers ou `nom` designe un nom de fichier Drive, jamais une personne.
NOM_FICHIER = {"adresses_inconnues.py", "controle_stocks.py",
               "upload_config.py", "auto_prepa.py"}


class TestLogsSansDonneesClient(unittest.TestCase):
    def test_aucun_print_ne_cite_une_personne(self):
        fautes = []
        for chemin in glob.glob(os.path.join(RACINE, "*.py")):
            fichier = os.path.basename(chemin)
            with open(chemin, encoding="utf-8") as fh:
                arbre = ast.parse(fh.read())
            for noeud in ast.walk(arbre):
                if not (isinstance(noeud, ast.Call) and getattr(noeud.func, "id", None) == "print"):
                    continue
                for arg in noeud.args:
                    for n in ast.walk(arg):
                        nom = n.id if isinstance(n, ast.Name) else (
                            n.attr if isinstance(n, ast.Attribute) else None)
                        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                                and n.slice.value in ("nom", "prenom")):
                            nom = n.slice.value
                        if nom and INTERDITS.match(nom):
                            if nom == "nom" and fichier in NOM_FICHIER:
                                continue
                            fautes.append(f"{fichier}:{noeud.lineno} ({nom})")
        self.assertEqual(fautes, [], "print avec donnee personnelle : " + ", ".join(fautes))


if __name__ == "__main__":
    unittest.main()
