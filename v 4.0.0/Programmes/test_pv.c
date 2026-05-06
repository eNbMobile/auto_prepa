#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

// Chemin de préparation : sert à éliminer les espaces entre les adresses, les "Voir le détail" et tout ce qui parasite autour

int main()
{
	/*FILE* database = NULL;
	database = fopen("bon_prepa.txt", "r");
	system("wc -l bon_prepa.txt > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		char reste[100]={0};
		int j=0, count=0;
		reste[j] = getc(database);
		while (reste[j] != '\n')
		{
			j++;
			reste[j] = getc(database);
			if (reste[j] == ';') count++;
		}
		reste[j] = '\0';
		if (count ==11) printf("Ligne %d\n", i+1);
		i++;
	}
	fclose(database);
	return 0;*/
	
	/*FILE* database = NULL;
	database = fopen("zones_de_collecte.csv", "r");
	system("wc -l zones_de_collecte.csv > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	char lettre[5]={0};
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		char reste[30]={0}, reste2[100]={0};
		int j=0, k=0;
		reste[j] = getc(database);
		while (reste[j] != ';')
		{
			j++;
			reste[j] = getc(database);
		}
		if (j < 2) {lettre[0] = reste[0];lettre[1]='\0';}
		reste[j] = '\0';
		reste2[k] = getc(database);
		while (reste2[k] != '\n')
		{
			k++;
			reste2[k] = getc(database);
		}
		reste2[k-1] = '\0';
		FILE* newDB = NULL;
		newDB = fopen("zones_de_collecte_NEW.csv", "a");
		if (j > 2) fprintf(newDB, "%s;%s;%c\n", reste, reste2, lettre[0]);
		fclose(newDB);
		i++;
	}
	fclose(database);
	return 0;	
	*/
	
	
	FILE* database = NULL;
	database = fopen("gencod_adresses.csv", "r");
	system("wc -l gencod_adresses.csv > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	char lettre[5]={0};
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		char gencod[20]={0}, reste[50]={0};
		int j=0;
		gencod[j] = getc(database);
		while (gencod[j] != ';')
		{
			j++;
			gencod[j] = getc(database);
		}
		gencod[j] = '\0';
		if (j == 1)
		{
			gencod[12] = gencod[0];
			int a=0;
			for (a=0;a<12;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 2)
		{
			gencod[12] = gencod[1];
			gencod[11] = gencod[0];
			int a=0;
			for (a=0;a<11;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 3)
		{
			gencod[12] = gencod[2];
			gencod[11] = gencod[1];
			gencod[10] = gencod[0];
			int a=0;
			for (a=0;a<10;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 4)
		{
			gencod[12] = gencod[3];
			gencod[11] = gencod[2];
			gencod[10] = gencod[1];
			gencod[9] = gencod[0];
			int a=0;
			for (a=0;a<9;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 5)
		{
			gencod[12] = gencod[4];
			gencod[11] = gencod[3];
			gencod[10] = gencod[2];
			gencod[9] = gencod[1];
			gencod[8] = gencod[0];
			int a=0;
			for (a=0;a<8;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 6)
		{
			gencod[12] = gencod[5];
			gencod[11] = gencod[4];
			gencod[10] = gencod[3];
			gencod[9] = gencod[2];
			gencod[8] = gencod[1];
			gencod[7] = gencod[0];
			int a=0;
			for (a=0;a<7;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 7)
		{
			gencod[12] = gencod[6];
			gencod[11] = gencod[5];
			gencod[10] = gencod[4];
			gencod[9] = gencod[3];
			gencod[8] = gencod[2];
			gencod[7] = gencod[1];
			gencod[6] = gencod[0];
			int a=0;
			for (a=0;a<6;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 8)
		{
			gencod[12] = gencod[7];
			gencod[11] = gencod[6];
			gencod[10] = gencod[5];
			gencod[9] = gencod[4];
			gencod[8] = gencod[3];
			gencod[7] = gencod[2];
			gencod[6] = gencod[1];
			gencod[5] = gencod[0];
			int a=0;
			for (a=0;a<5;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 9)
		{
			gencod[12] = gencod[8];
			gencod[11] = gencod[7];
			gencod[10] = gencod[6];
			gencod[9] = gencod[5];
			gencod[8] = gencod[4];
			gencod[7] = gencod[3];
			gencod[6] = gencod[2];
			gencod[5] = gencod[1];
			gencod[4] = gencod[0];
			int a=0;
			for (a=0;a<4;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 10)
		{
			gencod[12] = gencod[9];
			gencod[11] = gencod[8];
			gencod[10] = gencod[7];
			gencod[9] = gencod[6];
			gencod[8] = gencod[5];
			gencod[7] = gencod[4];
			gencod[6] = gencod[3];
			gencod[5] = gencod[2];
			gencod[4] = gencod[1];
			gencod[3] = gencod[0];
			int a=0;
			for (a=0;a<3;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 11)
		{
			gencod[12] = gencod[10];
			gencod[11] = gencod[9];
			gencod[10] = gencod[8];
			gencod[9] = gencod[7];
			gencod[8] = gencod[6];
			gencod[7] = gencod[5];
			gencod[6] = gencod[4];
			gencod[5] = gencod[3];
			gencod[4] = gencod[2];
			gencod[3] = gencod[1];
			gencod[2] = gencod[0];
			int a=0;
			for (a=0;a<2;a++)
			{
				gencod[a] = '0';
			}
		}
		else if (j == 12)
		{
			gencod[12] = gencod[11];
			gencod[11] = gencod[10];
			gencod[10] = gencod[9];
			gencod[9] = gencod[8];
			gencod[8] = gencod[7];
			gencod[7] = gencod[6];
			gencod[6] = gencod[5];
			gencod[5] = gencod[4];
			gencod[4] = gencod[3];
			gencod[3] = gencod[2];
			gencod[2] = gencod[1];
			gencod[1] = gencod[0];
			int a=0;
			for (a=0;a<1;a++)
			{
				gencod[a] = '0';
			}
		}
		j=0;
		reste[j] = getc(database);
		while (reste[j] != '\n')
		{
			j++;
			reste[j] = getc(database);
		}
		reste[j] = '\0';
		i++;
		FILE* newDB = NULL;
		newDB = fopen("gencod_adresses_NEW.csv", "a");
		fprintf(newDB, "%s;%s\n", gencod, reste);
		fclose(newDB);
	}
	fclose(database);
	return 0;	
}
