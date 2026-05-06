#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <wchar.h>

#ifndef __fct_prepa_drive_degrade_h__
#define __fct_prepa_drive_degrade_h__

/** La fonction change_format_fichier() permet de passer d'un fichier PDF en un fichier TXT. */
void change_format_fichier();

/** La fonction test_bon_encaissement() permet de trier les informations du PDF pour en extraire que les infos utiles. */
void test_bon_encaissement();

/** La fonction rewrite_bon_encaissement_sgp() permet de trier les informations du PDF pour en extraire que les infos utiles pour les bons sans gestion produit */
void rewrite_bon_encaissement_sgp();

/** La fonction rewrite_bon_encaissement_agp() permet de trier les informations du PDF pour en extraire que les infos utiles pour les bons avec gestion produit */
void rewrite_bon_encaissement_agp();

/** La fonction rewrite_bon_encaissement_02() permet réécrire le fichier d'une manière plus lisible par l'utilisateur. */
void rewrite_bon_encaissement_02();

/** La fonction add_files() permet d'ajouter les données des autres bon de commande. */
void add_files();

/** La fonction match_adresses() permet de rapprocher chaque ligne de produit avec son adresse et de l'ajouter dans les infos fournies au préparateur. */
void match_adresses();

/** La fonction recup_nom_adr() permet d'aller chercher le nom de la nomenclature. */
void recup_nom_adr(int ligne_nomenclature_save_2, char gencod_2[20], char reste_2[500]);

/** La fonction match_position() permet d'associer à chaque ligne la position dans laquelle il se trouve au niveau du chemin de préparation. */
void match_position();

/** La fonction match_position_2() permet d'associer à chaque ligne la position dans laquelle il se trouve au niveau du chemin de préparation. */
void match_position_2();

/** La fonction rangement_produits() permet de trier les produits pour qu'ils soient rangés dans l'ordre du chemin de préparation. */
void rangement_produits();

/** La fonction ajout_DLC() permet d'ajouter à chaque fin de ligne la DLC à respecter par le préparateur lors de la collecte. */
void ajout_DLC();

/** La fonction get_DLC() permet de faire la conversion entre la date de la commande et de la date à respecter. */
void get_DLC(int jour, int mois, int annee, int addj);

/** La fonction inverse_data() permet d'inverser les données contenues dans les deux premières colones. */
void inverse_data();

/** La fonction assemble_produits_plusieurs_clients() permet d'aggréger les produits qui sont commandés par plusieurs clients en ramasse. */
void assemble_produits_plusieurs_clients();

/** La fonction assemble_tri_commandes() permet d'assembler les données des commandes dans un seul fichier afin qu'il soit traité par la suite. */
void assemble_tri_commandes();

/** La focntion tri_commandes() permet de trier les commandes en fonction de l'heure de retrait et du nombre de produits afin de pouvoir les afficher en numéro de vague dans Android Studio. */
void tri_commandes();

/** La focntion crea_anticipation() permet de générer un bon d'anticipation pour les produits anticipables. */
void crea_anticipation();

/** La fonction recup_no_commandes() permet de récupérer les numéros de commande dans l'ordre dans lequel ils ont été écrits. */
void recup_no_commandes();

#endif
