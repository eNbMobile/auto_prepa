#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

// Chemin de préparation : sert à éliminer les espaces entre les adresses, les "Voir le détail" et tout ce qui parasite autour

int main()
{
	FILE* database = NULL;
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
		char gencod[20]={0}, reste[1000]={0};
		int j=0;
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
		FILE* newDB = NULL;
		newDB = fopen("chemin_de_prep_NEW.txt", "a");
		fprintf(newDB, "%s\n", gencod);
		fclose(newDB);
		i++;
	}
	fclose(database);
	return 0;
}
