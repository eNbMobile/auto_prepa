#include "fct_prepa_drive_degrade.h"

int premiere_ligne=0, qte_totale=0, jour2=0, mois2=0, annee2=0, nb_files=0, count=0, nb_files_def=0, count2=0, subs_mono=0;

void change_format_fichier()
{
	printf("Conversion du fichier...\n");
	system ("ls -lR | grep \\.pdf$ > tmp");
	FILE* tmp =  NULL;
	if (nb_files == 0)
	{
		remove("bon_prepa.txt");
		system("wc -l tmp > tmp2");
		tmp = fopen("tmp2", "r");
		fscanf(tmp, "%d", &nb_files);
		nb_files_def=nb_files;
		fclose(tmp);
		remove("tmp2");
	}
	tmp = fopen("tmp", "r");
	int j=0, pass=0;
	char cde[100]={0}, shell1[100]="mv BonDeCommande_", cdee2[100]=".pdf ./bon_encaissement.pdf";
	FILE* newTMP = NULL;
	newTMP = fopen("tmp_NEW", "a");
	cde[j] = getc(tmp);
	FILE* tri_cde = NULL;
	tri_cde = fopen("tri_cde.txt", "a");
	while (cde[j] != '\n')
	{
		j++;
		cde[j] = getc(tmp);
		if ((cde[j-5] == 'a' && cde[j-4] == 'n' && cde[j-3] == 'd' && cde[j-2] == 'e' && cde[j-1] == '_') || (pass >= 1 && pass <= 7))
		{
			fprintf(newTMP, "%c", cde[j]);
			shell1[17+pass] = cde[j];
			fprintf(tri_cde, "%c", cde[j]);
			pass++;
		}
	}
	fprintf(newTMP, "\n");
	fprintf(tri_cde, "\n");
	fclose(tri_cde);
	for (int a=0; a<28; a++) shell1[25+a] = cdee2[a];
	if (nb_files != 0)
	{
		system(shell1);
		system("pdftotext -layout bon_encaissement.pdf bon_encaissement.csv");
		remove("bon_encaissement.pdf");
	}
	else printf("Impossible de déterminer le nombre de fichier à incrémenter.\n");
	fclose(newTMP);
	remove("tmp_NEW");
	fclose(tmp);
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void test_bon_encaissement() // Tester les infos du fichier pour voir si le bon traité est un bon avec ou sans substitution au produit
{
	printf("Test du fichier...\n");
	FILE* database = NULL;
	database = fopen("bon_encaissement.csv", "r");
	system("wc -l bon_encaissement.csv > tmp");
	FILE* tmp = NULL;
	tmp= fopen("tmp", "r");
	int nbLignes=0, i=0, sub=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		char pbl[200]={0};
		int j=0;
		pbl[j] = getc(database);
		while (pbl[j] != '\n')
		{
			j++;
			pbl[j] = getc(database);
			if (pbl[j-6] == 'S' && pbl[j-5] == 'U' && pbl[j-4] == 'B' && pbl[j-3] == 'S' && pbl[j-2] == 'T' && pbl[j-1] == 'I' && pbl[j] == '.') sub=1;
		}
		i++;
	}
	fclose(database);
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
	if (sub == 0) rewrite_bon_encaissement_sgp();
	else if (sub == 1) rewrite_bon_encaissement_agp();
	else printf("Problème de définition de la gestion de la substitution au produit.\n");
}

void rewrite_bon_encaissement_sgp() // Ajouter les informations du client (n° de commande, prénom, nom, heure, date)
{
	printf("Réécriture du fichier SGP...\n");
	//Ce SP va permettre de lire et de récupérer les informations contenues dans le fichier PDF.
	FILE* database = NULL;
	database = fopen("bon_encaissement.csv", "r");
	system("wc -l bon_encaissement.csv > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0, save=0, type=0, recup_lib=0, i_lib=0, subs=0, offre=0, lib3=0, lib_maison=0, sacs=0;
	char type_retrait[15]={0};
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	FILE* newDB = NULL;
	newDB = fopen("bon_encaissement_NEW.csv", "a");
	while (i < nbLignes)
	{
		int j=0, gen=0, compte=0;
		char ligne[500]={0}, pass=0, passe=0;
		if (save == 1) save=2;
		ligne[j] = getc(database);
		if (i == 36 && sacs == 0)
		{
			FILE* baseClient = NULL;
			baseClient = fopen("base_client.txt", "a");
			fprintf(baseClient, ",Pas de sacs\n");
			fclose(baseClient);
			sacs=1;
		}
		while (ligne[j] != '\n')
		{
			j++;
			ligne[j] = getc(database);
			if (i < 6 && ligne[j-7] == '/' && ligne[j-4] == '/') // C'est pour récupérer la date
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				if (ligne[j-18] != ' ') fprintf(baseClient, "%c", ligne[j-18]);
				if (ligne[j-17] != ' ') fprintf(baseClient, "%c", ligne[j-17]);
				if (ligne[j-16] != ' ') fprintf(baseClient, "%c", ligne[j-16]);
				if (ligne[j-15] != ' ') fprintf(baseClient, "%c", ligne[j-15]);
				if (ligne[j-14] != ' ') fprintf(baseClient, "%c", ligne[j-14]);
				if (ligne[j-13] != ' ') fprintf(baseClient, "%c", ligne[j-13]);
				if (ligne[j-12] != ' ') fprintf(baseClient, "%c", ligne[j-12]);
				if (ligne[j-11] != ' ') fprintf(baseClient, "%c", ligne[j-11]);
				fprintf(baseClient, "%c", ligne[j-10]);
				fprintf(baseClient, "%c", ligne[j-9]);
				fprintf(baseClient, "%c", ligne[j-8]);
				fprintf(baseClient, "%c", ligne[j-7]);
				fprintf(baseClient, "%c", ligne[j-6]);
				fprintf(baseClient, "%c", ligne[j-5]);
				fprintf(baseClient, "%c", ligne[j-4]);
				fprintf(baseClient, "%c", ligne[j-3]);
				fprintf(baseClient, "%c", ligne[j-2]);
				fprintf(baseClient, "%c", ligne[j-1]);
				fprintf(baseClient, "%c", ligne[j]);
				fprintf(baseClient, " - ");
				fclose(baseClient);
			}
			if (i < 8 && ligne [j-10] == 'h' && ligne[j-6] == '-' && ligne[j-2] == 'h') //Écris l'heure
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				fprintf(baseClient, "%c%c%c%c%c%c%c%c%c%c%c,", ligne[j-12], ligne[j-11], ligne[j-10],  ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-4], ligne[j-3], ligne[j-2], ligne[j-1], ligne[j]); //Récupère l'heure
				fclose(baseClient);
				FILE* tri_heures = NULL;
				tri_heures =  fopen("tri_heures.txt", "a");
				fprintf(tri_heures, "%c%c%c%c%c\n", ligne[j-12], ligne[j-11], ligne[j-10],  ligne[j-9], ligne[j-8]);
				fclose(tri_heures);
			}
			if (i < 10 && ligne[j-18] == 'C' && ligne[j-17] == 'o' && ligne[j-11] == 'e' && ligne [j-9] == ':') // Récupère le numéro de la commande
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				if (ligne[j-7] != ' ') fprintf(baseClient, "%c", ligne[j-7]);
				if (ligne[j-6] != ' ') fprintf(baseClient, "%c", ligne[j-6]);
				if (ligne[j-5] != ' ') fprintf(baseClient, "%c", ligne[j-5]);
				if (ligne[j-4] != ' ') fprintf(baseClient, "%c", ligne[j-4]);
				if (ligne[j-3] != ' ') fprintf(baseClient, "%c", ligne[j-3]);
				if (ligne[j-2] != ' ') fprintf(baseClient, "%c", ligne[j-2]);
				if (ligne[j-1] != ' ') fprintf(baseClient, "%c", ligne[j-1]);
				if (ligne[j] != ' ') fprintf(baseClient, "%c", ligne[j]);
				fprintf(baseClient, ",");
				fclose(baseClient);
			}
			if (i == 8 && (ligne[0] == 'R' || ligne[0] == 'L' || ligne[0] == 'P') && type == 0) // Récupère les informations sur la commande: type de retrait, type de paiement
			{
				char type_paiement[100]={0}, pbl[100]={0};
                	if (ligne[0] == 'R')
                	{
              		type_retrait[0] = 'R';
					type_retrait[1] = 'e';
			     	type_retrait[2] = 't';
			      	type_retrait[3] = 'r';
			      	type_retrait[4] = 'a';
			      	type_retrait[5] = 'i';
			      	type_retrait[6] = 't';
			      	type_retrait[7] = '\0';
                }
              	else if (ligne[0] == 'L')
                {
                	type_retrait[0] = 'L';
                      type_retrait[1] = 'i';
                      type_retrait[2] = 'v';
                      type_retrait[3] = 'r';
                      type_retrait[4] = 'a';
                      type_retrait[5] = 'i';
                      type_retrait[6] = 's';
                      type_retrait[7] = 'o';
                      type_retrait[8] = 'n';
                      type_retrait[9] = '\0';
                }
                else if (ligne[0] == 'P')
                {
                      type_retrait[0] = 'P';
                      type_retrait[1] = 'o';
                      type_retrait[2] = 'i';
                      type_retrait[3] = 'n';
                      type_retrait[4] = 't';
                      type_retrait[5] = ' ';
                      type_retrait[6] = 'r';
                      type_retrait[7] = 'e';
                      type_retrait[8] = 'l';
                      type_retrait[9] = 'a';
                      type_retrait[10] = 'i';
                      type_retrait[11] = 's';
                      type_retrait[12] = '\0';
                }
                else printf("Problème de définition du type de retrait.\n");
				int a=1;
                                pbl[a-1] = getc(database);
                                pbl[a] = getc(database);
				while (pbl[a] != 'P')
				{
					a++;
					pbl[a] = getc(database);
				}
                                type_paiement[0] = pbl[a];
				type_paiement[1] = getc(database);
				a=1;
				while (type_paiement[a] != '\n')
				{
					a++;
					type_paiement[a] = getc(database);
				}
				type_paiement[a] = '\0';
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				fprintf(baseClient, "%s,%s,", type_retrait, type_paiement);
				fclose(baseClient);
				ligne[j] = '\n';
				type=1;
			}
			if (i < 15 && i > 9 && ligne[j-50] == 'M'  && (ligne[j-49] == '.' || ligne[j-49] == 'm') && pass == 0) //Récupère le nom du client (jusqu'à 50 caractères)
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				if ((ligne[j-50] != ' ' && ligne[j-49] != ' ') || (ligne[j-50] != ' ' && ligne[j-49] == ' ') || (ligne[j-50] == ' ' && ligne[j-49] != ' ')) fprintf(baseClient, "%c", ligne[j-50]);
				if ((ligne[j-49] != ' ' && ligne[j-48] != ' ') || (ligne[j-49] != ' ' && ligne[j-48] == ' ') || (ligne[j-49] == ' ' && ligne[j-48] != ' ')) fprintf(baseClient, "%c", ligne[j-49]);
				if ((ligne[j-48] != ' ' && ligne[j-47] != ' ') || (ligne[j-48] != ' ' && ligne[j-47] == ' ') || (ligne[j-48] == ' ' && ligne[j-47] != ' ')) fprintf(baseClient, "%c", ligne[j-48]);
				if ((ligne[j-47] != ' ' && ligne[j-46] != ' ') || (ligne[j-47] != ' ' && ligne[j-46] == ' ') || (ligne[j-47] == ' ' && ligne[j-46] != ' ')) fprintf(baseClient, "%c", ligne[j-47]);
				if ((ligne[j-46] != ' ' && ligne[j-45] != ' ') || (ligne[j-46] != ' ' && ligne[j-45] == ' ') || (ligne[j-46] == ' ' && ligne[j-45] != ' ')) fprintf(baseClient, "%c", ligne[j-46]);
				if ((ligne[j-45] != ' ' && ligne[j-44] != ' ') || (ligne[j-45] != ' ' && ligne[j-44] == ' ') || (ligne[j-45] == ' ' && ligne[j-44] != ' ')) fprintf(baseClient, "%c", ligne[j-45]);
				if ((ligne[j-44] != ' ' && ligne[j-43] != ' ') || (ligne[j-44] != ' ' && ligne[j-43] == ' ') || (ligne[j-44] == ' ' && ligne[j-43] != ' ')) fprintf(baseClient, "%c", ligne[j-44]);
				if ((ligne[j-43] != ' ' && ligne[j-42] != ' ') || (ligne[j-43] != ' ' && ligne[j-42] == ' ') || (ligne[j-43] == ' ' && ligne[j-42] != ' ')) fprintf(baseClient, "%c", ligne[j-43]);
				if ((ligne[j-42] != ' ' && ligne[j-41] != ' ') || (ligne[j-42] != ' ' && ligne[j-41] == ' ') || (ligne[j-42] == ' ' && ligne[j-41] != ' ')) fprintf(baseClient, "%c", ligne[j-42]);
				if ((ligne[j-41] != ' ' && ligne[j-40] != ' ') || (ligne[j-41] != ' ' && ligne[j-40] == ' ') || (ligne[j-41] == ' ' && ligne[j-40] != ' ')) fprintf(baseClient, "%c", ligne[j-41]);
				if ((ligne[j-40] != ' ' && ligne[j-39] != ' ') || (ligne[j-40] != ' ' && ligne[j-39] == ' ') || (ligne[j-40] == ' ' && ligne[j-39] != ' ')) fprintf(baseClient, "%c", ligne[j-40]);
				if ((ligne[j-39] != ' ' && ligne[j-38] != ' ') || (ligne[j-39] != ' ' && ligne[j-38] == ' ') || (ligne[j-39] == ' ' && ligne[j-38] != ' ')) fprintf(baseClient, "%c", ligne[j-39]);
				if ((ligne[j-38] != ' ' && ligne[j-37] != ' ') || (ligne[j-38] != ' ' && ligne[j-37] == ' ') || (ligne[j-38] == ' ' && ligne[j-37] != ' ')) fprintf(baseClient, "%c", ligne[j-38]);
				if ((ligne[j-37] != ' ' && ligne[j-36] != ' ') || (ligne[j-37] != ' ' && ligne[j-36] == ' ') || (ligne[j-37] == ' ' && ligne[j-36] != ' ')) fprintf(baseClient, "%c", ligne[j-37]);
				if ((ligne[j-36] != ' ' && ligne[j-35] != ' ') || (ligne[j-36] != ' ' && ligne[j-35] == ' ') || (ligne[j-36] == ' ' && ligne[j-35] != ' ')) fprintf(baseClient, "%c", ligne[j-36]);
				if ((ligne[j-35] != ' ' && ligne[j-34] != ' ') || (ligne[j-35] != ' ' && ligne[j-34] == ' ') || (ligne[j-35] == ' ' && ligne[j-34] != ' ')) fprintf(baseClient, "%c", ligne[j-35]);
				if ((ligne[j-34] != ' ' && ligne[j-33] != ' ') || (ligne[j-34] != ' ' && ligne[j-33] == ' ') || (ligne[j-34] == ' ' && ligne[j-33] != ' ')) fprintf(baseClient, "%c", ligne[j-34]);
				if ((ligne[j-33] != ' ' && ligne[j-32] != ' ') || (ligne[j-33] != ' ' && ligne[j-32] == ' ') || (ligne[j-33] == ' ' && ligne[j-32] != ' ')) fprintf(baseClient, "%c", ligne[j-33]);
				if ((ligne[j-32] != ' ' && ligne[j-31] != ' ') || (ligne[j-32] != ' ' && ligne[j-31] == ' ') || (ligne[j-32] == ' ' && ligne[j-31] != ' ')) fprintf(baseClient, "%c", ligne[j-32]);
				if ((ligne[j-31] != ' ' && ligne[j-30] != ' ') || (ligne[j-31] != ' ' && ligne[j-30] == ' ') || (ligne[j-31] == ' ' && ligne[j-30] != ' ')) fprintf(baseClient, "%c", ligne[j-31]);
				if ((ligne[j-30] != ' ' && ligne[j-29] != ' ') || (ligne[j-30] != ' ' && ligne[j-29] == ' ') || (ligne[j-30] == ' ' && ligne[j-29] != ' ')) fprintf(baseClient, "%c", ligne[j-30]);
				if ((ligne[j-29] != ' ' && ligne[j-28] != ' ') || (ligne[j-29] != ' ' && ligne[j-28] == ' ') || (ligne[j-29] == ' ' && ligne[j-28] != ' ')) fprintf(baseClient, "%c", ligne[j-29]);
				if ((ligne[j-28] != ' ' && ligne[j-27] != ' ') || (ligne[j-28] != ' ' && ligne[j-27] == ' ') || (ligne[j-28] == ' ' && ligne[j-27] != ' ')) fprintf(baseClient, "%c", ligne[j-28]);
				if ((ligne[j-27] != ' ' && ligne[j-26] != ' ') || (ligne[j-27] != ' ' && ligne[j-26] == ' ') || (ligne[j-27] == ' ' && ligne[j-26] != ' ')) fprintf(baseClient, "%c", ligne[j-27]);
				if ((ligne[j-26] != ' ' && ligne[j-25] != ' ') || (ligne[j-26] != ' ' && ligne[j-25] == ' ') || (ligne[j-26] == ' ' && ligne[j-25] != ' ')) fprintf(baseClient, "%c", ligne[j-26]);
				if ((ligne[j-25] != ' ' && ligne[j-24] != ' ') || (ligne[j-25] != ' ' && ligne[j-24] == ' ') || (ligne[j-25] == ' ' && ligne[j-24] != ' ')) fprintf(baseClient, "%c", ligne[j-25]);
				if ((ligne[j-24] != ' ' && ligne[j-23] != ' ') || (ligne[j-24] != ' ' && ligne[j-23] == ' ') || (ligne[j-24] == ' ' && ligne[j-23] != ' ')) fprintf(baseClient, "%c", ligne[j-24]);
				if ((ligne[j-23] != ' ' && ligne[j-22] != ' ') || (ligne[j-23] != ' ' && ligne[j-22] == ' ') || (ligne[j-23] == ' ' && ligne[j-22] != ' ')) fprintf(baseClient, "%c", ligne[j-23]);
				if ((ligne[j-22] != ' ' && ligne[j-21] != ' ') || (ligne[j-22] != ' ' && ligne[j-21] == ' ') || (ligne[j-22] == ' ' && ligne[j-21] != ' ')) fprintf(baseClient, "%c", ligne[j-22]);
				if ((ligne[j-21] != ' ' && ligne[j-20] != ' ') || (ligne[j-21] != ' ' && ligne[j-20] == ' ') || (ligne[j-21] == ' ' && ligne[j-20] != ' ')) fprintf(baseClient, "%c", ligne[j-21]);
				if ((ligne[j-20] != ' ' && ligne[j-19] != ' ') || (ligne[j-20] != ' ' && ligne[j-19] == ' ') || (ligne[j-20] == ' ' && ligne[j-19] != ' ')) fprintf(baseClient, "%c", ligne[j-20]);
				if ((ligne[j-19] != ' ' && ligne[j-18] != ' ') || (ligne[j-19] != ' ' && ligne[j-18] == ' ') || (ligne[j-19] == ' ' && ligne[j-18] != ' ')) fprintf(baseClient, "%c", ligne[j-19]);
				if ((ligne[j-18] != ' ' && ligne[j-17] != ' ') || (ligne[j-18] != ' ' && ligne[j-17] == ' ') || (ligne[j-18] == ' ' && ligne[j-17] != ' ')) fprintf(baseClient, "%c", ligne[j-18]);
				if ((ligne[j-17] != ' ' && ligne[j-16] != ' ') || (ligne[j-17] != ' ' && ligne[j-16] == ' ') || (ligne[j-17] == ' ' && ligne[j-16] != ' ')) fprintf(baseClient, "%c", ligne[j-17]);
				if ((ligne[j-16] != ' ' && ligne[j-15] != ' ') || (ligne[j-16] != ' ' && ligne[j-15] == ' ') || (ligne[j-16] == ' ' && ligne[j-15] != ' ')) fprintf(baseClient, "%c", ligne[j-16]);
				if ((ligne[j-15] != ' ' && ligne[j-14] != ' ') || (ligne[j-15] != ' ' && ligne[j-14] == ' ') || (ligne[j-15] == ' ' && ligne[j-14] != ' ')) fprintf(baseClient, "%c", ligne[j-15]);
				if ((ligne[j-14] != ' ' && ligne[j-13] != ' ') || (ligne[j-14] != ' ' && ligne[j-13] == ' ') || (ligne[j-14] == ' ' && ligne[j-13] != ' ')) fprintf(baseClient, "%c", ligne[j-14]);
				if ((ligne[j-13] != ' ' && ligne[j-12] != ' ') || (ligne[j-13] != ' ' && ligne[j-12] == ' ') || (ligne[j-13] == ' ' && ligne[j-12] != ' ')) fprintf(baseClient, "%c", ligne[j-13]);
				if ((ligne[j-12] != ' ' && ligne[j-11] != ' ') || (ligne[j-12] != ' ' && ligne[j-11] == ' ') || (ligne[j-12] == ' ' && ligne[j-11] != ' ')) fprintf(baseClient, "%c", ligne[j-12]);
				if ((ligne[j-11] != ' ' && ligne[j-10] != ' ') || (ligne[j-11] != ' ' && ligne[j-10] == ' ') || (ligne[j-11] == ' ' && ligne[j-10] != ' ')) fprintf(baseClient, "%c", ligne[j-11]);
				if ((ligne[j-10] != ' ' && ligne[j-9] != ' ') || (ligne[j-10] != ' ' && ligne[j-9] == ' ') || (ligne[j-10] == ' ' && ligne[j-9] != ' ')) fprintf(baseClient, "%c", ligne[j-10]);
				pass=1;
				fclose(baseClient);
			}
			if ((type_retrait[0] == 'L' || type_retrait[0] == 'P') && pass == 1 && ligne[j] == '\n') {FILE* baseClient = NULL;baseClient = fopen("base_client.txt", "a");fprintf(baseClient, ",Sac(s) facturé(s)\n");pass=2;fclose(baseClient);}
			if (i < 35 && ligne[j-6] == 'i' && ligne[j-5] == 'o' && ligne[j-4] == 'n' && ligne[j-2] == '>') // Lis si le client accepte ou non la substitution
			{
				if (ligne[j] == 'R') subs=0;
				if (ligne[j] == 'A') subs=1;
			}
			if (ligne[j-10] == 'P' && ligne[j-9] == 'a' && ligne[j-8] == 's' && ligne[j-7] == ' ' && ligne[j-6] == 'd' && ligne[j-5] == 'e' && ligne[j-4] == ' ' && ligne[j-3] == 's' && ligne[j-2] == 'a' && ligne[j-1] == 'c' && ligne[j] == 's') {FILE* baseClient = NULL;baseClient = fopen("base_client.txt", "a");fprintf(baseClient, ",Pas de sacs\n");fclose(baseClient);sacs=1;}
			if (ligne[j-7] == 'S' && ligne[j-6] == 'a' && ligne[j-5] == 'c' && ligne[j-4] == '(' && ligne[j-3] == 's' && ligne[j-2] == ')' && ligne[j-1] == ' ' && ligne[j] == 'f')
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				fprintf(baseClient, ",Sac(s) facturé(s)\n");
				fclose(baseClient);
				sacs=1;
			}
			if (i == 36 && sacs == 0)
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				fprintf(baseClient, ",Pas de sacs\n");
				fclose(baseClient);
				sacs=1;
			}
			if (ligne[j-13] == 'S' && ligne[j-12] == 'u' && ligne[j-11] == 'r' && ligne[j-10] == 'g' && ligne[j-9] == 'e' && ligne[j-8] == 'l' && ligne[j-7] == -61 && ligne[j-6] == -87 && ligne[j-5] == ' ' && ligne[j-4] == '>' && ligne[j-3] == ' ')
			{
				if (ligne[j-2] == 'O' && ligne[j-1] == 'U' && ligne[j] == 'I') subs_mono=1;
				else if (ligne[j-2] == 'N' && ligne[j-1] == 'O' && ligne[j] == 'N') subs_mono=0;
			}
			if (recup_lib == 42 && i_lib < i)
			{
				if (ligne[j-6] == ' ' && ligne[j-5] == -30 && ligne[j-4] == -126 && ligne[j-3] == -84 && ligne[j-2] == '/')
				{
					if (ligne[j-1] == 'K' && ligne[j] == 'G') fprintf(newDB, "O;");
					else fprintf(newDB, "N;");
					if (ligne[j-12] == ' ') // Ne contient pas de centaine
					{
						if (ligne[j-11] == ' ') fprintf(newDB, "%c.%c%c;", ligne[j-10], ligne[j-8], ligne[j-7]);
						else fprintf(newDB, "%c%c.%c%c;", ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
					}
					else fprintf(newDB, "%c%c%c.%c%c;", ligne[j-12], ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
					FILE* baseClient2 = NULL;
					baseClient2 = fopen("base_client.txt", "r");
					int d=0;
					char bc[200]={0};
					bc[d] = getc(baseClient2);
					while (bc[d] != '\n')
					{
						d++;
						bc[d] = getc(baseClient2);
					}
					bc[d] = '\0';
					fclose(baseClient2);
					if (subs == 1) fprintf(newDB, "OUI;%s\n", bc);
					if (subs == 0) fprintf(newDB, "NON;%s\n", bc);
					recup_lib=0;
					i_lib=0;
				}
			}
			if (recup_lib == 31 && i_lib < i) // on récupère le gencod dans le cas du lib long
			{
				FILE* temp = NULL;
				temp = fopen("temp", "a");
				if (ligne[j] != ' ' && ligne[j] != '\n' && j < 47 && gen < 13) {fprintf(temp, "%c", ligne[j]);gen++;} // écrit le gencod
				if (ligne[j-6] == ' ' && ligne[j-5] == -30 && ligne[j-4] == -126 && ligne[j-3] == -84 && ligne[j-2] == '/') // pour vérifier qu'il s'agit bien d'un prix au KG
				{
					if (ligne[j-1] == 'K' && ligne[j] == 'G') fprintf(temp, ";O;");
					else fprintf(temp, ";N;");
					if (ligne[j-12] == ' ') // Ne contient pas de centaine
					{
						if (ligne[j-11] == ' ') fprintf(temp, "%c.%c%c;", ligne[j-10], ligne[j-8], ligne[j-7]);
						else fprintf(temp, "%c%c.%c%c;", ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
					}
					else fprintf(temp, "%c%c%c.%c%c;", ligne[j-12], ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
					
					if (subs == 1) fprintf(temp, "OUI\n");
					if (subs == 0) fprintf(temp, "NON\n");
				}
				fclose(temp);
				if (ligne[j] == '\n')
				{
					temp = fopen("temp", "r");
					char lib1[200]={0}, prix1[10]={0}, qte[50]={0}, lib2[200]={0}, reste[500]={0};
					int t=0;
					lib1[t]= getc(temp);
					while (lib1[t] != ';')
					{
						t++;
						lib1[t] = getc(temp);
						if (lib1[t-4] == '&' && lib1[t-3] == 'a' && lib1[t-2] == 'm' && lib1[t-1] == 'p' && lib1[t] == ';') t-=4;
					}
					lib1[t] = '\0';
					t=0;
					prix1[t]= getc(temp);
					while (prix1[t] != ';')
					{
						t++;
						prix1[t] = getc(temp);
					}
					prix1[t] = '\0';
					t=0;
					qte[t]= getc(temp);
					while (qte[t] != ';')
					{
						t++;
						qte[t] = getc(temp);
					}
					qte[t] = '\0';
					t=0;
					lib2[t]= getc(temp);
					while (lib2[t] != ';')
					{
						t++;
						lib2[t] = getc(temp);
					}
					lib2[t] = '\0';
					t=0;
					reste[t]= getc(temp);
					while (reste[t] != '\n')
					{
						t++;
						reste[t] = getc(temp);
					}
					reste[t] = '\0';
					fclose(temp);
					remove("temp");
					FILE* baseClient2 = NULL;
					baseClient2 = fopen("base_client.txt", "r");
					int d=0;
					char bc[200]={0};
					bc[d] = getc(baseClient2);
					while (bc[d] != '\n')
					{
						d++;
						bc[d] = getc(baseClient2);
					}
					bc[d] = '\0';
					fclose(baseClient2);
					fprintf(newDB, "%s;%s;%s %s;%s;%s\n", prix1, qte, lib1, lib2, reste, bc);
					recup_lib=0;
					i_lib=0;
				}
			}
			if (recup_lib == 3 && i_lib < i) // on récupère le gencod dans le cas du lib classique (et la fin du libellé si lib sur 3 lignes)
			{
				if (ligne[j] != ' ' && ligne[j] != '\n' && j < 47 && gen < 13 && lib_maison == 0)
				{
					FILE* gentemp = NULL;
					gentemp = fopen("gentemp.txt", "a");
					fprintf(gentemp, "%c", ligne[j]);
					fclose(gentemp);
					gen++;
				}
				if (lib3 == 2 && j < 70)
				{
					if (ligne[j-1] != ' ' || ligne[j] != ' ') fprintf(newDB, "%c", ligne[j-1]);
				}
				if ((gen > 0 || lib_maison > 0) && ligne[j-1] == ' ' && ligne[j] == ' ')
				{
					FILE* gentemp =  NULL;
					gentemp = fopen("gentemp.txt", "a");
					if (gen == 0) gen=lib_maison+1;
					lib_maison=0;
					fprintf(gentemp, ";%d;", gen);
					fclose(gentemp);
					if (lib3 == 1) lib3 = 2;
				}
				if ((ligne[j-6] == ' ' && ligne[j-5] == -30 && ligne[j-4] == -126 && ligne[j-3] == -84 && ligne[j-2] == '/') || (ligne[j-4] == ' ' && ligne[j-3] == -30 && ligne[j-2] == -126 && ligne[j-1] == -84 && ligne[j] == '\n')) // Récupération du prix au kg lors du lib classique
				{
					FILE* gentemp = NULL;
					gentemp = fopen("gentemp.txt", "r");
					char gencod[20]={0};
					int p=0;
					gencod[p] = getc(gentemp);
					while (gencod[p] != ';')
					{
						p++;
						gencod[p] = getc(gentemp);
					}
					gencod[p] = '\0';
					fscanf(gentemp, "%d;", &gen);
					fclose(gentemp);
					remove("gentemp.txt");
					if (lib3 == 2) fprintf(newDB, ";");
					if (gen == 3) fprintf(newDB, "0000000000%s", gencod);
					else if (gen == 4) fprintf(newDB, "000000000%s", gencod);
					else if (gen == 5) fprintf(newDB, "00000000%s", gencod);
					else if (gen == 6) fprintf(newDB, "0000000%s", gencod);
					else if (gen == 7) fprintf(newDB, "000000%s", gencod);
					else if (gen == 8) fprintf(newDB, "00000%s", gencod);
					else if (gen == 9) fprintf(newDB, "0000%s", gencod);
					else if (gen == 10) fprintf(newDB, "000%s", gencod);
					else if (gen == 11) fprintf(newDB, "00%s", gencod);
					else if (gen == 12) fprintf(newDB, "0%s", gencod);
					else if (gen == 13) fprintf(newDB, "%s", gencod);
					if (lib3 == 0)
					{
						if (ligne[j-1] == 'K' && ligne[j] == 'G') fprintf(newDB, ";O;");
						else fprintf(newDB, ";N;");
						if (ligne[j-12] == ' ') // Ne contient pas de centaine
						{
							if (ligne[j-11] == ' ') fprintf(newDB, "%c.%c%c;", ligne[j-10], ligne[j-8], ligne[j-7]);
							else fprintf(newDB, "%c%c.%c%c;", ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
						}
						else fprintf(newDB, "%c%c%c.%c%c;", ligne[j-12], ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
						FILE* baseClient2 = NULL;
						baseClient2 = fopen("base_client.txt", "r");
						int d=0;
						char bc[200]={0};
						bc[d] = getc(baseClient2);
						while (bc[d] != '\n')
						{
							d++;
							bc[d] = getc(baseClient2);
						}
						bc[d] = '\0';
						fclose(baseClient2);
						if (subs == 1) fprintf(newDB, "OUI;%s\n", bc);
						if (subs == 0) fprintf(newDB, "NON;%s\n", bc);
						recup_lib=0;i_lib=0;
					}
				}
				if (ligne[j] == '\n')
				{
					if (lib3 == 0) {recup_lib=0;i_lib=0;gen=0;}
					else {recup_lib=42;i_lib=i;fprintf(newDB, ";");}
					lib3=0;lib_maison=0;
				}
			}
			if (recup_lib == 21 && i_lib < i) // On récupère la qté du lib long et la deuxième partie du lib
			{
				FILE* temp = NULL;
				temp = fopen("temp", "a");
				if (j == 16) // Écris la qté dans le fichier temp
				{
					if (ligne[j-16] != ' ') fprintf(temp, "%c", ligne[j-16]);
					if (ligne[j-15] != ' ') fprintf(temp, "%c", ligne[j-15]);
					if (ligne[j-14] != ' ') fprintf(temp, "%c", ligne[j-14]);
					if (ligne[j-13] != ' ') fprintf(temp, "%c", ligne[j-13]);
					if (ligne[j-12] != ' ') fprintf(temp, "%c", ligne[j-12]);
					if (ligne[j-11] != ' ') fprintf(temp, "%c", ligne[j-11]);
					if (ligne[j-10] != ' ') fprintf(temp, "%c", ligne[j-10]);
					if (ligne[j-9] != ' ') fprintf(temp, "%c", ligne[j-9]);
					if (ligne[j-8] != ' ') fprintf(temp, "%c", ligne[j-8]);
					if (ligne[j-7] != ' ') fprintf(temp, "%c", ligne[j-7]);
					if (ligne[j-6] != ' ') fprintf(temp, "%c", ligne[j-6]);
					if (ligne[j-5] != ' ') fprintf(temp, "%c", ligne[j-5]);
					if (ligne[j-4] != ' ') fprintf(temp, "%c", ligne[j-4]);
					if (ligne[j-3] != ' ') fprintf(temp, "%c", ligne[j-3]);
					if (ligne[j-2] != ' ') fprintf(temp, "%c", ligne[j-2]);
					if (ligne[j-1] != ' ') fprintf(temp, "%c", ligne[j-1]);
					if (ligne[j] != ' ') fprintf(temp, "%c", ligne[j]);
					fprintf(temp, ";");
				}
				else if (j > 28) // Écris la seconde partie du libellé dans le fichier temp
				{
					if ((ligne[j-10] != ' ' || ligne[j-9] != ' ') && (ligne[j-9] != ' ' || ligne[j-8] != ' ') && ligne[j-9] != '"') fprintf(temp, "%c", ligne[j-9]);
					if (ligne[j] == '\n') {fprintf(temp, ";");recup_lib=31;i_lib=i;}
				}
				fclose(temp);
			}
			if (recup_lib == 2 && i_lib < i) // On scanne la qté et le libellé. Continuer la prise en charge du libellé sur 3 lignes (lib classique = qté puis lib, 3l = lib1 déjà inscrit) Tester le fichier temp_lib, s'il existe on met à la suite le libellé dans le fichier (3l), sinon on écrit directement dans la BDD
			{
				FILE* temp_lib = NULL;
				temp_lib = fopen("temp_lib.txt", "r");
				char lib[200]={0};
				int a=0;
				lib[a] = getc(temp_lib);
				while (lib[a] != '\n')
				{
					a++;
					lib[a] = getc(temp_lib);
				}
				lib[a] = '\0';
				fclose(temp_lib);
				if (j == 16)
				{
					if (ligne[j-16] != ' ') fprintf(newDB, "%c", ligne[j-16]);
					if (ligne[j-15] != ' ') fprintf(newDB, "%c", ligne[j-15]);
					if (ligne[j-14] != ' ') fprintf(newDB, "%c", ligne[j-14]);
					if (ligne[j-13] != ' ') fprintf(newDB, "%c", ligne[j-13]);
					if (ligne[j-12] != ' ') fprintf(newDB, "%c", ligne[j-12]);
					if (ligne[j-11] != ' ') fprintf(newDB, "%c", ligne[j-11]);
					if (ligne[j-10] != ' ') fprintf(newDB, "%c", ligne[j-10]);
					if (ligne[j-9] != ' ') fprintf(newDB, "%c", ligne[j-9]);
					if (ligne[j-8] != ' ') fprintf(newDB, "%c", ligne[j-8]);
					if (ligne[j-7] != ' ') fprintf(newDB, "%c", ligne[j-7]);
					if (ligne[j-6] != ' ') fprintf(newDB, "%c", ligne[j-6]);
					if (ligne[j-5] != ' ') fprintf(newDB, "%c", ligne[j-5]);
					if (ligne[j-4] != ' ') fprintf(newDB, "%c", ligne[j-4]);
					if (ligne[j-3] != ' ') fprintf(newDB, "%c", ligne[j-3]);
					if (ligne[j-2] != ' ') fprintf(newDB, "%c", ligne[j-2]);
					if (ligne[j-1] != ' ') fprintf(newDB, "%c", ligne[j-1]);
					if (ligne[j] != ' ') fprintf(newDB, "%c", ligne[j]);
					fprintf(newDB, ";");
					passe=1;
				}
				else if (j > 16 && j <= 32)
				{
					if (ligne[j-1] != ' ' && ligne[j] != ' ') 
					{
						FILE* gentemp = NULL;
						gentemp = fopen("gentemp.txt", "a");
						fprintf(gentemp, "%c", ligne[j-1]);
						fclose(gentemp);
						lib_maison++;
					}
				}
				else if (j > 42 && passe == 1)
				{
					if (ligne[j-11] == '&') compte=1;
					if (a > 0 && lib3 == 0) {fprintf(newDB, "%s", lib);lib3=1;}
					if ((ligne[j-12] != ' ' || ligne[j-11] != ' ') && (ligne[j-11] != ' ' || ligne[j-10] != ' ') && ligne[j-11] != '"' && compte <= 1) fprintf(newDB, "%c", ligne[j-11]);
					if (ligne[j] == '\n')
					{
						int a=0;
						for (a=10;a>8;a--) {if (ligne[j-a] != ' ') fprintf(newDB, "%c", ligne[j-a]);}
						passe=2;
					}
					if (compte >= 1) compte++;
					if (compte == 6) compte=0;
				}
				if (passe == 2)
				{
					if (a == 0) fprintf(newDB, ";");
					recup_lib=3;
					i_lib=i;
					passe=0;
					remove("temp_lib.txt");
				}
			}
			if (recup_lib == 1 && i_lib < i) // Première ligne après le PU. On va scanner la ligne du prix (lib classique), vide (lib 2 lignes), lib1 (lib 3 lignes)
			{
				if (i_lib == i-1) // Il s'agit d'un lib classique ou d'un lib sur 3 lignes
				{
					if (ligne[j] == '\n' && (ligne[j-3] == -30 || ligne[j-3] == '.'))
					{
						if (ligne[j-10] == ' ')
						{
							if (ligne[j-9] == ' ' && (ligne[j-8] != '0' || ligne[j-6] != '0')) fprintf(newDB, "%c.%c%c;", ligne[j-8], ligne[j-6], ligne[j-5]);
							else if (ligne[j-9] != ' ' && ligne[j-9] != '0') fprintf(newDB, "%c%c.%c%c;", ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						}
						else if (ligne[j-10] != '0') fprintf(newDB, "%c%c%c.%c%c;", ligne[j-10], ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						int a=42;
						FILE* temp_lib= NULL;
						temp_lib = fopen("temp_lib.txt", "a");
						for (a=42;a<j-16;a++) if (ligne[a] != ' ' || ligne[a+1] != ' ') fprintf(temp_lib, "%c", ligne[a+1]);
						fprintf(temp_lib, "\n");
						fclose(temp_lib);
						recup_lib=2;
						i_lib=i;
					}
				}
				else if (i_lib == i-2) // Il s'agit d'un lib long (la première ligne après le PU est vide, c'est donc à la seconde ligne après qu'on peut récupérer des infos) ! Il faut donc scanner le libellé qui se trouve déjà sur cette ligne et le prix également
				{
					if (ligne[j-11] == '&') compte=1;
					FILE* temp = NULL;
					temp = fopen("temp", "a");
					if ((ligne[j-12] != ' ' || ligne[j-11] != ' ') && (ligne[j-11] != ' ' || ligne[j-10] != ' ') && ligne[j-11] != '"' && j > 30 && compte <= 1) fprintf(temp, "%c", ligne[j-11]);
					if (ligne[j] == '\n')
					{
						fprintf(temp, ";");
						if (ligne[j-10] == ' ')
						{
							if (ligne[j-9] == ' ' && (ligne[j-8] != '0' || ligne[j-6] != '0')) fprintf(temp, "%c.%c%c;", ligne[j-8], ligne[j-6], ligne[j-5]);
							else if (ligne[j-9] != ' ' && ligne[j-9] != '0') fprintf(temp, "%c%c.%c%c;", ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						}
						else if (ligne[j-10] != '0') fprintf(temp, "%c%c%c.%c%c;", ligne[j-10], ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						recup_lib=21;
						i_lib=i;
					}
					if (compte >= 1) compte++;
					if (compte == 6) compte=0;
					fclose(temp);
				}
			}
			if (ligne[j-2] == ' ' && ligne[j-1] == 'P' && ligne[j] == 'U' && recup_lib == 0 && i > 34 && offre == 0 && j > 20) {recup_lib=1;i_lib=i;}
			if (ligne[j-8] == 'A' && ligne[j-7] == 'V' && ligne[j-6] == 'A' && ligne[j-5] == 'N' && ligne[j-4] == 'T' && ligne[j-3] == 'A' && ligne[j-2] == 'G' && ligne[j-1] == 'E' && ligne[j] == 'S' && i < 40) offre=1;
			if (i >= 40) offre=0;
			// PU -> Prix -> Quantité /t Libellé -> Gencod \t prix/Kg Cas du lib classique
		}
		i++;
	}
	fclose(newDB);
	fclose(database);
	remove("bon_encaissement.csv");
	remove("base_client.txt");
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void rewrite_bon_encaissement_agp() // Ajouter les informations du client (n° de commande, prénom, nom, heure, date)
{
	printf("Réécriture du fichier AGP...\n");
	//Ce SP va permettre de lire et de récupérer les informations contenues dans le fichier PDF.
	FILE* database = NULL;
	database = fopen("bon_encaissement.csv", "r");
	system("wc -l bon_encaissement.csv > tmp");
	FILE* tmp = NULL;
	tmp= fopen("tmp", "r");
	int nbLignes=0, i=0, save=0, type=0, recup_lib=0, i_lib=0;
	char type_retrait[50]={0};
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	FILE* newDB = NULL;
	newDB = fopen("bon_encaissement_NEW.csv", "a");
	while (i < nbLignes)
	{
		int j=0, gen=0, passage=0, compte=0;
		char ligne[200]={0}, pass=0;
		if (save == 1) save=2;
		ligne[j] = getc(database);
		while (ligne[j] != '\n')
		{
			j++;
			ligne[j] = getc(database);
			if (i < 6 && ligne[j-7] == '/' && ligne[j-4] == '/') // Écris la date de la commande
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				if (ligne[j-18] != ' ') fprintf(baseClient, "%c", ligne[j-18]);
				if (ligne[j-17] != ' ') fprintf(baseClient, "%c", ligne[j-17]);
				if (ligne[j-16] != ' ') fprintf(baseClient, "%c", ligne[j-16]);
				if (ligne[j-15] != ' ') fprintf(baseClient, "%c", ligne[j-15]);
				if (ligne[j-14] != ' ') fprintf(baseClient, "%c", ligne[j-14]);
				if (ligne[j-13] != ' ') fprintf(baseClient, "%c", ligne[j-13]);
				if (ligne[j-12] != ' ') fprintf(baseClient, "%c", ligne[j-12]);
				if (ligne[j-11] != ' ') fprintf(baseClient, "%c", ligne[j-11]);
				fprintf(baseClient, "%c", ligne[j-10]);
				if (ligne[j-9] != ' ') fprintf(baseClient, "%c", ligne[j-9]);
				if (ligne[j-8] != ' ') fprintf(baseClient, "%c", ligne[j-8]);
				if (ligne[j-7] != ' ') fprintf(baseClient, "%c", ligne[j-7]);
				if (ligne[j-6] != ' ') fprintf(baseClient, "%c", ligne[j-6]);
				if (ligne[j-5] != ' ') fprintf(baseClient, "%c", ligne[j-5]);
				if (ligne[j-4] != ' ') fprintf(baseClient, "%c", ligne[j-4]);
				if (ligne[j-3] != ' ') fprintf(baseClient, "%c", ligne[j-3]);
				if (ligne[j-2] != ' ') fprintf(baseClient, "%c", ligne[j-2]);
				if (ligne[j-1] != ' ') fprintf(baseClient, "%c", ligne[j-1]);
				if (ligne[j] != ' ') fprintf(baseClient, "%c", ligne[j]);
				fprintf(baseClient, " - ");
				fclose(baseClient);
			}
			if (i < 8 && ligne [j-10] == 'h' && ligne[j-6] == '-' && ligne[j-2] == 'h')
			{
				FILE* baseClient = NULL;
				baseClient =fopen("base_client.txt", "a");
				fprintf(baseClient, "%c%c%c%c%c%c%c%c%c%c%c,", ligne[j-12], ligne[j-11], ligne[j-10],  ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-4], ligne[j-3], ligne[j-2], ligne[j-1], ligne[j]); //Récupère l'heure
				fclose(baseClient);
				FILE* tri_heures = NULL;
				tri_heures =  fopen("tri_heures.txt", "a");
				fprintf(tri_heures, "%c%c%c%c%c\n", ligne[j-12], ligne[j-11], ligne[j-10],  ligne[j-9], ligne[j-8]);
				fclose(tri_heures);
			}
			if (i < 10 && ligne[j-18] == 'C' && ligne[j-17] == 'o' && ligne[j-11] == 'e' && ligne [j-9] == ':') // Récupère le numéro de la commande
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				if (ligne[j-7] != ' ') fprintf(baseClient, "%c", ligne[j-7]);
				if (ligne[j-6] != ' ') fprintf(baseClient, "%c", ligne[j-6]);
				if (ligne[j-5] != ' ') fprintf(baseClient, "%c", ligne[j-5]);
				if (ligne[j-4] != ' ') fprintf(baseClient, "%c", ligne[j-4]);
				if (ligne[j-3] != ' ') fprintf(baseClient, "%c", ligne[j-3]);
				if (ligne[j-2] != ' ') fprintf(baseClient, "%c", ligne[j-2]);
				if (ligne[j-1] != ' ') fprintf(baseClient, "%c", ligne[j-1]);
				if (ligne[j] != ' ') fprintf(baseClient, "%c", ligne[j]);
				fprintf(baseClient, ",");
				fclose(baseClient);
			}
			if (i == 8 && (ligne[0] == 'R' || ligne[0] == 'L' || ligne[0] == 'P') && type == 0) // Récupère les informations sur la commande: type de retrait, type de paiement
			{
				char type_paiement[100]={0}, pbl[100]={0};
				if (ligne[0] == 'R')
				{
					type_retrait[0] = 'R';
					type_retrait[1] = 'e';
		            type_retrait[2] = 't';
		            type_retrait[3] = 'r';
		            type_retrait[4] = 'a';
		            type_retrait[5] = 'i';
		            type_retrait[6] = 't';
		            type_retrait[7] = '\0';
                }
                else if (ligne[0] == 'L')
                {
                  	type_retrait[0] = 'L';
                  	type_retrait[1] = 'i';
                  	type_retrait[2] = 'v';
                 	type_retrait[3] = 'r';
                  	type_retrait[4] = 'a';
                  	type_retrait[5] = 'i';
                  	type_retrait[6] = 's';
                  	type_retrait[7] = 'o';
                  	type_retrait[8] = 'n';
                  	type_retrait[9] = '\0';
                }
                else if (ligne[0] == 'P')
                {
                  	type_retrait[0] = 'P';
                  	type_retrait[1] = 'o';
                  	type_retrait[2] = 'i';
                  	type_retrait[3] = 'n';
                  	type_retrait[4] = 't';
                  	type_retrait[5] = ' ';
                  	type_retrait[6] = 'r';
                  	type_retrait[7] = 'e';
                  	type_retrait[8] = 'l';
                  	type_retrait[9] = 'a';
                  	type_retrait[10] = 'i';
                  	type_retrait[11] = 's';
                  	type_retrait[12] = '\0';
                }
                else printf("Problème de définition du type de retrait.\n");						
				int a=1;
                                pbl[a-1] = getc(database);
                                pbl[a] = getc(database);
				while (pbl[a] != 'P')
				{
					a++;
					pbl[a] = getc(database);
				}
                                type_paiement[0] = pbl[a];
				type_paiement[1] = getc(database);
				a=1;
				while (type_paiement[a] != '\n')
				{
					a++;
					type_paiement[a] = getc(database);
				}
				type_paiement[a] = '\0';
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				fprintf(baseClient, "%s,%s,", type_retrait, type_paiement);
				fclose(baseClient);
				ligne[j] = '\n';
				type=1;
			}
			if (i < 12 && i > 9 && ligne[j-51] == ' ' && ligne[j-50] == 'M'  && (ligne[j-49] == '.' || ligne[j-49] == 'm') && pass == 0) //Récupère le nom du client (jusqu'à 50 caractères)
			{
				FILE* baseClient = NULL;
				baseClient = fopen("base_client.txt", "a");
				if ((ligne[j-50] != ' ' && ligne[j-49] != ' ') || (ligne[j-50] != ' ' && ligne[j-49] == ' ') || (ligne[j-50] == ' ' && ligne[j-49] != ' ')) fprintf(baseClient, "%c", ligne[j-50]);
				if ((ligne[j-49] != ' ' && ligne[j-48] != ' ') || (ligne[j-49] != ' ' && ligne[j-48] == ' ') || (ligne[j-49] == ' ' && ligne[j-48] != ' ')) fprintf(baseClient, "%c", ligne[j-49]);
				if ((ligne[j-48] != ' ' && ligne[j-47] != ' ') || (ligne[j-48] != ' ' && ligne[j-47] == ' ') || (ligne[j-48] == ' ' && ligne[j-47] != ' ')) fprintf(baseClient, "%c", ligne[j-48]);
				if ((ligne[j-47] != ' ' && ligne[j-46] != ' ') || (ligne[j-47] != ' ' && ligne[j-46] == ' ') || (ligne[j-47] == ' ' && ligne[j-46] != ' ')) fprintf(baseClient, "%c", ligne[j-47]);
				if ((ligne[j-46] != ' ' && ligne[j-45] != ' ') || (ligne[j-46] != ' ' && ligne[j-45] == ' ') || (ligne[j-46] == ' ' && ligne[j-45] != ' ')) fprintf(baseClient, "%c", ligne[j-46]);
				if ((ligne[j-45] != ' ' && ligne[j-44] != ' ') || (ligne[j-45] != ' ' && ligne[j-44] == ' ') || (ligne[j-45] == ' ' && ligne[j-44] != ' ')) fprintf(baseClient, "%c", ligne[j-45]);
				if ((ligne[j-44] != ' ' && ligne[j-43] != ' ') || (ligne[j-44] != ' ' && ligne[j-43] == ' ') || (ligne[j-44] == ' ' && ligne[j-43] != ' ')) fprintf(baseClient, "%c", ligne[j-44]);
				if ((ligne[j-43] != ' ' && ligne[j-42] != ' ') || (ligne[j-43] != ' ' && ligne[j-42] == ' ') || (ligne[j-43] == ' ' && ligne[j-42] != ' ')) fprintf(baseClient, "%c", ligne[j-43]);
				if ((ligne[j-42] != ' ' && ligne[j-41] != ' ') || (ligne[j-42] != ' ' && ligne[j-41] == ' ') || (ligne[j-42] == ' ' && ligne[j-41] != ' ')) fprintf(baseClient, "%c", ligne[j-42]);
				if ((ligne[j-41] != ' ' && ligne[j-40] != ' ') || (ligne[j-41] != ' ' && ligne[j-40] == ' ') || (ligne[j-41] == ' ' && ligne[j-40] != ' ')) fprintf(baseClient, "%c", ligne[j-41]);
				if ((ligne[j-40] != ' ' && ligne[j-39] != ' ') || (ligne[j-40] != ' ' && ligne[j-39] == ' ') || (ligne[j-40] == ' ' && ligne[j-39] != ' ')) fprintf(baseClient, "%c", ligne[j-40]);
				if ((ligne[j-39] != ' ' && ligne[j-38] != ' ') || (ligne[j-39] != ' ' && ligne[j-38] == ' ') || (ligne[j-39] == ' ' && ligne[j-38] != ' ')) fprintf(baseClient, "%c", ligne[j-39]);
				if ((ligne[j-38] != ' ' && ligne[j-37] != ' ') || (ligne[j-38] != ' ' && ligne[j-37] == ' ') || (ligne[j-38] == ' ' && ligne[j-37] != ' ')) fprintf(baseClient, "%c", ligne[j-38]);
				if ((ligne[j-37] != ' ' && ligne[j-36] != ' ') || (ligne[j-37] != ' ' && ligne[j-36] == ' ') || (ligne[j-37] == ' ' && ligne[j-36] != ' ')) fprintf(baseClient, "%c", ligne[j-37]);
				if ((ligne[j-36] != ' ' && ligne[j-35] != ' ') || (ligne[j-36] != ' ' && ligne[j-35] == ' ') || (ligne[j-36] == ' ' && ligne[j-35] != ' ')) fprintf(baseClient, "%c", ligne[j-36]);
				if ((ligne[j-35] != ' ' && ligne[j-34] != ' ') || (ligne[j-35] != ' ' && ligne[j-34] == ' ') || (ligne[j-35] == ' ' && ligne[j-34] != ' ')) fprintf(baseClient, "%c", ligne[j-35]);
				if ((ligne[j-34] != ' ' && ligne[j-33] != ' ') || (ligne[j-34] != ' ' && ligne[j-33] == ' ') || (ligne[j-34] == ' ' && ligne[j-33] != ' ')) fprintf(baseClient, "%c", ligne[j-34]);
				if ((ligne[j-33] != ' ' && ligne[j-32] != ' ') || (ligne[j-33] != ' ' && ligne[j-32] == ' ') || (ligne[j-33] == ' ' && ligne[j-32] != ' ')) fprintf(baseClient, "%c", ligne[j-33]);
				if ((ligne[j-32] != ' ' && ligne[j-31] != ' ') || (ligne[j-32] != ' ' && ligne[j-31] == ' ') || (ligne[j-32] == ' ' && ligne[j-31] != ' ')) fprintf(baseClient, "%c", ligne[j-32]);
				if ((ligne[j-31] != ' ' && ligne[j-30] != ' ') || (ligne[j-31] != ' ' && ligne[j-30] == ' ') || (ligne[j-31] == ' ' && ligne[j-30] != ' ')) fprintf(baseClient, "%c", ligne[j-31]);
				if ((ligne[j-30] != ' ' && ligne[j-29] != ' ') || (ligne[j-30] != ' ' && ligne[j-29] == ' ') || (ligne[j-30] == ' ' && ligne[j-29] != ' ')) fprintf(baseClient, "%c", ligne[j-30]);
				if ((ligne[j-29] != ' ' && ligne[j-28] != ' ') || (ligne[j-29] != ' ' && ligne[j-28] == ' ') || (ligne[j-29] == ' ' && ligne[j-28] != ' ')) fprintf(baseClient, "%c", ligne[j-29]);
				if ((ligne[j-28] != ' ' && ligne[j-27] != ' ') || (ligne[j-28] != ' ' && ligne[j-27] == ' ') || (ligne[j-28] == ' ' && ligne[j-27] != ' ')) fprintf(baseClient, "%c", ligne[j-28]);
				if ((ligne[j-27] != ' ' && ligne[j-26] != ' ') || (ligne[j-27] != ' ' && ligne[j-26] == ' ') || (ligne[j-27] == ' ' && ligne[j-26] != ' ')) fprintf(baseClient, "%c", ligne[j-27]);
				if ((ligne[j-26] != ' ' && ligne[j-25] != ' ') || (ligne[j-26] != ' ' && ligne[j-25] == ' ') || (ligne[j-26] == ' ' && ligne[j-25] != ' ')) fprintf(baseClient, "%c", ligne[j-26]);
				if ((ligne[j-25] != ' ' && ligne[j-24] != ' ') || (ligne[j-25] != ' ' && ligne[j-24] == ' ') || (ligne[j-25] == ' ' && ligne[j-24] != ' ')) fprintf(baseClient, "%c", ligne[j-25]);
				if ((ligne[j-24] != ' ' && ligne[j-23] != ' ') || (ligne[j-24] != ' ' && ligne[j-23] == ' ') || (ligne[j-24] == ' ' && ligne[j-23] != ' ')) fprintf(baseClient, "%c", ligne[j-24]);
				if ((ligne[j-23] != ' ' && ligne[j-22] != ' ') || (ligne[j-23] != ' ' && ligne[j-22] == ' ') || (ligne[j-23] == ' ' && ligne[j-22] != ' ')) fprintf(baseClient, "%c", ligne[j-23]);
				if ((ligne[j-22] != ' ' && ligne[j-21] != ' ') || (ligne[j-22] != ' ' && ligne[j-21] == ' ') || (ligne[j-22] == ' ' && ligne[j-21] != ' ')) fprintf(baseClient, "%c", ligne[j-22]);
				if ((ligne[j-21] != ' ' && ligne[j-20] != ' ') || (ligne[j-21] != ' ' && ligne[j-20] == ' ') || (ligne[j-21] == ' ' && ligne[j-20] != ' ')) fprintf(baseClient, "%c", ligne[j-21]);
				if ((ligne[j-20] != ' ' && ligne[j-19] != ' ') || (ligne[j-20] != ' ' && ligne[j-19] == ' ') || (ligne[j-20] == ' ' && ligne[j-19] != ' ')) fprintf(baseClient, "%c", ligne[j-20]);
				if ((ligne[j-19] != ' ' && ligne[j-18] != ' ') || (ligne[j-19] != ' ' && ligne[j-18] == ' ') || (ligne[j-19] == ' ' && ligne[j-18] != ' ')) fprintf(baseClient, "%c", ligne[j-19]);
				if ((ligne[j-18] != ' ' && ligne[j-17] != ' ') || (ligne[j-18] != ' ' && ligne[j-17] == ' ') || (ligne[j-18] == ' ' && ligne[j-17] != ' ')) fprintf(baseClient, "%c", ligne[j-18]);
				if ((ligne[j-17] != ' ' && ligne[j-16] != ' ') || (ligne[j-17] != ' ' && ligne[j-16] == ' ') || (ligne[j-17] == ' ' && ligne[j-16] != ' ')) fprintf(baseClient, "%c", ligne[j-17]);
				if ((ligne[j-16] != ' ' && ligne[j-15] != ' ') || (ligne[j-16] != ' ' && ligne[j-15] == ' ') || (ligne[j-16] == ' ' && ligne[j-15] != ' ')) fprintf(baseClient, "%c", ligne[j-16]);
				if ((ligne[j-15] != ' ' && ligne[j-14] != ' ') || (ligne[j-15] != ' ' && ligne[j-14] == ' ') || (ligne[j-15] == ' ' && ligne[j-14] != ' ')) fprintf(baseClient, "%c", ligne[j-15]);
				if ((ligne[j-14] != ' ' && ligne[j-13] != ' ') || (ligne[j-14] != ' ' && ligne[j-13] == ' ') || (ligne[j-14] == ' ' && ligne[j-13] != ' ')) fprintf(baseClient, "%c", ligne[j-14]);
				if ((ligne[j-13] != ' ' && ligne[j-12] != ' ') || (ligne[j-13] != ' ' && ligne[j-12] == ' ') || (ligne[j-13] == ' ' && ligne[j-12] != ' ')) fprintf(baseClient, "%c", ligne[j-13]);
				if ((ligne[j-12] != ' ' && ligne[j-11] != ' ') || (ligne[j-12] != ' ' && ligne[j-11] == ' ') || (ligne[j-12] == ' ' && ligne[j-11] != ' ')) fprintf(baseClient, "%c", ligne[j-12]);
				if ((ligne[j-11] != ' ' && ligne[j-10] != ' ') || (ligne[j-11] != ' ' && ligne[j-10] == ' ') || (ligne[j-11] == ' ' && ligne[j-10] != ' ')) fprintf(baseClient, "%c", ligne[j-11]);
				if ((ligne[j-10] != ' ' && ligne[j-9] != ' ') || (ligne[j-10] != ' ' && ligne[j-9] == ' ') || (ligne[j-10] == ' ' && ligne[j-9] != ' ')) fprintf(baseClient, "%c", ligne[j-10]);
				pass=1;
				fclose(baseClient);
			}
			FILE* baseClient = NULL;
			baseClient = fopen("base_client.txt", "a");
			if ((type_retrait[0] == 'L' || type_retrait[0] == 'P') && i == 30 && ligne[j] == '\n') fprintf(baseClient, ",Sac(s) facturé(s)\n");
			if (ligne[j-10] == 'P' && ligne[j-9] == 'a' && ligne[j-8] == 's' && ligne[j-7] == ' ' && ligne[j-6] == 'd' && ligne[j-5] == 'e' && ligne[j-4] == ' ' && ligne[j-3] == 's' && ligne[j-2] == 'a' && ligne[j-1] == 'c' && ligne[j] == 's') fprintf(baseClient, ",Pas de sacs\n");
			if (ligne[j-7] == 'S' && ligne[j-6] == 'a' && ligne[j-5] == 'c' && ligne[j-4] == '(' && ligne[j-3] == 's' && ligne[j-2] == ')' && ligne[j-1] == ' ' && ligne[j] == 'f') fprintf(baseClient, ",Sac(s) facturé(s)\n");
			fclose(baseClient);
			if (recup_lib == 41 && i_lib < i)
			{
				if (passage == 0)
				{
					FILE* temp = NULL;
					temp = fopen("temp", "r");
					char gencod[20]={0};int k=0;
					gencod[k] = getc(temp);
					while (gencod[k] != ';')
					{
						k++;
						gencod[k] = getc(temp);
					}
					gencod[k] = '\0';
					fclose(temp);
					remove("temp");
					fprintf(newDB, "%s", gencod);
					passage = 1;
				}
				if (ligne[j-5] == '.' && ligne[j-4] == '(' && ligne[j-3] == 'O' && ligne[j-2] == 'u' && ligne[j-1] == 'i' && ligne[j] == ')') fprintf(newDB, ";OUI\n");
				else if (ligne[j-4] == '(' && ligne[j-3] == 'N' && ligne[j-2] == 'o' && ligne[j-1] == 'n' && ligne[j] == ')') fprintf(newDB, ";NON\n");
				if (ligne[j] == '\n') {recup_lib=0;i_lib=0;}
			}
			if (recup_lib == 31 && i_lib < i)
			{
				char prix[10]={0}, qte[10]={0};int p=0;
				if (passage == 0)
				{
					FILE* temp = NULL;
					temp = fopen("temp", "r");
					prix[p] = getc(temp);
					while (prix[p] != ';')
					{
						p++;
						prix[p] = getc(temp);
					}
					prix[p] = '\0';
					p=0;
					qte[p] = getc(temp);
					while (qte[p] != ';')
					{
						p++;
						qte[p] = getc(temp);
					}
					qte[p] = '\0';
					fclose(temp);
					remove("temp");
					passage=1;
					fprintf(newDB, "%s;%s;", prix, qte);
				}
				if (ligne[j] != ' ' && gen < 13)
				{
					FILE* temp = NULL;
					temp = fopen("temp", "a");
					fprintf(temp, "%c", ligne[j]);
					fclose(temp);
					gen++;
				}
				if (gen == 13)
				{
					if (ligne[j-6] == ' ' && ligne[j-5] == -30 && ligne[j-4] == -126 && ligne[j-3] == -84 && ligne[j-2] == '/') // pour vérifier qu'il s'agit bien d'un prix au KG
					{
						if (ligne[j-1] == 'K' && ligne[j] == 'G') fprintf(newDB, "O;");
						else fprintf(newDB, "N;");
						if (ligne[j-12] == ' ') // Ne contient pas de centaine
						{
							if (ligne[j-11] == ' ') fprintf(newDB, "%c.%c%c;", ligne[j-10], ligne[j-8], ligne[j-7]);
							else fprintf(newDB, "%c%c.%c%c;", ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
						}
						else fprintf(newDB, "%c%c%c.%c%c;", ligne[j-12], ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
						recup_lib=41;i_lib=i;
						FILE* temp = NULL;
						temp = fopen("temp", "a");
						fprintf(temp, ";");
						fclose(temp);
						passage = 0;
					}	
				}
			}
			if (recup_lib == 3 && i_lib < i)
			{
				if (ligne[j] != ' ' && gen < 13) {fprintf(newDB, "%c", ligne[j]);gen++;}
				if (gen == 13)
				{
					if (ligne[j-5] == '.' && ligne[j-4] == '(' && ligne[j-3] == 'O' && ligne[j-2] == 'u' && ligne[j-1] == 'i' && ligne[j] == ')') fprintf(newDB, ";OUI\n");
					else if (ligne[j-4] == '(' && ligne[j-3] == 'N' && ligne[j-2] == 'o' && ligne[j-1] == 'n' && ligne[j] == ')') fprintf(newDB, ";NON\n");
					if (ligne[j] == '\n') {recup_lib=0;i_lib=0;}
				}
			}
			if (recup_lib == 21 && i_lib < i)
			{
				if (j == 14)
				{
					FILE* temp = NULL;
					temp = fopen("temp", "a");
					if (ligne[j-14] != ' ') fprintf(temp, "%c", ligne[j-14]);
					if (ligne[j-13] != ' ') fprintf(temp, "%c", ligne[j-13]);
					if (ligne[j-12] != ' ') fprintf(temp, "%c", ligne[j-12]);
					if (ligne[j-11] != ' ') fprintf(temp, "%c", ligne[j-11]);
					if (ligne[j-10] != ' ') fprintf(temp, "%c", ligne[j-10]);
					if (ligne[j-9] != ' ') fprintf(temp, "%c", ligne[j-9]);
					if (ligne[j-8] != ' ') fprintf(temp, "%c", ligne[j-8]);
					if (ligne[j-7] != ' ') fprintf(temp, "%c", ligne[j-7]);
					if (ligne[j-6] != ' ') fprintf(temp, "%c", ligne[j-6]);
					if (ligne[j-5] != ' ') fprintf(temp, "%c", ligne[j-5]);
					if (ligne[j-4] != ' ') fprintf(temp, "%c", ligne[j-4]);
					if (ligne[j-3] != ' ') fprintf(temp, "%c", ligne[j-3]);
					if (ligne[j-2] != ' ') fprintf(temp, "%c", ligne[j-2]);
					if (ligne[j-1] != ' ') fprintf(temp, "%c", ligne[j-1]);
					if (ligne[j] != ' ') fprintf(temp, "%c", ligne[j]);
					fprintf(temp, ";");
					fclose(temp);
				}
				else if (j > 14) // Ecrire la deuxième partie du libellé dans le fichier temp en faisant attention ne pas écrire le "Dont TVA" de la fin de la ligne
				{
					if (ligne[j-8] == 'd' && ligne[j-7] == 'o' && ligne[j-6] == 'n' && ligne[j-5] == 't' && ligne[j-4] == ' ' && ligne[j-3] == 'T' && ligne[j-2] == 'V' && ligne[j-1] == 'A' && ligne[j] == '\n') {fprintf(newDB, ";");recup_lib=31;i_lib=1;}
					else if ((ligne[j-9] != ' ' || ligne[j-8] != ' ') && (ligne[j-8] != ' ' || ligne[j-7] != ' ') && ligne[j-8] != '"' && j > 20) fprintf(newDB, "%c", ligne[j-8]);
				}
			}
			if (recup_lib == 2 && i_lib < i)
			{
				if (j == 14)
				{
					if (ligne[j-14] != ' ') fprintf(newDB, "%c", ligne[j-14]);
					if (ligne[j-13] != ' ') fprintf(newDB, "%c", ligne[j-13]);
					if (ligne[j-12] != ' ') fprintf(newDB, "%c", ligne[j-12]);
					if (ligne[j-11] != ' ') fprintf(newDB, "%c", ligne[j-11]);
					if (ligne[j-10] != ' ') fprintf(newDB, "%c", ligne[j-10]);
					if (ligne[j-9] != ' ') fprintf(newDB, "%c", ligne[j-9]);
					if (ligne[j-8] != ' ') fprintf(newDB, "%c", ligne[j-8]);
					if (ligne[j-7] != ' ') fprintf(newDB, "%c", ligne[j-7]);
					if (ligne[j-6] != ' ') fprintf(newDB, "%c", ligne[j-6]);
					if (ligne[j-5] != ' ') fprintf(newDB, "%c", ligne[j-5]);
					if (ligne[j-4] != ' ') fprintf(newDB, "%c", ligne[j-4]);
					if (ligne[j-3] != ' ') fprintf(newDB, "%c", ligne[j-3]);
					if (ligne[j-2] != ' ') fprintf(newDB, "%c", ligne[j-2]);
					if (ligne[j-1] != ' ') fprintf(newDB, "%c", ligne[j-1]);
					if (ligne[j] != ' ') fprintf(newDB, "%c", ligne[j]);
				}
				else
				{
					if (ligne[j-6] == ' ' && ligne[j-5] == -30 && ligne[j-4] == -126 && ligne[j-3] == -84 && ligne[j-2] == '/') // pour vérifier qu'il s'agit bien d'un prix au KG
					{
						if (ligne[j-1] == 'K' && ligne[j] == 'G') fprintf(newDB, ";O;");
						else fprintf(newDB, ";N;");
						if (ligne[j-12] == ' ') // Ne contient pas de centaine
						{
							if (ligne[j-11] == ' ') fprintf(newDB, "%c.%c%c;", ligne[j-10], ligne[j-8], ligne[j-7]);
							else fprintf(newDB, "%c%c.%c%c;", ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
						}
						else fprintf(newDB, "%c%c%c.%c%c;", ligne[j-12], ligne[j-11], ligne[j-10], ligne[j-8], ligne[j-7]);
						recup_lib=3;i_lib=i;
					}
				}
			}
			if (recup_lib == 1 && i_lib < i) // Récupération du libellé + du prix
			{
				if (i_lib+2 == i) // Le libellé est affiché en-dessous une ligne vide du PU -> lib classique
				{
					if (ligne[j-11] == '&') compte=1;
					if ((ligne[j-12] != ' ' || ligne[j-11] != ' ') && (ligne[j-11] || ligne[j-10] != ' ') && ligne[j-11] != '"' && ligne[j-11] != 0 && ligne[j-11] !=  1 && compte <= 1) fprintf(newDB, "%c", ligne[j-11]);
					if (ligne[j] == '\n' && ligne[j-3] == -30)
					{
						if (ligne[j-10] == ' ')
						{
							if (ligne[j-9] == ' ' && (ligne[j-8] != '0' || ligne[j-6] != '0')) fprintf(newDB, ";%c.%c%c;", ligne[j-8], ligne[j-6], ligne[j-5]);
							else if (ligne[j-9] != ' ' && ligne[j-9] != '0') fprintf(newDB, ";%c%c.%c%c;", ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						}
						else if (ligne[j-10] != '0') fprintf(newDB, ";%c%c%c.%c%c;", ligne[j-10], ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						if (ligne[j-8] != '0' || ligne[j-6] != '0') {recup_lib=2;i_lib=i;}
						else {recup_lib=0;i_lib=0;}
					}
					if (compte >= 1) compte++;
					if (compte == 6) compte=0;
				}
				else if (i_lib+1 == i) // Le libellé est affiché juste en dessous le PU : il s'agit d'un lib long
				{
					if (ligne[j-11] == '&') compte=1;
					FILE* temp = NULL;
					temp = fopen("temp", "a");
					if ((ligne[j-12] != ' ' || ligne[j-11] != ' ') && (ligne[j-11] != ' ' || ligne[j-10] != ' ') && ligne[j-11] != '"' && ligne[j-11] != 0 && ligne[j-11] !=  1 && compte <= 1) fprintf(newDB, "%c", ligne[j-11]);
					if (ligne[j] == '\n' && ligne[j-3] == -30)
					{
						if (ligne[j-10] == ' ')
						{
							if (ligne[j-9] == ' ' && (ligne[j-8] != '0' || ligne[j-6] != '0')) fprintf(temp, "%c.%c%c;", ligne[j-8], ligne[j-6], ligne[j-5]);
							else if (ligne[j-9] != ' ' && ligne[j-9] != '0') fprintf(temp, "%c%c.%c%c;", ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						}
						else if (ligne[j-10] != '0') fprintf(temp, "%c%c%c.%c%c;", ligne[j-10], ligne[j-9], ligne[j-8], ligne[j-6], ligne[j-5]);
						if (ligne[j-8] != '0' || ligne[j-6] != '0') {recup_lib=21;i_lib=i;fprintf(newDB, " ");}
						else {recup_lib=0;i_lib=0;}
					}
					if (compte >= 1) compte++;
					if (compte == 6) compte=0;
					fclose(temp);
				}
			}
			if (ligne[j-2] == ' ' && ligne[j-1] == 'P' && ligne[j] == 'U' && recup_lib == 0 && i > 36) {recup_lib=1;i_lib=i;}
		}	
		i++;
	}
	fclose(newDB);
	fclose(database);
	remove("bon_encaissement.csv");
	inverse_data();
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void inverse_data()
{
	FILE* database = NULL;
	database = fopen("bon_encaissement_NEW.csv", "r");
	system("wc -l bon_encaissement_NEW.csv > tmp");
	FILE* tmp = NULL;
	tmp =  fopen("tmp","r");
	int nbLignes=0, i=0, a=0;
	char cbc[600]={0};
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	FILE* bc = NULL;
	bc = fopen("base_client.txt", "r");
	cbc[a] = getc(bc);
	while (cbc[a] != '\n')
	{
		a++;
		cbc[a] = getc(bc);
	}
	cbc[a] = '\0';
	fclose(bc);
	remove("base_client.txt");
	FILE* newDB = NULL;
	newDB = fopen("bon_encaissement_NEW_NEW.csv", "a");
	while (i < nbLignes)
	{
		char libelle[300]={0}, prix[10]={0}, qte[5]={0}, type_prix[5]={0}, prixKG[10]={0}, gencod[20]={0}, subs[10]={0};
		int j=0;
		libelle[j] = getc(database);
		while (libelle[j] != ';')
		{
			j++;
			libelle[j] = getc(database);
		}
		libelle[j] = '\0';
		j=0;
		prix[j] = getc(database);
		while (prix[j] != ';')
		{
			j++;
			prix[j] = getc(database);
		}
		prix[j] = '\0';
		j=0;
		qte[j] = getc(database);
		while (qte[j] != ';')
		{
			j++;
			qte[j] = getc(database);
		}
		qte[j] = '\0';
		j=0;
		type_prix[j] = getc(database);
		while (type_prix[j] != ';')
		{
			j++;
			type_prix[j] = getc(database);
		}
		type_prix[j] = '\0';
		j=0;
		prixKG[j] = getc(database);
		while (prixKG[j] != ';')
		{
			j++;
			prixKG[j] = getc(database);
		}
		prixKG[j] = '\0';
		j=0;
		gencod[j] = getc(database);
		while (gencod[j] != ';')
		{
			j++;
			gencod[j] = getc(database);
		}
		gencod[j] = '\0';
		j=0;
		subs[j] = getc(database);
		while (subs[j] != '\n')
		{
			j++;
			subs[j] = getc(database);
		}
		subs[j] = '\0';
		fprintf(newDB, "%s;%s;%s;%s;%s;%s;%s;%s\n", prix, qte, libelle, gencod, type_prix, prixKG, subs, cbc);
		i++;
	}
	fclose(newDB);
	fclose(database);
	system("mv bon_encaissement_NEW_NEW.csv ./bon_encaissement_NEW.csv");
}

void rewrite_bon_encaissement_02()
{
	printf("Réécriture du fichier (2)...\n");
	FILE* database = NULL;
	database = fopen("bon_encaissement_NEW.csv", "r");
	system("wc -l bon_encaissement_NEW.csv > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0, nb_produits=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	FILE* newDB = NULL;
	newDB = fopen("bon_encaissement_NEW_NEW.csv", "a");
	fclose(newDB);
	while (i < nbLignes)
	{
		FILE* temp = NULL;
		temp =  fopen("temp", "a");
		int j=0, qte=0, kilos=0, grammes=0;
		float prix3=0, prix4=0, prixf=0;
		char prix[10]={0}, libelle[300]={0}, gencod[20]={0}, sub[10]={0}, prix2[10]={0}, poids[10]={0}, mealz='N', infos_client[300]={0};
		prix[j] = getc(database);
		fprintf(temp, "%c", prix[j]);
		while (prix[j] != ';')
		{
			j++;
			prix[j] = getc(database);
			fprintf(temp, "%c", prix[j]);
			if (prix[j] == '.') prix[j] = ','; // Cette ligne ne sert à ... rien ?
		}
		prix[j] = '\0';
		j=0;
		fscanf(database, "%d;", &qte);
		qte_totale+=qte;
		nb_produits+=qte;
		libelle[j] = getc(database);
		while (libelle[j] != ';')
		{
			j++;
			libelle[j] = getc(database);
			if (libelle[j-1] == ' ' && libelle[j] == ' ') j--;
			if (libelle[j-4] == '&' && libelle[j-3] == 'a' && libelle[j-2] == 'm' && libelle[j-1] == 'p' && libelle[j] == ';') j -= 4;
		}
		if (libelle[j-1] == ' ') libelle[j-1] = '\0';
		else libelle[j] = '\0';
		j=0;
		gencod[j] = getc(database);
		while (gencod[j] != ';')
		{
			j++;
			gencod[j] = getc(database);
		}
		gencod[j] = '\0';
		j=0;
		fscanf(database, "%c;", &poids[0]);
		prix2[j] = getc(database);
		fprintf(temp, "%c", prix2[j]);
		while (prix2[j] != ';')
		{
			j++;
			prix2[j] = getc(database);
			fprintf(temp, "%c", prix2[j]);
			if (prix2[j] == '.') prix2[j] = ',';
		}
		prix2[j] = '\0';
		j=0;
		fclose(temp);
		sub[j] = getc(database);
		while (sub[j] != ';')
		{
			j++;
			sub[j] = getc(database);
		}
		sub[j] = '\0';
		j=0;
		infos_client[j] = getc(database);
		while (infos_client[j] != '\n')
		{
			j++;
			infos_client[j] = getc(database);
		}
		infos_client[j] = '\0';
		FILE* newDB = NULL;
		newDB = fopen("bon_encaissement_NEW_final.csv", "a");
		if ((gencod[0] != '3' || gencod[1] != '3' || gencod[2] != '6' || gencod[3] != '8' || gencod[4] != '9' || gencod[5] != '5' || gencod[6] != '8' || gencod[7] != '4' || gencod[8] != '6' || gencod[9] != '7' || gencod[10] != '8' || gencod[11] != '0' || gencod[12] != '9') && (gencod[0] != '9' || gencod[1] != '9'))
		{
			if (poids[0] == 'O' && (gencod[0] == '0' || (gencod[0] == '2' && (gencod[1] != '0' || gencod[2] != '0' || gencod[3] != '0' || gencod[4] != '0')))) // Le produit contient un PV si le gencod commence par un 0 ou un 2
			{
				FILE* temp2 = NULL;
				temp2 = fopen("temp", "r");
				fscanf(temp2, "%f;%f;", &prix3, &prix4);
				fclose(temp2);
				remove("temp");
				prixf=prix3/prix4;
				temp2 = fopen("temp", "a");
				fprintf(temp2, "%.2f\n", prixf);
				fclose(temp2);
				temp2 = fopen("temp", "r");
				fscanf(temp2, "%d.%d\n", &kilos, &grammes);
				fclose(temp2);
				int kilosT=0, grammesT=0;
				kilosT=qte*kilos;
				grammesT=qte*grammes;
				if (grammesT >= 100) {grammesT-=100;kilosT+=1;}
				if (grammes < 10) fprintf(newDB, "%s;%s;%s;%s;%d;%s;%d,0%d;%d,%d;%c;%s\n", gencod, libelle, prix, prix2, qte, sub, kilos, grammes*10, kilosT, grammesT*10, mealz, infos_client);
				else fprintf(newDB, "%s;%s;%s;%s;%d;%s;%d,%d;%d,%d;%c;%s\n", gencod, libelle, prix, prix2, qte, sub, kilos, grammes*10, kilosT, grammesT*10, mealz, infos_client);
			}
			else fprintf(newDB, "%s;%s;%s;%s;%d;%s;0;0;%c;%s\n", gencod, libelle, prix, prix2, qte, sub, mealz, infos_client);
		}
		else qte_totale--;
		fclose(newDB);
		remove("temp");
		i++;
	}
	fclose(database);
	FILE* tri_nb_pdts = NULL;
	tri_nb_pdts = fopen("tri_nb_pdts.txt", "a");
	fprintf(tri_nb_pdts, "%d\n", nb_produits);
	fclose(tri_nb_pdts);
	remove("bon_encaissement_NEW.csv");
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
	if (nb_files >= 2) {nb_files--;add_files();}
	if (nb_files_def < 2) {remove("tri_cde.txt");remove("tri_heures.txt");remove("tri_nb_pdts.txt");}
}

void add_files()// Tester ici le nombre de fichiers. Si 1 : on continue normalement, si plusieurs on revient au début du programme en comptant le nombre de fois qu'on revient au début
{
	change_format_fichier();
	test_bon_encaissement();
	rewrite_bon_encaissement_02();
}

void match_adresses() // Le programme ne reconnait pas les gencod commencant par un 0 (poids variable), il est donc nécessaire de vérifier le gencod en passant par une chaine de caractère et non par un entier, pour vérifier le 1er chiffre du gencod et le garder; car si un entier commence par un 0 il n'est pas pris en compte.
{
	printf("Rajout des adresses...\n"); //Pour B5 et B6, le niveau de l'adresse descend à la tablette
	FILE* database = NULL;
	database = fopen("bon_encaissement_NEW_final.csv", "r");
	system("wc -l bon_encaissement_NEW_final.csv > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	FILE* newDB = NULL;
	newDB = fopen("bon_prépa_1.csv", "a");
	while (i < nbLignes)
	{
		int j=0;
		char gencod1[25]={0}, reste1[500]={0};
		gencod1[j] = getc(database);
		while (gencod1[j] != ';')
		{
			j++;
			gencod1[j]= getc(database);
		}
		gencod1[j] = '\0';
		j=0;
		reste1[j] = getc(database);
		while (reste1[j] != '\n')
		{
			if (reste1[j-1] == ';' && reste1[j] == ' ') j--;
			j++;
			reste1[j] = getc(database);
		}
		reste1[j] = '\0';
		FILE* database2 = NULL;
		database2 = fopen("gencod_adresses.csv", "r");
		system("wc -l gencod_adresses.csv > tmp2");
		FILE* tmp2 = NULL;
		tmp2 = fopen("tmp2", "r");
		int nbLignes2=0, k=0, compteur=0, count=0;
		fscanf(tmp2, "%d", &nbLignes2);
		fclose(tmp2);
		remove("tmp2");
		if (gencod1[j] != 'T')
		{
			while (k < nbLignes2)
			{
				int l=0, gencod_1=0, gencod_2=0, gencod_3=0, gencod_4=0, gencod_5=0, gencod_6=0, gencod_7=0, cle_controle=0, m=1;
				char gencod2[15]={0}, adresse[25]={0};
				gencod2[l] = getc(database2);
				while (gencod2[l] != ';')
				{
					l++;
					m++;
					gencod2[l] = getc(database2);
				}
				gencod2[l] = '\0';
				l=0;
				adresse[l] = getc(database2);
				while (adresse[l] != '\n')
				{
					l++;
					adresse[l] = getc(database2);
				}
				adresse[l-1] = '\0';
				if ((gencod1[0] == '0' && gencod1[1] == '2') || (gencod1[0] == '2' && gencod1[1] != '0'))
				{
					gencod_1= gencod1[0]-48;
					gencod_2= gencod1[1]-48;
					gencod_3= gencod1[2]-48;
					gencod_4= gencod1[3]-48;
					gencod_5= gencod1[4]-48;
					gencod_6= gencod1[5]-48;
					gencod_7= gencod1[6]-48;
					cle_controle = 10-((gencod_1+(gencod_2*3)+gencod_3+(gencod_4*3)+gencod_5+(gencod_6*3)+gencod_7)%10);
					gencod1[7] = '0';
					gencod1[8] = '0';
					gencod1[9] = '0';
					gencod1[10] = '0';
					gencod1[11] = '0';
					if (cle_controle+48 == 58) gencod1[12] = '0';
					else gencod1[12] = cle_controle+48;
				}
				if (gencod1[0] == gencod2[0] && gencod1[1] == gencod2[1] && gencod1[2] == gencod2[2] && gencod1[3] == gencod2[3] && gencod1[4] == gencod2[4] && gencod1[5] == gencod2[5] && gencod1[6] == gencod2[6] && gencod1[7] == gencod2[7] && gencod1[8] == gencod2[8] && gencod1[9] == gencod2[9] && gencod1[10] == gencod2[10] && gencod1[11] == gencod2[11])
				{
					fprintf(newDB, "%s;%s;%s\n", adresse, gencod1, reste1);
					k=nbLignes2;
				}
				else compteur++;
				k++;
			}
		}
		fclose(database2);
		if (k == compteur) // L'adresse n'a pas été trouvée dans le fichier des gencod adressés, on cherche alors la nomenclature du produit
		{
			FILE* database3 = NULL;
			database3 = fopen("gencod_nomenclatures.csv", "r");
			system("wc -l gencod_nomenclatures.csv > tmp3");
			FILE* tmp3 = NULL;
			tmp3 = fopen("tmp3", "r");
			int nbLignes3=0, p=0;
			fscanf(tmp3, "%d", &nbLignes3);
			fclose(tmp3);
			remove("tmp3");
			while (p < nbLignes3)
			{
				int a=0;
				char gencod3[20]={0}, nomenclature[30]={0};
				gencod3[a] = getc(database3);
				while (gencod3[a] != ';')
				{
					a++;
					gencod3[a] = getc(database3);
				}
				gencod3[a] = '\0';
				a=0;
				nomenclature[a] = getc(database3);
				while (nomenclature[a] != '\n')
				{
					a++;
					nomenclature[a] = getc(database3);
				}
				nomenclature[a-1] = '\0';
				//if (p == 1) printf("On chercher la noemnclature pour le produit %s\n", gencod1);
				if (gencod1[0] == gencod3[0] && gencod1[1] == gencod3[1] && gencod1[2] == gencod3[2] && gencod1[3] == gencod3[3] && gencod1[4] == gencod3[4] && gencod1[5] == gencod3[5] && gencod1[6] == gencod3[6] && gencod1[7] == gencod3[7] && gencod1[8] == gencod3[8] && gencod1[9] == gencod3[9] && gencod1[10] == gencod3[10] && gencod1[11] == gencod3[11])
				{
					fprintf(newDB, "%s;%s;%s\n", nomenclature, gencod1, reste1);
					p=nbLignes3;
				}
				else count++;
				p++;
			}
			fclose(database3);
			if (count == p) fprintf(newDB, "M1-ZZ-0-0;%s;%s\n", gencod1, reste1); // Tous les prduits n'ont pas été récupérés dans la BDD Ulis ce qui engendre que certain produits n'apparaissent pas sur le bon de préparation final
		}
		i++;
	}
	fclose(newDB);
	fclose(database);
	remove("bon_encaissement_NEW_final.csv");
	remove("bon_encaissement_NEW_NEW.csv");
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void match_position_2()
{
	printf("Récupération des noms de nomenclatures et d'adresses...\n");
	FILE* database = NULL;
	database = fopen("bon_prépa_1.csv", "r");
	system("wc -l bon_prépa_1.csv > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		char choix1[50]={0}, gencod[20]={0}, reste[500]={0}, zone_mag1[5]={0}, nomenclature1[50]={0};
		int j=0, no_mag1=0, gondole1=0, element1=0, detail=0, nom_save=0, nom_save_2=0, tablette=0;
		choix1[0] = getc(database);
		if (choix1[0] == 'M' || choix1[0] == 'R') // La ligne scanée a une adresse, il faut donc récupérer l'adresse sous forme d'adresse
		{
			fscanf(database, "%d-", &no_mag1);
			if (no_mag1 == 1 || no_mag1 == 2) fscanf(database, "%c%c-%d-%d;", &zone_mag1[0], &zone_mag1[1], &gondole1, &element1);
			else fscanf(database, "%c%c-%d;", &zone_mag1[0], &zone_mag1[1], &gondole1); // IL NE DEVRAIT PAS Y AVOIR CETTE LIGNE, AUCUN PRODUIT NE DEVRAIT ÊTRE ADRESSÉ À LA GONDOLE !! (la G2 est adressé en gondole et non en élément, à savoir pourquoi j'ai fait ça...)
			//if (choix1[0] == 'R' && zone_mag1[1] == 'V' && gondole1 == 1) fscanf(database, "-%d;", &tablette); // Applicable si le megasin est adressé à la tablette (total ou partiel)
			//else fscanf(database, ";");
		}
		else if (choix1[0] == '0') // La ligne scanée n'a pas d'adresse, il faut donc récupérer l'adresse sous forme de nomenclature
		{
			nomenclature1[j] = choix1[0];
			while (nomenclature1[j] != ';')
			{
				j++;
				nomenclature1[j] = getc(database);
			}
			nomenclature1[j] = '\0';
			j=0;
		}
		else printf("Aucune adresse ni aucune nomenclature récupérée pour la ligne %d.\n", i+2);
		gencod[j] = getc(database);
		while (gencod[j] != ';')
		{
			j++;
			gencod[j] = getc(database);
		}
		gencod[j] = '\0';
		j=0;
		reste[j] = getc(database);
		while (reste[j] != '\n')
		{
			j++;
			reste[j] = getc(database);
		}
		reste[j] = '\0';
		FILE* database2 = NULL;
		if (nb_files_def == 1) {	database2 = fopen("chemin_prepa_mono.csv", "r");system("wc -l chemin_prepa_mono.csv > tmp2");}
		else {database2 = fopen("chemin_prepa_ramasse.csv", "r");system("wc -l chemin_prepa_ramasse.csv > tmp2");}
		FILE* tmp2 = NULL;
		tmp2 = fopen("tmp2", "r");
		int nbLignes2=0, k=0, count=0;
		fscanf(tmp2, "%d", &nbLignes2);
		fclose(tmp2);
		remove("tmp2");
		while (k < nbLignes2)
		{
			int l=0, no_mag2=0, gondole2=0, element2=0;
			char choix2[50]={0}, nom_adr[100]={0}, zone_mag2[5]={0}, nomenclature2[50]={0}, caract[2]={0}, lettre[5]={0};
			choix2[0] = getc(database2);
			if (choix2[0] == 'M' || choix2[0] == 'R')
			{
				fscanf(database2, "%d-", &no_mag2);
				if (no_mag2 == 1 || no_mag2 == 2) fscanf(database2, "%c%c-%d-%d;", &zone_mag2[0], &zone_mag2[1], &gondole2, &element2);
				else fscanf(database2, "%c%c-%d-%d;", &zone_mag2[0], &zone_mag2[1], &gondole2, &element2);
			}
			else if (choix2[0] == '0')
			{
				nomenclature2[l] = choix2[0];
				while (nomenclature2[l] != ';')
				{
					l++;
					nomenclature2[l] = getc(database2);
				}
				nomenclature2[l] = '\0';
			}
			l=0;
			nom_adr[l] = getc(database2);
			if (nb_files_def > 1) caract[0] = ';';
			else caract[0] = '\n';
			while (nom_adr[l] != caract[0])
			{
				l++;
				nom_adr[l] = getc(database2);
			}
			nom_adr[l] = '\0';
			if (nb_files_def > 1)
			{
				l=0;
				lettre[l] = getc(database2);
				while (lettre[l] != '\n')
				{
					l++;
					lettre[l] = getc(database2);
				}
				lettre[l] = '\0';
			}
			if (choix1[0] == choix2[0]) // Si la première lettre correspond
			{
				int precision=0;
				if (choix1[0] == 'M' || choix1[0] == 'R') // Si c'est une adresse (Magasin ou Réserve)
				{
					FILE* newDB = NULL;
					newDB = fopen("bon_prepa_NEW.txt", "a");
					if (no_mag1 == no_mag2 && zone_mag1[0] == zone_mag2[0] && zone_mag1[1] == zone_mag2[1] && gondole1 == gondole2 && element1 == element2)
					{
						if (nb_files_def != 1)
						{
							//if (no_mag1 == 1 && zone_mag1[0] == 'A' && (gondole1 == 5 || gondole1 == 6 || gondole1 == 7 || gondole1 == 8) && element1 != 6) fprintf(newDB, "%s;%d;%s;M%d-%s-%d-%d-%d;%s;%c\n", gencod, k, reste, no_mag1, zone_mag1, gondole1, element1, tablette, nom_adr, lettre[0]); // Si c'est au rayon vin, l'adresse descend à la tablette, pas applicable à Castelnau
							//else fprintf(newDB, "%s;%d;%s;%c%d-%s-%d;%s;%c\n", gencod, k, reste, choix1[0], no_mag1, zone_mag1, gondole1, nom_adr, lettre[0]); // A ajouter si des produits sont adressés à la gondole
							if (choix1[0] == 'R' && zone_mag1[1] == 'V' && gondole1 == 1) fprintf(newDB, "%s;%d;%s;%c%d-%s-%d-%d-%d;%s;%c\n", gencod, k, reste, choix1[0], no_mag1, zone_mag1, gondole1, element1, tablette, nom_adr, lettre[0]);
							else fprintf(newDB, "%s;%d;%s;%c%d-%s-%d-%d;%s;%c\n", gencod, k, reste, choix1[0], no_mag1, zone_mag1, gondole1, element1, nom_adr, lettre[0]); // On a supprimé le numéro de la ligne au début de chaque ligne qui permettait de trier les lignes en focntion de l'ordre du chemin de prep -> A réintégrer (ramasse) -> fait ok
							k=nbLignes2;
						}
						else
						{
							//if (no_mag1 == 1 && zone_mag1[0] == 'A' && (gondole1 == 5 || gondole1 == 6 || gondole1 == 7 || gondole1 == 8) && element1 != 6) fprintf(newDB, "%s;%d;%s;M%d-%s-%d-%d-%d;%s\n", gencod, k, reste, no_mag1, zone_mag1, gondole1, element1, tablette, nom_adr); // Si c'est au rayon vin, l'adresse descend à la tablette, pas applicable à Castelnau
							if (no_mag1 == 1 || no_mag1 == 2) fprintf(newDB, "%s;%d;%s;%c%d-%s-%d-%d;%s\n", gencod, k, reste, choix1[0], no_mag1, zone_mag1, gondole1, element1, nom_adr); // On a supprimé le numéro de la ligne au début de chaque ligne qui permettait de trier les lignes en focntion de l'ordre du chemin de prep -> A réintégrer (ramasse) -> fait ok
							else fprintf(newDB, "%s;%d;%s;%c%d-%s-%d;%s\n", gencod, k, reste, choix1[0], no_mag1, zone_mag1, gondole1, nom_adr);
						}
					}
					/*else if (no_mag1 == no_mag2 && no_mag1 == 2 && zone_mag1[0] == zone_mag2[0] && gondole1 == gondole2)
					{
						if (nb_files_def != 1) fprintf(newDB, "%s;%d;%s;M%d-%s-%d;%s;%c\n", gencod, k, reste, no_mag1, zone_mag1, gondole1, nom_adr, lettre[0]);
						else fprintf(newDB, "%s;%d;%s;M%d-%s-%d;%s\n", gencod, k, reste, no_mag1, zone_mag1, gondole1, nom_adr);
					}*/
					else count++;
					fclose(newDB);
				}
				else if (choix1[0] == '0') // Sinon si c'est une nomenclature
			    {
					nom_save = k;
					precision=1;
					if (nomenclature1[1] == nomenclature2[1])
					{
						nom_save = k;
						precision=2;
						if (nomenclature1[2] == nomenclature2[2])
						{
							nom_save = k;
							precision=3;
							if (nomenclature1[3] == nomenclature2[3])
							{
								nom_save=k;
								precision=4;
								if (nomenclature1[4] == nomenclature2[4])
								{
									nom_save=k;
									precision=5;
									if (nomenclature1[5] == nomenclature2[5])
									{
										nom_save=k;
										precision=6;
										if (nomenclature1[6] == nomenclature2[6])
										{
											nom_save=k;
											precision=7;
											if (nomenclature1[7] == nomenclature2[7])
											{
												nom_save=k;
												precision=8;
										        if (nomenclature1[8] == nomenclature2[8])
										        {
											        nom_save=k;
											        precision=9;
											        if (nomenclature1[9] == nomenclature2[9])
											        {
										                nom_save=k;
										                precision=10;
										                if (nomenclature1[10] == nomenclature2[10])
										                {
										                        nom_save=k;
										                        precision=11;
										                }
											        }
										        }
											}
										}
									}
								}
							}
						}
						// Sauvegarder le nom de la nomenclature trouvée et rechercher quand même plus loin
						// S'il n'y a pas plus précis, on s'arrête là et on notera cette adresse
						// S'il y a plus précis, on continue de chercher et de sauvegarder le nom tant qu'on trouve plus précis
					}
					else count++;
				}
				/*else if (nomenclature1[1] == '4') // Pourquoi ? Le produit ira dans les non adressés et basta ?
				{
					FILE* newDB = NULL;
					newDB = fopen("bon_prepa_NEW.txt", "a");
					fprintf(newDB, "210;%s;%s;M%d-%s-%d-%d;TEXTILE/CHAUSSURE\n", gencod, reste, no_mag1, zone_mag1, gondole1, element1);
					fclose(newDB);
				}*/
				else count++;
				if (precision > detail)
				{
					detail = precision;
					nom_save_2 = nom_save;
				}
			}
			else count++;
			k++;
		}
		if (k == count)
		{
			printf("La ligne %d (%s) a une adresse ou une nomenclature qui ne fait pas partie du chemin de préparation.\n", i+2, gencod);
			FILE* newDB = NULL;
			newDB = fopen("bon_prepa_NEW.txt", "a");
			if (choix1[0] == 'M' || choix1[0] == 'R')
			{
				if (nb_files_def != 1)
				{
					if (no_mag1 == 1 || no_mag1 == 2) fprintf(newDB, "%s;%d;%s;M%d-%s-%d-%d;ADRESSE INCONNUE;W\n", gencod, k, reste, no_mag1, zone_mag1, gondole1, element1); // W étant la letttre définissant la zone non adressé de la ramasse
					else fprintf(newDB, "%s;%d;%s;M%d-%s-%d;ADRESSE INCONNUE;W\n", gencod, k, reste, no_mag1, zone_mag1, gondole1);
				}
				else
				{
					if (no_mag1 == 1 || no_mag1 == 2) fprintf(newDB, "%s;%d;%s;M%d-%s-%d-%d;ADRESSE INCONNUE\n", gencod, k, reste, no_mag1, zone_mag1, gondole1, element1); // W étant la letttre définissant la zone non adressé de la ramasse
					else fprintf(newDB, "%s;%d;%s;M%d-%s-%d;ADRESSE INCONNUE;W\n", gencod, k, reste, no_mag1, zone_mag1, gondole1);
				}
			}
			else if (choix1[0] == '0' && nb_files_def != 1) fprintf(newDB, "%s;%d;%s;no adress;no adress;L\n", gencod, k, reste);
			else if (choix1[0] == '0' && nb_files_def == 1) fprintf(newDB, "%s;%d;%s;no adress;no adress;L\n", gencod, k, reste);
			fclose(newDB);
		}
		if (choix1[0] == '0') recup_nom_adr(nom_save_2, gencod, reste);
		fclose(database2);
		i++;
	}
	fclose(database);
	remove("bon_prépa_1.csv");
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void recup_nom_adr(int ligne_nomenclature_save_2, char gencod_2[20], char reste_2[500])
{
	FILE* database = NULL;
	if (nb_files_def == 1) {	database = fopen("chemin_prepa_mono.csv", "r");system("wc -l chemin_prepa_mono.csv > tmp");}
	else {database = fopen("chemin_prepa_ramasse.csv", "r");system("wc -l chemin_prepa_ramasse.csv > tmp");}
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{	
		char nom_adr[30]={0}, libelle_nomenclature[100]={0}, caract[2]={0}, lettre[5]={0};
		int j=0;
		nom_adr[j] = getc(database);
		while (nom_adr[j] != ';')
		{
			j++;
			nom_adr[j] = getc(database);
		}
		j=0;
		libelle_nomenclature[j] = getc(database);
		if (nb_files_def > 1) caract[0] = ';';
		else caract[0] = '\n';
		while (libelle_nomenclature[j] != caract[0])
		{
			j++;
			libelle_nomenclature[j] = getc(database);
		}
		libelle_nomenclature[j] = '\0';
		if (nb_files_def > 1)
		{
			j=0;
			lettre[j] = getc(database);
			while (lettre[j] != '\n')
			{
				j++;
				lettre[j] = getc(database);
			}
			lettre[j] = '\0';
		}
		if (i == ligne_nomenclature_save_2)
		{
			i=nbLignes;
			FILE* newDB = NULL;
			newDB = fopen("bon_prepa_NEW.txt", "a");
			if (nb_files_def > 1) fprintf(newDB, "%s;%d;%s;AUCUNE ADRESSE;%s;%c\n", gencod_2, ligne_nomenclature_save_2, reste_2, libelle_nomenclature, lettre[0]);
			else fprintf(newDB, "%s;%d;%s;AUCUNE ADRESSE;%s\n", gencod_2, ligne_nomenclature_save_2, reste_2, libelle_nomenclature);
			fclose(newDB);
		}
		i++;
	}
	fclose(database);
}

void rangement_produits() // Dans le count=1, les EAN 13 avec un 0 au début (type flegs/métiers) sont supprimés (juste le 0), à rétintégrer ? -> fait ok mais certain gencod ont des 0 aussi avant d'autres chiffres et ce ne sont pas des poids variable -> Trouver un autre moyen de le récupérer (adieu le LLD);
{
	if (count == 0) printf("Rangement des articles par gencod...\n");
	else printf("Rangement des articles dans l'ordre du chemin de préparation...\n"); // Rangement des articles dans l'ordre du numéro de la ligne qui apparaît en première colone
	FILE* database = NULL;
	database = fopen("bon_prepa_NEW.txt", "r");
	system("wc -l bon_prepa_NEW.txt > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0, no_adresse[3200]={0}, position[5]={0};
	char gencod[3200][1000]={0}, reste[3200][1000]={0};
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		int j=0;
		if (count == 0)
		{
			int a=0;
			gencod[i][a] = getc(database);
			while (gencod[i][a] != ';')
			{
				a++;
				gencod[i][a] = getc(database);
			}
			fscanf(database, "%d;", &position[i]);
		}
		else fscanf(database, "%d;", &no_adresse[i]);
		reste[i][j] = getc(database);
		while (reste[i][j] != '\n')
		{
			j++;
			reste[i][j] = getc(database);
		}
		reste[i][j] = '\0';
		i++;
	}
	fclose(database);
	int j=0, no_adresse_temp=0, d=0, position_temp=0;
	char gencod_temp[3200]={0};
	char reste2[3200]={0};
	for (j=0; count == 0 && j<i-1; j++)
	{
		int k=0;
		for (k=0; k<i; k++)
		{
			int b=0;
			if (count == 0)
			{
				if (((gencod[k][0] > gencod[k+1][0]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] > gencod[k+1][1]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] > gencod[k+1][2]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] > gencod[k+1][3]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] > gencod[k+1][4]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] > gencod[k+1][5]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] > gencod[k+1][6]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] == gencod[k+1][6] &&  gencod[k][7] > gencod[k+1][7]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] == gencod[k+1][6] &&  gencod[k][7] == gencod[k+1][7] && gencod[k][8] > gencod[k+1][8]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] == gencod[k+1][6] &&  gencod[k][7] == gencod[k+1][7] && gencod[k][8] == gencod[k+1][8] && gencod[k][9] > gencod[k+1][9]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] == gencod[k+1][6] &&  gencod[k][7] == gencod[k+1][7] && gencod[k][8] == gencod[k+1][8] && gencod[k][9] == gencod[k+1][9] && gencod[k][10] > gencod[k+1][10]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] == gencod[k+1][6] &&  gencod[k][7] == gencod[k+1][7] && gencod[k][8] == gencod[k+1][8] && gencod[k][9] == gencod[k+1][9] && gencod[k][10] == gencod[k+1][10] && gencod[k][11] > gencod[k+1][11]) || (gencod[k][0] == gencod[k+1][0] && gencod[k][1] == gencod[k+1][1] && gencod[k][2] == gencod[k+1][2] && gencod[k][3] == gencod[k+1][3] && gencod[k][4] == gencod[k+1][4] && gencod[k][5] == gencod[k+1][5] && gencod[k][6] == gencod[k+1][6] &&  gencod[k][7] == gencod[k+1][7] && gencod[k][8] == gencod[k+1][8] && gencod[k][9] == gencod[k+1][9] && gencod[k][10] == gencod[k+1][10] && gencod[k][11] == gencod[k+1][11] && gencod[k][12] > gencod[k+1][12])) && k != i-1) // Le gencod est descendu tout en bas (c'est le plus haut) + faire la comparaison de tous les chiffres du gencod
				{
					gencod_temp[b] = gencod[k+1][b]; // On copie dans gencod_temp le gencod[k]
					while (gencod_temp[b] != ';')
					{
						b++;
						gencod_temp[b] = gencod[k+1][b];
					}
					gencod_temp[b+1] = '\0';
					b=0;
					gencod[k+1][b] = gencod[k][b]; // On met alors dans le gencod[k+1] le gencod[k]
					while (gencod[k+1][b] != ';')
					{
						b++;
						gencod[k+1][b] = gencod[k][b];
					}
					gencod[k+1][b+1] = '\0';
					b=0;
					gencod[k][b] = gencod_temp[b]; // Puis met dans gencod[k] on met gencod_temp. Au final, on a inversé les gencod[k]  et gencod[k+1]
					while (gencod[k][b] != ';')
					{
						b++;
						gencod[k][b] = gencod_temp[b];
					}
					gencod[k][b+1] = '\0';
					position_temp = position[k+1]; // On fait pareil avec la position du produit
					position[k+1] = position[k];
					position[k] = position_temp;
					int b=0;
					for (b=0; b<500; b++) // Et pareil aussi avec le reste de la ligne pour inverser toutes les données des deux lignes
					{
						reste2[b] = reste[k+1][b];
						reste[k+1][b] = reste[k][b];
						reste[k][b] = reste2[b];
					}
				}
			}
			else
			{
				if (no_adresse[k] > no_adresse[k+1] && k != i-1)
				{
					no_adresse_temp = no_adresse[k+1];
					no_adresse[k+1] = no_adresse[k];
					no_adresse[k] = no_adresse_temp;
					int b=0;
					for (b=0; b<500; b++)
					{
						reste2[b] = reste[k+1][b];
						reste[k+1][b] = reste[k][b];
						reste[k][b] = reste2[b];
					}
				}
			}
		}
	}
	for (d=0; d<i; d++)
	{
		FILE* newDB = NULL;
		newDB = fopen("bon_prepa.txt", "a");
		if (count == 0) fprintf(newDB, "%d;%s%s\n", position[d], gencod[d], reste[d]);
		else fprintf(newDB, "%s\n", reste[d]);
		fclose(newDB);
	}
	system("mv bon_prepa.txt ./bon_prepa_NEW.txt");
	count=1;
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void ajout_DLC()
{
	printf ("Ajout de la DLC...\n");
	FILE* database = NULL;
	database = fopen("bon_prepa_NEW.txt", "r");
	system("wc -l bon_prepa_NEW.txt > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0, a=0, jour1=0, mois1=0, annee1=0, count=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	// Scanner les premières infos avec les différentes vbariables pour ensuite récupérer la date de la commande
	char txt1[10]={0}, txtplb1[1000]={0};
	txtplb1[a] = getc(database);
	while (count < 8)
	{
		a++;
		txtplb1[a] = getc(database);
		if (txtplb1[a] == ';') count++;
	}
	a=0;
	txt1[a] = getc(database);
	while (txt1[a] != ' ')
	{
		a++;
		txt1[a] = getc(database);
	}
	fscanf(database, "%d/%d/%d -", &jour1, &mois1, &annee1); // Récupère la date de la commande afin de calculer la DLC
	fclose(database);
	database =  fopen("bon_prepa_NEW.txt", "r");
	FILE* newDB = NULL;
	newDB = fopen("bon_prepa_dlc.txt", "a");
	if (nb_files_def == 1) fprintf(newDB, "M,%d,%d,%d,%d\n", nb_files_def, nbLignes, qte_totale, subs_mono);
	while (i < nbLignes)
	{
		int j=0, k=0, nbLignes2=0, z=0;
		char gencod1[20]={0}, reste1[1000]={0};
		gencod1[j] = getc(database);
		while (gencod1[j] != ';')
		{
			j++;
			gencod1[j] = getc(database);
		}
		gencod1[j] = '\0';
		/*if (gencod1[0] == '2' && gencod1[6] == '0' && gencod1[7] == '0' && gencod1[8] == '0' && gencod1[9] == '0' && gencod1[10] == '0')
		{
			for (int a=12;a>0;a--)
			{
				gencod1[a] = gencod1[a-1];
			}
			gencod1[0] = '0';
		}*/
		j=0;
		reste1[j] = getc(database);
		while (reste1[j] != '\n')
		{
			j++;
			reste1[j] = getc(database);
		}
		reste1[j] = '\0';
		if (nb_files_def == 1) reste1[j-1] = '\0';
		FILE* database2 = NULL;
		database2 = fopen("gencod_nomenclatures.csv", "r"); // J'ouvre le fichier des correspondances entre les gencod et les nomenclatures
		system("wc -l gencod_nomenclatures.csv > tmp2");
		FILE* tmp2 = NULL;
		tmp2 = fopen("tmp2", "r");
		fscanf(tmp2, "%d", &nbLignes2);
		fclose(tmp2);
		remove("tmp2");
		while (k < nbLignes2) // Je cherche parmi toute la BDD, la correspondance avec mon article
		{
			int l=0;
			char gencod2[20]={0}, nomenclature[50]={0};
			gencod2[l] = getc(database2);
			while (gencod2[l] != ';')
			{
				l++;
				gencod2[l] = getc(database2);
			}
			gencod2[l] = '\0';
			l=0;
			nomenclature[l] = getc(database2);
			while (nomenclature[l] != '\n')
			{
				l++;
				nomenclature[l] = getc(database2);
			}
			if (gencod1[0] == gencod2[0] && gencod1[1] == gencod2[1] && gencod1[2] == gencod2[2] && gencod1[3] == gencod2[3] && gencod1[4] == gencod2[4] && gencod1[5] == gencod2[5] && gencod1[6] == gencod2[6] && gencod1[7] == gencod2[7] && gencod1[8] == gencod2[8] && gencod1[9] == gencod2[9] && gencod1[10] == gencod2[10] && gencod1[11] == gencod2[11])
			{
				if (nomenclature[0] == '0' && nomenclature[1] == '2') // Nomenclature 02 : PRODUITS FRAIS
				{
					if (nomenclature[2] == '0' && nomenclature[3] == '5' && nomenclature[4] == '2' && nomenclature[5] == '0') // PATISSERIE -> 2J
					{
						get_DLC(jour1, mois1, annee1, 2);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if (((nomenclature[2] == '2' && nomenclature[3] == '5') && ((nomenclature[4] == '3' && nomenclature[5] == '3') || (nomenclature[4] == '2' && nomenclature[5] == '8'))) || (nomenclature[2] == '4' && ((nomenclature[3] == '0' && ((nomenclature[4] == '3' && ((nomenclature[5] == '8') || (nomenclature[5] == '9' && nomenclature[6] != '1' && nomenclature[7] != '5'))) || (nomenclature[4] == '4' && (nomenclature[5] == '0' || nomenclature[5] == '1')))) || nomenclature[3] == '5')))
					{
						get_DLC(jour1, mois1, annee1, 10);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if (nomenclature[2] == '2' && nomenclature[3] == '5' && nomenclature[4] == '3' && (nomenclature[5] == '0' || nomenclature[5] == '1'))
					{
						get_DLC(jour1, mois1, annee1,20);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if ((nomenclature[2] == '1' || nomenclature[2] == '2') && (nomenclature[3] == '0' || (nomenclature[3] == '5' && nomenclature[4] == '3' && nomenclature[5] == '2' && nomenclature[6] == '0' && nomenclature[7] == '5')))
					{
						get_DLC(jour1, mois1, annee1, 7);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if (nomenclature[2] == '2' && nomenclature[3] == '5' && nomenclature[4] == '2' && nomenclature[5] == '9')
					{
						get_DLC(jour1, mois1, annee1, 8);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if (nomenclature[2] == '3' && nomenclature[3] == '0' && nomenclature[4] == '3' && nomenclature[5] == '5' && nomenclature[6] == '0' && nomenclature[7] == '5')
					{
						get_DLC(jour1, mois1, annee1, 5);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if (nomenclature[2] == '4' && nomenclature[3] == '0' && nomenclature[4] == '3' && nomenclature[5] == '9' && nomenclature[6] == '1' && nomenclature[7] == '5')
					{
						get_DLC(jour1, mois1, annee1, 6);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if (nomenclature[2] == '4' && nomenclature[3] == '0' && nomenclature[4] == '3' && nomenclature[5] == '9')
					{
						get_DLC(jour1, mois1, annee1, 10);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else if ((nomenclature[2] == '5' || nomenclature[2] == '6') && (nomenclature[3] == '0' || nomenclature[3] == '5'))
					{
						get_DLC(jour1, mois1, annee1, 4);
						fprintf(newDB, "%s;%s;%02d/%02d/%d\n", gencod1, reste1, jour2, mois2, annee2);
					}
					else fprintf(newDB, "%s;%s;00/00/0000\n", gencod1, reste1);
				}
				else fprintf(newDB, "%s;%s;00/00/0000\n", gencod1, reste1);
				k=nbLignes2;
			}
			else z++;
			k++;
		}
		fclose(database2);
		if (z == k) fprintf(newDB, "%s;%s;00/00/0000\n", gencod1, reste1);
		i++;
	}
	fclose(newDB);
	fclose(database);
	remove("bon_prepa_NEW.txt");
	system("cp bon_prepa_dlc.txt ./bon_prepa.txt");
	remove("bon_prepa_dlc.txt");
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
	if (nb_files_def > 1) assemble_produits_plusieurs_clients();
}

void get_DLC(int jour, int mois, int annee, int addj)
{
	int nb_jours_mois[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
	jour += addj;
	if (jour > nb_jours_mois[mois-1]) // Si on dépasse du nombre de jours dans le même mois
	{
		jour -= nb_jours_mois[mois-1]; // On décrémente la limite du nombre de jour du mois d'avant et le résulat et le jour de la DLC à respecter
		if (mois <= 11) mois++;
		else
		{
			mois = 1;
			annee += 1;
		}
	}
	jour2=jour;
	mois2=mois;
	annee2=annee;
}

void assemble_produits_plusieurs_clients()
{
	printf ("Agrégation des produits...\n");
	FILE* database = NULL;
	database = fopen("bon_prepa.txt", "r");
	system("wc -l bon_prepa.txt > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0, pass=0, p=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		for (p=0;p<pass;p++) // scanner ce qui a déjà été récupéré dans le pass !
		{
			int r=0;
			char pbl[500]={0};
			pbl[r] = getc(database);
			while (pbl[r] != '\n')
			{
				r++;
				pbl[r] = getc(database);
			}
		}
		pass=0;
		int j=0, qte1=0, k=0, a=0;
		char gencod1[20]={0}, libelle1[200]={0}, prix1[10]={0}, prixKG1[10]={0}, subs1[5]={0}, poids1[10]={0}, poids12[10]={0}, reste1[100]={0}, heure1[20]={0}, no_cde1[10]={0}, reste12[200]={0}, type_retrait1[20]={0};
		gencod1[j] = getc(database);
		while (gencod1[j] != ';')
		{
			j++;
			gencod1[j] = getc(database);
		}
		gencod1[j] = '\0';
		j=0;
		libelle1[j] = getc(database);
		while (libelle1[j] != ';')
		{
			j++;
			libelle1[j] = getc(database);
		}
		libelle1[j] = '\0';
		j=0;
		prix1[j] = getc(database);
		while (prix1[j] != ';')
		{
			j++;
			prix1[j] = getc(database);
		}
		prix1[j] = '\0';
		j=0;
		prixKG1[j] = getc(database);
		while (prixKG1[j] != ';')
		{
			j++;
			prixKG1[j] = getc(database);
		}
		prixKG1[j] = '\0';
		j=0;
		fscanf(database, "%d;", &qte1);
		subs1[j] = getc(database);
		while (subs1[j] != ';')
		{
			j++;
			subs1[j] = getc(database);
		}
		subs1[j] = '\0';
		j=0;
		poids1[j] = getc(database);
		while (poids1[j] != ';')
		{
			j++;
			poids1[j] = getc(database);
		}
		poids1[j] = '\0';
		j=0;
		poids12[j] = getc(database);
		while (poids12[j] != ';')
		{
			j++;
			poids12[j] = getc(database);
		}
		poids12[j] = '\0';
		j=0;
		reste1[j] = getc(database);
		while (reste1[j] != '-')
		{
			j++;
			reste1[j] = getc(database);
		}
		reste1[j-1] = '\0';
		j=0;
		fscanf(database, " ");
		heure1[j] = getc(database);
		while (heure1[j] != ',')
		{
			j++;
			heure1[j] = getc(database);
		}
		heure1[j] = '\0';
		j=0;
		no_cde1[j] = getc(database);
		while (no_cde1[j] != ',')
		{
			j++;
			no_cde1[j] = getc(database);
		}
		no_cde1[j] = '\0';
		j=0;
		type_retrait1[j] = getc(database);
		while (type_retrait1[j] != ',')
		{
			j++;
			type_retrait1[j] = getc(database);
		}
		type_retrait1[j] = '\0';
		j=0;
		reste12[j] = getc(database);
		while (reste12[j] != '\n')
		{
			j++;
			reste12[j] = getc(database);
		}
		reste12[j] = '\0';
		FILE* database2 = NULL;
		database2 = fopen("bon_prepa.txt", "r");
		for (a=0;a<i+1;a++) // Il faudra ignorer les lignes au-dessus de celle qu'on est en train de vérifier + celles plus haut
		{
			char pbl[500]={0};
			int b=0;
			pbl[b] = getc(database2);
			while (pbl[b] != '\n')
			{
				b++;
				pbl[b] = getc(database2);
			}
		}
		while (k < nbLignes-(i+1))
		{
			int l=0, qte2=0;
			char gencod2[20]={0}, libelle2[300]={0}, prix2[10]={0}, prixKG2[10]={0}, subs2[5]={0}, poids2[10]={0}, poids21[10]={0}, reste2[100]={0}, heure2[20]={0}, no_cde2[10]={0}, reste22[200]={0}, type_retrait2[20]={0};
			gencod2[l] = getc(database2);
			while (gencod2[l] != ';')
			{
				l++;
				gencod2[l] = getc(database2);
			}
			gencod2[l] = '\0';
			l=0;
			libelle2[l] = getc(database2);
			while (libelle2[l] != ';')
			{
				l++;
				libelle2[l] = getc(database2);
			}
			libelle2[l] = '\0';
			l=0;
			prix2[l] = getc(database2);
			while (prix2[l] != ';')
			{
				l++;
				prix2[l] = getc(database2);
			}
			prix2[l] = '\0';
			l=0;
			prixKG2[l] = getc(database2);
			while (prixKG2[l] != ';')
			{
				l++;
				prixKG2[l] = getc(database2);
			}
			prixKG2[l] = '\0';
			l=0;
			fscanf(database2, "%d;", &qte2);
			subs2[l] = getc(database2);
			while (subs2[l] != ';')
			{
				l++;
				subs2[l] = getc(database2);
			}
			subs2[l] = '\0';
			l=0;
			poids2[l] = getc(database2);
			while (poids2[l] != ';')
			{
				l++;
				poids2[l] = getc(database2);
			}
			poids2[l] = '\0';
			l=0;
			poids21[l] = getc(database2);
			while (poids21[l] != ';')
			{
				l++;
				poids21[l] = getc(database2);
			}
			poids21[l] = '\0';
			l=0;
			reste2[l] = getc(database2);
			while (reste2[l] != '-')
			{
				l++;
				reste2[l] = getc(database2);
			}
			reste2[l] = '\0';
			l=0;
			fscanf(database2, " ");
			heure2[l] = getc(database2);
			while (heure2[l] != ',')
			{
				l++;
				heure2[l] = getc(database2);
			}
			heure2[l] = '\0';
			l=0;
			no_cde2[l] = getc(database2);
			while (no_cde2[l] != ',')
			{
				l++;
				no_cde2[l] = getc(database2);
			}
			no_cde2[l] = '\0';
			l=0;
			type_retrait2[l] = getc(database2);
			while (type_retrait2[l] != ',')
			{
				l++;
				type_retrait2[l] = getc(database2);
			}
			type_retrait2[l] = '\0';
			l=0;
			reste22[l] = getc(database2);
			while (reste22[l] != '\n')
			{
				l++;
				reste22[l] = getc(database2);
			}
			reste22[l] = '\0';
			if (gencod1[0] == gencod2[0] && gencod1[1] == gencod2[1] && gencod1[2] == gencod2[2] && gencod1[3] == gencod2[3] && gencod1[4] == gencod2[4] && gencod1[5] == gencod2[5] && gencod1[6] == gencod2[6] && gencod1[7] == gencod2[7] && gencod1[8] == gencod2[8] && gencod1[9] == gencod2[9] && gencod1[10] == gencod2[10] && gencod1[11] == gencod2[11]) 
			{
				FILE* gen_temp = NULL;
				gen_temp = fopen("no_cde_temp.txt", "a");
				if (i+1 == k+a) fprintf(gen_temp, "%s+%s", no_cde1, no_cde2);
				else fprintf(gen_temp, "+%s", no_cde2);
				fclose(gen_temp);
				FILE* qte_temp = NULL;
				qte_temp = fopen("qte_temp.txt", "a");
				if (i+1 == k+a) fprintf(qte_temp, "%d+%d", qte1, qte2);
				else fprintf(qte_temp, "+%d", qte2);
				fclose(qte_temp);
				FILE* subs_temp = NULL;
				subs_temp = fopen("subs_temp.txt", "a");
				if (i+1 == k+a) fprintf(subs_temp, "%s+%s", subs1, subs2);
				else fprintf(subs_temp, "+%s", subs2);
				fclose(subs_temp);
				FILE* heure_temp = NULL;
				heure_temp = fopen("heure_temp.txt", "a");
				if (i+1 == k+a) fprintf(heure_temp, "%s+%s", heure1, heure2); // Changer les int par des char
				else fprintf(heure_temp, "+%s", heure2);
				fclose(heure_temp);
				FILE* retrait_temp = NULL;
				retrait_temp = fopen("retrait_temp.txt", "a");
				if (i+1 == k+a) fprintf(retrait_temp, "%s+%s", type_retrait1, type_retrait2);
				else fprintf(retrait_temp, "+%s", type_retrait2);
				fclose(retrait_temp);
				qte1 += qte2; // qte1 devient qte_totale
				pass++;
			}
			//printf("Le gencod %s de la ligne %d correspond au gencod %s de la ligne %d\n", gencod1, i+2, gencod2, k+a+1);
			k++;
		}
		fclose(database2);
		if (pass >= 1) // On est passé dans l'aggrégation, il faudra plus tard scanner automatiquement les lignes d'après aussi si ont les a déja scanner (au moins 3 produits pareil)
		{
			int z=0;
			char no_cdes[5000]={0}, qtes[1000]={0}, subs[2000]={0}, heures[3000]={0}, retraits[6000]={0};
			FILE* temp = NULL;
			temp = fopen("no_cde_temp.txt", "a");
			fprintf(temp, "\n");
			fclose(temp);
			temp = fopen("no_cde_temp.txt", "r");
			no_cdes[z] = getc(temp);
			while (no_cdes[z] != '\n')
			{
				z++;
				no_cdes[z] = getc(temp);
			}
			no_cdes[z] = '\0';
			z=0;
			fclose(temp);
			temp = fopen("qte_temp.txt", "a");
			fprintf(temp, "\n");
			fclose(temp);
			temp = fopen("qte_temp.txt", "r");
			qtes[z] = getc(temp);
			while (qtes[z] != '\n')
			{
				z++;
				qtes[z] = getc(temp);
			}
			qtes[z] = '\0';
			z=0;
			fclose(temp);
			temp = fopen("subs_temp.txt", "a");
			fprintf(temp, "\n");
			fclose(temp);
			temp = fopen("subs_temp.txt", "r");
			subs[z] = getc(temp);
			while (subs[z] != '\n')
			{
				z++;
				subs[z] = getc(temp);
			}
			subs[z] = '\0';
			z=0;
			fclose(temp);
			temp = fopen("heure_temp.txt", "a");
			fprintf(temp, "\n");
			fclose(temp);
			temp = fopen("heure_temp.txt", "r");
			heures[z] = getc(temp);
			while (heures[z] != '\n')
			{
				z++;
				heures[z] = getc(temp);
			}
			heures[z] = '\0';
			z=0;
			fclose(temp);
			temp = fopen("retrait_temp.txt", "a");
			fprintf(temp, "\n");
			fclose(temp);
			temp = fopen("retrait_temp.txt", "r");
			retraits[z] = getc(temp);
			while (retraits[z] != '\n')
			{
				z++;
				retraits[z] = getc(temp);
			}
			retraits[z] = '\0';
			fclose(temp);
			FILE* newDB = NULL;
			newDB = fopen("bon_prepa_NEW.txt", "a");
			fprintf(newDB, "%s;%s;%s;%s;%d;%s;%s;%s;%s;%s,%s,%s,%s,%s\n", gencod1, libelle1, prix1, prixKG1, qte1, qtes, subs, poids1, poids12, reste1, heures, no_cdes, retraits, reste12);
			// Il faudrait afficher l'heure de la commande qui part le plus tôt dans une prochaine version
			fclose(newDB);
			system("rm no_cde_temp.txt");
			system("rm qte_temp.txt");
			system("rm subs_temp.txt");
			system("rm heure_temp.txt");
			system("rm retrait_temp.txt");
			i += pass;
		}
		else
		{
			FILE* newDB = NULL;
			newDB = fopen("bon_prepa_NEW.txt", "a");
			fprintf(newDB, "%s;%s;%s;%s;%d;0;%s;%s;%s;%s,%s,%s,%s,%s\n", gencod1, libelle1, prix1, prixKG1, qte1, subs1, poids1, poids12, reste1, heure1, no_cde1, type_retrait1, reste12);
			fclose(newDB);
		}
		i++;
	}
	fclose(database);
	system("mv bon_prepa_NEW.txt ./bon_prepa.txt");
	system("wc -l bon_prepa.txt > tmp");
	tmp = fopen("tmp", "r");
	int nb_articles=0, h=0;
	fscanf(tmp, "%d", &nb_articles);
	fclose(tmp);
	tmp = fopen("bon_prepa_NEW.txt", "a");
	fprintf(tmp, "R,%d,%d,%d\n", nb_files_def, nb_articles, qte_totale);
	fclose(tmp);
	assemble_tri_commandes();
	remove("tmp");
	tmp = fopen("bon_prepa.txt", "r");
	while (h < nb_articles)
	{
		int g=0;
		char poubelle[800]={0};
		poubelle[g] = getc(tmp);
		while (poubelle[g] != '\n')
		{
			g++;
			poubelle[g] = getc(tmp);
		}
		FILE* newDB = NULL;
		newDB = fopen("bon_prepa_NEW.txt", "a");
		fprintf(newDB, "%s", poubelle);
		fclose(newDB);
		h++;
	}
	fclose(tmp);
	system("mv bon_prepa_NEW.txt ./bon_prepa.txt");
	printf("\t\t\t\t\t\t\t\tTerminé.\n");
}

void assemble_tri_commandes()
{
	FILE* tri_cdes = NULL;
	tri_cdes = fopen("tri_cde.txt", "r");
	FILE* tri_heures = NULL;
	tri_heures = fopen("tri_heures.txt", "r");
	FILE* tri_nb_pdts = NULL;
	tri_nb_pdts = fopen("tri_nb_pdts.txt", "r");
	int a=0;
	while (a < nb_files_def)
	{
		int j=0, nb_pdts=0;
		char no_cde[10]={0}, heure[10]={0};
		no_cde[j] = getc(tri_cdes);
		while (no_cde[j] != '\n')
		{
			j++;
			no_cde[j] = getc(tri_cdes);
		}
		no_cde[j] = '\0';
		j=0;
		heure[j] = getc(tri_heures);
		while (heure[j] != '\n')
		{
			j++;
			heure[j] = getc(tri_heures);
		}
		heure[j] = '\0';
		fscanf(tri_nb_pdts, "%d\n", &nb_pdts);
		FILE* newDB = NULL;
		newDB = fopen("tri_final.txt", "a");
		fprintf(newDB, "%s,%s,%d\n", no_cde, heure, nb_pdts);
		fclose(newDB);
		a++;
	}
	fclose(tri_cdes);
	fclose(tri_heures);
	fclose(tri_nb_pdts);
	remove("tri_cde.txt");
	remove("tri_heures.txt");
	remove("tri_nb_pdts.txt");
	tri_commandes();
}

void tri_commandes()
{
	FILE* database = NULL;
	database = fopen("tri_final.txt", "r");
	int a=0, nb_pdts[1500]={0}, nb_pdts_temp=0;;
	char no_cde[1500][10]={0}, heure[1500][10]={0}, no_cde_temp[10]={0}, heure_temp[10]={0};
	while (a < nb_files_def)
	{
		int j=0;
		no_cde[a][j] = getc(database);
		while (no_cde[a][j] != ',')
		{
			j++;
			no_cde[a][j] = getc(database);
		}
		no_cde[a][j] = '\0';
		j=0;
		heure[a][j] = getc(database);
		while (heure[a][j] != ',')
		{
			j++;
			heure[a][j] = getc(database);
		}
		heure[a][j] = '\0';
		fscanf(database, "%d\n", &nb_pdts[a]);
		a++;
	}
	fclose(database);
	int d=0;
	for (d=0;d<nb_files_def;d++)
	{
		int b=0;
		for (b=0;b<nb_files_def-1;b++)
		{
			if (heure[b][0] > heure[b+1][0] || (heure[b][0] == heure[b+1][0] && heure[b][1] > heure[b+1][1]) || (heure[b][0] == heure[b+1][0] && heure[b][1] == heure[b+1][1] && heure[b][3] > heure[b+1][3]))
			{
				int c=0;
				for (c=0;c<8;c++)
				{
					no_cde_temp[c] = no_cde[b][c];
				 	no_cde[b][c] = no_cde[b+1][c];
				 	no_cde[b+1][c] = no_cde_temp[c];
				}
				for (c=0;c<5;c++)
				{
					heure_temp[c] = heure[b][c];
				 	heure[b][c] = heure[b+1][c];
				 	heure[b+1][c] = heure_temp[c];
				}
				nb_pdts_temp = nb_pdts[b];
				nb_pdts[b] = nb_pdts[b+1];
				nb_pdts[b+1] = nb_pdts_temp;
			}	
		}
	}
	FILE* newDB = NULL;
	newDB = fopen("bon_prepa_NEW.txt", "a");
	for (int b=0;b<nb_files_def;b++)
	{
		if (nb_files_def-b > 1) fprintf(newDB, "%s,", no_cde[b]);
		else fprintf(newDB, "%s\n", no_cde[b]);
	}
	fclose(newDB);
	remove("tri_final.txt");
}

void crea_anticipation()
{
	printf("Création du bon d'anticipation...\n");
	remove("bon_anticipation.txt");
	FILE* database = NULL;
	database = fopen("bon_prepa.txt", "r");
	system("wc -l bon_prepa.txt > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0, j=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	char pbl[1500]={0};
	pbl[j] = getc(database);
	while (pbl[j] != '\n') // Récupère la première ligne (en-tête M,1,...)
	{
		j++;
		pbl[j] = getc(database);
	}
	/*char lettre_anticip[2]={0};
	printf("Choisissez le rayon a anticiper. Entrez la lettre correspondante au rayon comme suit et appuyez sur entrée.\nA : BAZAR & TEXTILE\nB : BOULANGERIE\nC : BVP\nD : CHOCOLATS A OFFRIR\nE : POISSIONNERIE\nF : TRAITEUR CHAUD\n");
	scanf("%c", &lettre_anticip[0]);*/
	while (i < nbLignes-1)
	{
		char gencod1[20]={0}, reste[1500]={0};
		int k=0, l=0, nbLignes2=0, drive=0;
		gencod1[k] = getc(database);
		while (gencod1[k] != ';')
		{
			k++;
			gencod1[k] = getc(database);
		}
		gencod1[k] = '\0';
		k=0;
		/*pbl[k] = getc(database);
		while (pbl[k] != ';')
		{
			k++;
			pbl[k] = getc(database);
		}
		k=0;*/
		reste[k] = getc(database);
		while (reste[k] != '\n')
		{
			k++;
			reste[k] = getc(database);
			if (reste[k-3] == ';' && reste[k-2] == 'R' && reste[k-1] == '1' && reste[k] == '-') drive=1;
		}
		reste[k] = '\0';
		if (drive == 0)
		{
			FILE* database2 = NULL;
			database2 = fopen("gencod_nomenclatures.csv", "r");
			system("wc -l gencod_nomenclatures.csv > tmp2");
			FILE* tmp2 = NULL;
			tmp2 = fopen("tmp2", "r");
			fscanf(tmp2, "%d", &nbLignes2);
			fclose(tmp2);
			remove("tmp2");
			while (l < nbLignes2)
			{
				char gencod2[20]={0}, nom[30]={0};
				int m=0;
				gencod2[m] = getc(database2);
				while (gencod2[m] != ';')
				{
					m++;
					gencod2[m] = getc(database2);
				}
				gencod2[m] = '\0';
				m=0;
				nom[m] = getc(database2);
				while (nom[m] != '\n')
				{
					m++;
					nom[m] = getc(database2);
				}
				nom[m] = '\0';
				if (gencod1[0] == gencod2[0] && gencod1[1] == gencod2[1] && gencod1[2] == gencod2[2] && gencod1[3] == gencod2[3] && gencod1[4] == gencod2[4] && gencod1[5] == gencod2[5] && gencod1[6] == gencod2[6] && gencod1[7] == gencod2[7] && gencod1[8] == gencod2[8] && gencod1[9] == gencod2[9] && gencod1[10] == gencod2[10] && gencod1[11] == gencod2[11])
				{
					//if (nom[0] == '0' && nom[1] == '1' && nom[2] == '2' && nom[3] == '0' && nom[4] == '1' && ((nom[5] == '5' && (nom[6] == '0' || nom[6] == '1' || nom[6] == '2' || nom[6] == '3' || (nom[6] == '4' && nom[7] == '5'))) || (nom[5] == '6' && nom[7] == '5' && (nom[6] == '0' || nom[6] == '1' || (nom[6] == '2' && nom[8] == '0' && nom[9] == '5'))) || (nom[5] == '7' && (nom[6] == '1' || nom[6] == '2')))) // Anticipation beauté
					FILE* newDB = NULL;
					newDB = fopen("bon_anticipation.txt", "a");
					if (nom[0] == '0' && (nom[1] == '3' || nom[1] == '4')) fprintf(newDB, "%s;%s;A\n", gencod1, reste); // Bazar & Textile
					else if (nom[0] == '0' && nom[1] == '2' && nom[2] == '6' && nom[3] == '0') fprintf(newDB, "%s;%s;B\n", gencod1, reste); // Boucherie
					else if (nom[0] == '0' && nom[1] == '2' && nom[2] == '0' && nom[3] == '5') fprintf(newDB, "%s;%s;C\n", gencod1, reste); // BVP
					else if (nom[0] == '0' && nom[1] == '2' && nom[2] == '6' && nom[3] == '5' && nom[4] == '5' && (nom[5] == '1' || nom[5] == '2')) fprintf(newDB, "%s;%s;D\n", gencod1, reste); // Poissonnerie
					else if (nom[0] == '0' && nom[1] == '2' && nom[2] == '4' && nom[3] == '5' && nom[4] == '4' && (nom[5] == '2' || nom[5] == '4')) fprintf(newDB, "%s;%s;E\n", gencod1, reste); // Traiteur
					else if (nom[0] == '0' && nom[1] == '2' && nom[2] == '2' && nom[3] == '0') fprintf(newDB, "%s;%s;F\n", gencod1, reste); // Fromage Coupe
					fclose(newDB);
					//if (nom[0] == '0' && nom[1] == '1' && nom[2] == '0' && nom[3] == '5' && nom[4] == '0' && nom[5] == '2' && nom[6] == '4') // Chocolats à offrir
					l = nbLignes2;
				}
				l++;
			}
			fclose(database2);
		}
		i++;
	}
	fclose(database);
	printf("\t\t\t\t\t\t\t\tTerminé.\n");	
}
