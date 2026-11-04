# Worker "pavesdeparis"

**Pavés de Paris** : un jeu de plateau immobilier original, jouable à plusieurs
en ligne sur le même principe que `skyjoenligne`. Chacun ouvre la page sur son
téléphone, rejoint une salle avec un code court et joue son tour ; tout est
calculé par le worker.

URL une fois déployé : `https://pavesdeparis.coopu.workers.dev`

## Déroulé d'une partie

1. Le premier joueur crée une salle (code de 4 caractères, lien `…/?code=XXXX`)
   et choisit la durée : 15, 25 ou 40 tours, ou sans limite.
2. Les autres rejoignent avec le code (2 à 6 joueurs) ; l'hôte lance la partie,
   l'ordre de jeu est tiré au sort. Chacun part avec 1 500 €.
3. À son tour : lancer les dés et avancer. Passer par le Départ rapporte 200 €.
   - Rue, gare ou service libre : l'acheter ou la laisser à la banque.
   - Bien d'un autre joueur : le loyer est payé automatiquement. Loyer d'une
     rue doublé si le propriétaire a tout le quartier (même couleur) ; gares
     25/50/100/200 € selon le nombre possédé ; services 4× ou 10× les dés.
   - Taxe foncière (200 €), amende de stationnement (100 €).
   - Cartes Surprise et Mairie (gains, frais, déplacements, poste de police,
     carte « Libéré sur parole »).
   - Un double fait rejouer ; trois doubles de suite envoient au poste.
4. Au poste de police : tenter un double (3 essais, puis 50 € de caution
   obligatoire), payer 50 € tout de suite, ou utiliser une carte « Libéré sur
   parole ».
5. Un joueur qui ne peut pas payer revend automatiquement ses biens à la
   banque (moitié du prix, les moins chers d'abord) ; s'il reste à court, il
   fait faillite et ses biens redeviennent libres.
6. La partie s'arrête quand il ne reste qu'un joueur, ou à la fin du nombre de
   tours choisi : la plus grosse fortune (argent + prix des biens) gagne.

Si un joueur ne joue plus depuis 60 s, les autres voient « Jouer à sa place »
(lancer de dés, ou refus d'achat). « Abandonner la partie » le met en faillite.
On reprend sa place en rouvrant le lien sur le même téléphone.

Pas encore inclus (version suivante) : maisons/hôtels, hypothèques, enchères,
échanges entre joueurs.

## Technique

- Même base D1 que `skyjoenligne` (binding `DB`) : table `paves_salles`, créée
  au premier appel, et la table `joueurs` partagée (noms proposés à la saisie).
  Salles purgées après 72 h sans coup.
- Les clients interrogent `/api/etat` toutes les 1,5 s ; les écritures sont
  protégées par un numéro de version (pas de coup perdu si deux joueurs
  agissent en même temps).
- Déployé par `.github/workflows/deploy_pavesdeparis.yml` à chaque modification
  poussée sur `main`.
