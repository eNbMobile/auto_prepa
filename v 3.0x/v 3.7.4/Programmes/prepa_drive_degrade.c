#include "fct_prepa_drive_degrade.h"

// Dernière modification 2025/04/28
// v3.7.4 : Anticipation : ajout de toutes les familles anticipées qui apparaissent sur le même bon d'anticipation
//          + Corrections mineures : - sur certaines commandes, le client n'a pas choisi les sacs
//                                   - certains gencod PV étaient décalés vers la gauche de 1 à tort

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
