#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

// Chemin de préparation : sert à éliminer les espaces entre les adresses, les "Voir le détail" et tout ce qui parasite autour

int main()
{
	FILE* database = NULL;
	database = fopen("chemin_de_prep.txt", "r");
	system("wc -l chemin_de_prep.txt > tmp");
	FILE* tmp = NULL;
	tmp = fopen("tmp", "r");
	int nbLignes=0, i=0;
	fscanf(tmp, "%d", &nbLignes);
	fclose(tmp);
	remove("tmp");
	while (i < nbLignes)
	{
		char reste[100]={0};
		int j=0;
		reste[j] = getc(database);
		while (reste[j] != '\n')
		{
			j++;
			reste[j] = getc(database);
			if (reste[0] == 'M' && reste[j] == '0' && j < 21 && j > 7 && reste[j-1] != '1') j--;
		}
		reste[j] = '\0';
		if (j > 2)
		{
			FILE* newDB = NULL;
			newDB = fopen("chemin_de_prep_NEW.txt", "a");
			if (reste[0] == 'M') reste[5] = '-';
			if (reste[0] == 'M' || reste[0] == '0' || reste[0] == 'R') fprintf(newDB, "%s\n", reste);
			fclose(newDB);
		}
		i++;
	}
	fclose(database);
	return 0;
}
