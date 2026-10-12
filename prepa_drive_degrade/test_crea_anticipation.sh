#!/usr/bin/env bash
# Verifie le classement de crea_anticipation() sur un bon_prepa.txt minimal,
# avant de deposer un nouveau binaire sur Drive.
# Usage : prepa_drive_degrade/test_crea_anticipation.sh
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/main_test.c" <<'C'
#include "fct_prepa_drive_degrade.h"
int main(){ crea_anticipation(); return 0; }
C
gcc -w -I"$ICI" -o "$TMP/test_anticipation" "$TMP/main_test.c" "$ICI/fct_prepa_drive_degrade.c"

cd "$TMP"
printf 'M,1,3,3,entete\n' > bon_prepa.txt
# Baguette au mais : UC liee a 2000000280356, la commande porte l'EAN fabricant.
printf '3289664281803;Baguette au Mais;1,20;4,80;4;OUI;0;0;N;MARDI,1,Retrait;M2-MM-2-8;X;U;1;00/00/0000\n' >> bon_prepa.txt
printf '3760242644772;Combustible;29,99;1,50;2;OUI;0;0;N;MARDI,1,Retrait;AUCUNE ADRESSE;X;H;2;00/00/0000\n' >> bon_prepa.txt
printf '3256229807013;Saucisson;7,30;7,30;1;OUI;0;0;N;MARDI,1,Retrait;M2-JJ-3-7;X;O;3;00/00/0000\n' >> bon_prepa.txt
printf '3760242644772;0320000\n3256229807013;0240410\n' > gencod_nomenclatures.csv
./test_anticipation > /dev/null

attendu=$'3289664281803;C\n3760242644772;A'
obtenu="$(awk -F';' '{print $1";"$NF}' bon_anticipation.txt)"
if [ "$obtenu" != "$attendu" ]; then
  echo "ECHEC crea_anticipation : attendu"
  echo "$attendu"
  echo "obtenu"
  echo "$obtenu"
  exit 1
fi
echo "crea_anticipation OK"
