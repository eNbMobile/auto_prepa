#include <stdlib.h>  
#include <stdio.h>  
#include <string.h>  
#include <unistd.h>  
#include <wchar.h>  
  
#ifndef __fct_prepa_drive_degrade_h__  
#define __fct_prepa_drive_degrade_h__  
  
int gencod_correspond(char *gencod_produit, char *gencod_ref);
void change_format_fichier();
void test_bon_encaissement();
void rewrite_bon_encaissement_sgp();  
void rewrite_bon_encaissement_agp();  
void rewrite_bon_encaissement_02();  
void add_files();  
void match_adresses();  
void recup_nom_adr(int ligne_nomenclature_save_2, char gencod_2[20], char reste_2[500]);  
int repli_nomenclature(char gencod_2[20], char reste_2[500]);  
void match_position();  
void match_position_2();  
void rangement_produits();  
void ajout_DLC();  
void get_DLC(int jour, int mois, int annee, int addj);  
void inverse_data();  
void assemble_produits_plusieurs_clients();  
void assemble_tri_commandes();  
void tri_commandes();  
void crea_anticipation();  
void recup_no_commandes();  
  
#endif  
