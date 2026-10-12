#include "fct_prepa_drive_degrade.h"

// Dernière modification 2025/05/06
// v4.0.0 : Ajout de plusieurs fonctionalités générées par IA
//        + Correction d'un filtre qui faisait disapraitre les produits dont le premier chiffre était un 9

int main()
{
	change_format_fichier();
	test_bon_encaissement();
	rewrite_bon_encaissement_02();
	match_adresses();
	match_position_2();
	rangement_produits();
	rangement_produits();
    ajout_DLC();
    crea_anticipation();
	printf("\n\nProgramme terminé.\n");
	return 0;
}
