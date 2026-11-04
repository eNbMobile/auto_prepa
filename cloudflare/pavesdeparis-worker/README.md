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
3. À son tour : lancer les dés et avancer. Chaque téléphone rejoue le coup
   comme sur un vrai plateau : les dés roulent, le pion avance case par case
   et les événements s'affichent un par un. Passer par le Départ rapporte 200 €.
   - Rue, gare ou service libre : son titre de propriété (prix, loyers nu, en
     quartier, avec maisons et hôtel, hypothèque) s'affiche au centre ; l'acheter, ou le refuser : il part alors aux
     enchères (aussi quand le joueur n'a pas de quoi l'acheter).
   - Bien d'un autre joueur : le loyer est payé automatiquement. Loyer d'une
     rue doublé si le propriétaire a tout le quartier (même couleur), puis
     ×5, ×15, ×40, ×55 avec 1 à 4 maisons et ×70 avec un hôtel ; gares
     25/50/100/200 € selon le nombre possédé ; services 4× ou 10× les dés.
     Un bien hypothéqué ne rapporte rien.
   - Taxe foncière (200 €), amende de stationnement (100 €).
   - Cartes Surprise et Caisse commune (gains, frais, déplacements, poste de police,
     carte « Libéré sur parole ») : la carte reste affichée au centre et son
     effet ne s'applique que quand le joueur touche « OK ».
   - Un double fait rejouer ; trois doubles de suite envoient au poste.
4. Au poste de police : tenter un double (3 essais, puis 50 € de caution
   obligatoire), payer 50 € tout de suite, ou utiliser une carte « Libéré sur
   parole ».
5. **Constructions et hypothèques** (à tout moment, sauf pendant une enchère,
   en touchant un de ses biens) :
   - avec tout un quartier non hypothéqué, construire des maisons puis un
     hôtel (5e construction), de façon équilibrée entre les rues ; coût de
     50 € (marron, bleu ciel) à 200 € (vert, bleu foncé), revente moitié prix ;
   - hypothéquer un bien sans construction dans son quartier (+ moitié du
     prix) ; lever l'hypothèque coûte la moitié du prix + 10 %.
6. **Enchères** : chacun mise +10/+50/+100 € ou passe ; dès qu'il ne reste
   qu'un enchérisseur, il emporte le bien. Après 20 s sans nouvelle offre,
   n'importe qui peut clore l'enchère. Sans offre, le bien reste à la banque.
7. Un joueur qui ne peut pas payer passe dans le rouge : la partie attend qu'il
   choisisse lui-même les maisons à revendre et les biens à hypothéquer, ou
   qu'il déclare faillite (ses biens redeviennent libres ; un créancier ne
   garde que ce qui a réellement pu être payé). S'il ne répond plus, un autre
   joueur peut « Régler à sa place » après 60 s (revente automatique).
8. La partie s'arrête quand il ne reste qu'un joueur, ou à la fin du nombre de
   tours choisi : la plus grosse fortune (argent + biens + constructions, un bien hypothéqué comptant pour moitié) gagne.

## Échanges

- À tout moment (sauf pendant une enchère), « 🤝 Proposer un échange » :
  choisir le joueur, cocher les biens qu'on donne et ceux qu'on veut, ajouter
  de l'argent d'un côté. Le joueur visé accepte ou refuse ; celui qui propose
  peut retirer sa proposition. Une seule proposition à la fois dans la salle.
- Les biens d'un quartier bâti ne s'échangent pas (revendre d'abord ses
  maisons) ; un bien hypothéqué change de main en restant hypothéqué.
- Tout est revérifié à l'acceptation (biens, argent) ; un échange peut aider
  un joueur à régler une dette.

## Robots

- Dans la salle d'attente, l'hôte peut **ajouter des robots** (Bip, Zap, Kiwi…)
  pour compléter la table, et les retirer avant de lancer.
- Pendant la partie, chaque fiche de joueur a une case **« 🤖 Robot »** : cochée,
  un robot joue à la place de ce joueur (pratique si quelqu'un s'absente) ;
  le joueur la décoche à son retour pour reprendre la main.
- Les robots achètent s'il leur reste de la marge, enchérissent jusqu'au prix
  (davantage pour un bien qui touche un quartier), construisent dès qu'ils ont
  un quartier, lèvent leurs hypothèques et règlent leurs dettes eux-mêmes.
- Ils répondent aux propositions d'échange (acceptées si elles leur sont
  nettement favorables) et proposent eux-mêmes d'acheter la rue qui leur
  manque pour compléter un quartier : 2,4 × son prix, puis +0,6 × à chaque
  refus (au plus tôt 3 tours après), et ils abandonnent cette rue après
  3 refus pour viser un autre quartier.
- Ils jouent côté serveur, au rythme des animations, tant qu'au moins un
  téléphone a la partie ouverte.

Si un joueur ne joue plus depuis 60 s, les autres voient « Jouer à sa place »
(lancer de dés, ou refus d'achat). « Abandonner la partie » le met en faillite.
On reprend sa place en rouvrant le lien sur le même téléphone.


## Technique

- Même base D1 que `skyjoenligne` (binding `DB`) : table `paves_salles`, créée
  au premier appel, et la table `joueurs` partagée (noms proposés à la saisie).
  Salles purgées après 72 h sans coup.
- Les clients interrogent `/api/etat` toutes les 1,5 s ; les écritures sont
  protégées par un numéro de version (pas de coup perdu si deux joueurs
  agissent en même temps).
- Déployé par `.github/workflows/deploy_pavesdeparis.yml` à chaque modification
  poussée sur `main`.
