from datetime import date

import jours_fermes as jf

FERMES = {date(2026, 11, 11), date(2027, 5, 1), date(2027, 3, 29)}


def test_lendemain_jour_ferie_remonte_a_la_veille():
    # jeudi 12/11/2026, mercredi 11/11 férié → ventes du mardi 10/11
    assert jf.dernier_jour_ventes(date(2026, 11, 12), FERMES) == date(2026, 11, 10)


def test_jour_normal_prend_hier():
    assert jf.dernier_jour_ventes(date(2026, 11, 13), FERMES) == date(2026, 11, 12)


def test_lundi_prend_samedi():
    assert jf.dernier_jour_ventes(date(2026, 11, 16), FERMES) == date(2026, 11, 14)


def test_lundi_apres_samedi_ferie_prend_vendredi():
    assert jf.dernier_jour_ventes(date(2027, 5, 3), FERMES) == date(2027, 4, 30)


def test_mardi_apres_lundi_ferie_prend_samedi():
    assert jf.dernier_jour_ventes(date(2027, 3, 30), FERMES) == date(2027, 3, 27)


def test_fichier_reel_lisible():
    jours = jf.charger_jours_fermes()
    assert date(2026, 11, 11) in jours
    assert jf.est_ferme(date(2026, 11, 15), jours)  # dimanche
