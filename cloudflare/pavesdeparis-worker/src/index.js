/**
 * Worker "pavesdeparis" — « Pavés de Paris », un jeu de plateau immobilier
 * original jouable à plusieurs en ligne, sur le même principe que skyjoenligne.
 *
 * Chacun ouvre la page sur son téléphone, crée ou rejoint une salle avec un
 * code court et joue son tour : dés, déplacement, achat de rues, loyers,
 * cartes Surprise et Caisse commune, poste de police, faillite et fin de partie sont
 * gérés par le worker.
 *
 * L'état des salles vit dans D1 (base « skyjoenligne », table paves_salles,
 * créée au besoin) : une lecture juste après une écriture renvoie bien la
 * dernière version. Les clients interrogent /api/etat toutes les 1,5 s.
 */

const MIN_JOUEURS = 2;
const MAX_JOUEURS = 6;
const ARGENT_DEPART = 1500;
const SALAIRE = 200;
const CAUTION = 50;
const DELAI_INACTIF_S = 60;
const JOURNAL_MAX = 8;
const SALLE_TTL_H = 72;
const TOURS_CHOIX = [0, 15, 25, 40];
const TOURS_DEFAUT = 25;
const CASE_POSTE = 10;
const DELAI_ENCHERE_S = 20;
const MISE_MAX = 5000;
const NOMS_ROBOTS = ['Bip', 'Zap', 'Kiwi', 'Pixel', 'Momo', 'Tic'];
const REFLEXION_ROBOT_MS = 1200;
// Offre d'un robot pour la rue qui lui manque : 2,4 × le prix, +0,6 × à chaque refus,
// abandon de cette rue après 3 refus ; nouvelle tentative au plus tôt 3 tours plus tard.
const OFFRE_ROBOT_BASE = 2.4;
const OFFRE_ROBOT_HAUSSE = 0.6;
const OFFRE_ROBOT_REFUS_MAX = 3;
const OFFRE_ROBOT_PAUSE_TOURS = 3;
// Loyer d'une rue selon ses constructions (0 à 4 maisons, 5 = hôtel), en multiples du loyer de base.
const MULT_MAISONS = [1, 5, 15, 40, 55, 70];
// Coût d'une maison (ou de l'hôtel) par quartier.
const COUT_MAISON = [50, 50, 100, 100, 150, 150, 200, 200];

const COULEURS = ['#E63946', '#2A9D8F', '#F4A261', '#7B8FD6', '#B5179E', '#90BE6D'];
const GROUPES = ['#8B5E3C', '#7EC8E3', '#D16BA5', '#F28C28', '#E03B3B', '#F2C14E', '#2E9E5B', '#2B4C9B'];

/* --------------------------------------------------------------- plateau */

const PLATEAU = [
  { t: 'depart', nom: 'Départ', court: 'Départ' },
  { t: 'rue', g: 0, nom: 'Rue Mouffetard', court: 'Mouffetard', prix: 60 },
  { t: 'carte', p: 'mairie', nom: 'Caisse commune', court: 'Caisse commune' },
  { t: 'rue', g: 0, nom: 'Rue de Ménilmontant', court: 'Ménilmontant', prix: 70 },
  { t: 'taxe', nom: 'Taxe foncière', court: 'Taxe foncière', montant: 200 },
  { t: 'gare', nom: "Gare de l'Est", court: "G. de l'Est", prix: 200 },
  { t: 'rue', g: 1, nom: 'Rue Oberkampf', court: 'Oberkampf', prix: 100 },
  { t: 'carte', p: 'surprise', nom: 'Surprise', court: 'Surprise' },
  { t: 'rue', g: 1, nom: 'Rue des Martyrs', court: 'Martyrs', prix: 110 },
  { t: 'rue', g: 1, nom: 'Rue de la Roquette', court: 'Roquette', prix: 120 },
  { t: 'poste', nom: 'Poste de police (simple visite)', court: 'Poste · visite' },
  { t: 'rue', g: 2, nom: 'Rue Montorgueil', court: 'Montorgueil', prix: 140 },
  { t: 'service', nom: 'Compagnie du gaz', court: 'Gaz', prix: 150 },
  { t: 'rue', g: 2, nom: 'Rue Cler', court: 'Cler', prix: 150 },
  { t: 'rue', g: 2, nom: 'Rue du Bac', court: 'Bac', prix: 160 },
  { t: 'gare', nom: "Gare d'Austerlitz", court: 'G. Austerlitz', prix: 200 },
  { t: 'rue', g: 3, nom: 'Rue des Rosiers', court: 'Rosiers', prix: 180 },
  { t: 'carte', p: 'mairie', nom: 'Caisse commune', court: 'Caisse commune' },
  { t: 'rue', g: 3, nom: 'Rue de Rivoli', court: 'Rivoli', prix: 190 },
  { t: 'rue', g: 3, nom: 'Boulevard Haussmann', court: 'Haussmann', prix: 200 },
  { t: 'pause', nom: 'Pause terrasse', court: 'Terrasse' },
  { t: 'rue', g: 4, nom: "Rue Saint-Louis-en-l'Île", court: 'St-Louis', prix: 220 },
  { t: 'carte', p: 'surprise', nom: 'Surprise', court: 'Surprise' },
  { t: 'rue', g: 4, nom: "Quai d'Orsay", court: 'Orsay', prix: 230 },
  { t: 'rue', g: 4, nom: 'Place des Vosges', court: 'Vosges', prix: 240 },
  { t: 'gare', nom: 'Gare de Bercy', court: 'G. de Bercy', prix: 200 },
  { t: 'rue', g: 5, nom: 'Avenue Marceau', court: 'Marceau', prix: 260 },
  { t: 'rue', g: 5, nom: 'Place de la Concorde', court: 'Concorde', prix: 270 },
  { t: 'service', nom: 'Réseau fibre', court: 'Fibre', prix: 150 },
  { t: 'rue', g: 5, nom: 'Avenue George-V', court: 'George-V', prix: 280 },
  { t: 'police', nom: 'Direction le poste !', court: 'Au poste !' },
  { t: 'rue', g: 6, nom: 'Rue de Varenne', court: 'Varenne', prix: 300 },
  { t: 'rue', g: 6, nom: "Avenue d'Iéna", court: 'Iéna', prix: 310 },
  { t: 'carte', p: 'mairie', nom: 'Caisse commune', court: 'Caisse commune' },
  { t: 'rue', g: 6, nom: 'Place Dauphine', court: 'Dauphine', prix: 320 },
  { t: 'gare', nom: 'Gare des Invalides', court: 'G. Invalides', prix: 200 },
  { t: 'carte', p: 'surprise', nom: 'Surprise', court: 'Surprise' },
  { t: 'rue', g: 7, nom: 'Avenue Montaigne', court: 'Montaigne', prix: 360 },
  { t: 'taxe', nom: 'Amende de stationnement', court: 'Amende', montant: 100 },
  { t: 'rue', g: 7, nom: 'Place Vendôme', court: 'Vendôme', prix: 400 },
];

// Loyer de base d'une rue : un huitième du prix, arrondi au pair supérieur.
for (const c of PLATEAU) {
  if (c.t === 'rue') {
    c.loyer = Math.ceil(c.prix / 16) * 2;
    c.maison = COUT_MAISON[c.g];
  }
  if (c.prix) c.leve = Math.ceil((c.prix * 11) / 100) * 5; // levée d'hypothèque : moitié du prix + 10 %, au 5 € supérieur
}

/* Noms d'origine ; ceux de la base D1 (page « Noms des rues ») les remplacent. */
const NOMS_ORIGINE = PLATEAU.map((c) => ({ nom: c.nom, court: c.court }));
const NOM_MAX = 40;
const COURT_MAX = 16;

/** Cases dont on peut changer le nom : rues, gares et services. */
function nomModifiable(i) {
  return !!(PLATEAU[i] && PLATEAU[i].prix);
}

/** Applique au plateau les noms enregistrés (ou ceux d'origine). */
function appliquerNoms(noms) {
  PLATEAU.forEach((c, i) => {
    const o = NOMS_ORIGINE[i];
    const n = nomModifiable(i) && noms && noms[i] ? noms[i] : null;
    c.nom = (n && n.nom) || o.nom;
    c.court = (n && n.court) || (n && n.nom ? n.nom : o.court);
  });
}

const CARTES = {
  surprise: [
    { texte: 'Ton appli de covoiturage te rapporte 50 €.', gain: 50 },
    { texte: 'Tu gagnes au loto du quartier : 100 €.', gain: 100 },
    { texte: 'Avance jusqu\'à la case Départ.', aller: 0 },
    { texte: 'Rendez-vous Place Vendôme.', aller: 39 },
    { texte: 'Va flâner Place des Vosges.', aller: 24 },
    { texte: 'Prends le train à la Gare de l\'Est.', aller: 5 },
    { texte: 'Tu as oublié tes clés : recule de 3 cases.', recule: 3 },
    { texte: 'Trottinette sur le trottoir : 20 € d\'amende.', paie: 20 },
    { texte: 'Excès de vitesse sur le périph : 60 €.', paie: 60 },
    { texte: 'Contrôle d\'identité qui tourne mal : direction le poste !', prison: true },
    { texte: 'Libéré sur parole : garde cette carte pour sortir du poste.', sortie: true },
    { texte: 'Tu offres le café : 20 € à chaque joueur.', chacun: 20 },
  ],
  mairie: [
    { texte: 'Remboursement d\'impôts : 80 €.', gain: 80 },
    { texte: 'Héritage d\'une tante de Montmartre : 120 €.', gain: 120 },
    { texte: 'Prime de fin d\'année : 100 €.', gain: 100 },
    { texte: 'Tu revends ton vieux vélo : 30 €.', gain: 30 },
    { texte: 'Rendez-vous chez le dentiste : 70 €.', paie: 70 },
    { texte: 'Frais de scolarité : 100 €.', paie: 100 },
    { texte: 'Cotisation au syndic : 50 €.', paie: 50 },
    { texte: 'C\'est ton anniversaire : chaque joueur te donne 15 €.', anniversaire: 15 },
    { texte: 'Avance jusqu\'à la case Départ.', aller: 0 },
    { texte: 'Tapage nocturne : direction le poste !', prison: true },
    { texte: 'Libéré sur parole : garde cette carte pour sortir du poste.', sortie: true },
    { texte: 'Retourne Rue Mouffetard (sans passer par le Départ).', aller: 1, sansDepart: true },
  ],
};

/* ---------------------------------------------------------------- helpers */

class ErreurJeu extends Error {}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
}

function erreur(message, status = 400) {
  return json({ erreur: message }, status);
}

function toScriptJson(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

function refuser(message) {
  throw new ErreurJeu(message);
}

function aleatoire(n) {
  return crypto.getRandomValues(new Uint32Array(1))[0] % n;
}

function melanger(liste) {
  for (let i = liste.length - 1; i > 0; i--) {
    const j = aleatoire(i + 1);
    [liste[i], liste[j]] = [liste[j], liste[i]];
  }
  return liste;
}

/** Code de salle lisible : pas de 0/O/1/I pour éviter les confusions. */
function nouveauCode() {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let code = '';
  for (let i = 0; i < 4; i++) code += alphabet[aleatoire(alphabet.length)];
  return code;
}

function normaliserCode(valeur) {
  const code = String(valeur || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
  return /^[A-Z0-9]{4}$/.test(code) ? code : null;
}

function nomValide(nom) {
  const propre = String(nom || '').trim().slice(0, 20);
  return propre || null;
}

function jetonValide(valeur) {
  const jeton = String(valeur || '').trim();
  return /^[A-Za-z0-9._-]{8,64}$/.test(jeton) ? jeton : null;
}

async function corpsJson(request) {
  try {
    const corps = await request.json();
    return corps && typeof corps === 'object' ? corps : {};
  } catch (err) {
    return {};
  }
}

/* ------------------------------------------------------------------- jeu */

function nouvelleSalle(code, toursMax) {
  return {
    code,
    toursMax,
    phase: 'attente',
    hote: null,
    joueurs: [],
    proprio: PLATEAU.map(() => null),
    maisons: PLATEAU.map(() => 0),
    hypo: PLATEAU.map(() => false),
    enchere: null,
    paquets: { surprise: [], mairie: [] },
    tour: null,
    etape: null,
    des: null,
    doubles: 0,
    rejouer: false,
    tourNo: 0,
    derniereCarte: null,
    dernierCoup: Date.now(),
    journal: ['Salle créée. Partage le code ' + code + '.'],
  };
}

function nouveauJoueur(jeton, nom, couleur) {
  return {
    jeton, nom, couleur,
    argent: ARGENT_DEPART, position: 0,
    enPrison: false, essais: 0, cartesSortie: [], faillite: false,
  };
}

function noter(salle, message) {
  if (salle.anim) salle.anim.etapes.push({ t: 'msg', texte: message });
  salle.journal.push(message);
  if (salle.journal.length > JOURNAL_MAX) salle.journal = salle.journal.slice(-JOURNAL_MAX);
}

/** Étape d'animation (dés, déplacement) rejouée par les téléphones. */
function animer(salle, etape) {
  if (salle.anim) salle.anim.etapes.push(etape);
}

function indexJoueur(salle, jeton) {
  return salle.joueurs.findIndex((j) => j.jeton === jeton);
}

function couleurLibre(salle) {
  const prises = salle.joueurs.map((j) => j.couleur);
  return COULEURS.findIndex((c, i) => !prises.includes(i));
}

function demarrer(salle) {
  melanger(salle.joueurs);
  for (const j of salle.joueurs) Object.assign(j, nouveauJoueur(j.jeton, j.nom, j.couleur), { robot: !!j.robot });
  salle.proprio = PLATEAU.map(() => null);
  salle.maisons = PLATEAU.map(() => 0);
  salle.hypo = PLATEAU.map(() => false);
  salle.enchere = null;
  salle.paquets = {
    surprise: melanger(CARTES.surprise.map((c, i) => i)),
    mairie: melanger(CARTES.mairie.map((c, i) => i)),
  };
  salle.phase = 'jeu';
  salle.tour = 0;
  salle.etape = 'lancer';
  salle.des = null;
  salle.doubles = 0;
  salle.rejouer = false;
  salle.tourNo = 1;
  salle.derniereCarte = null;
  salle.classement = null;
  salle.journal = [];
  noter(salle, 'La partie commence ! ' + salle.joueurs[0].nom + ' ouvre le bal.');
}

function fortune(salle, idx) {
  let total = salle.joueurs[idx].argent;
  salle.proprio.forEach((p, i) => {
    if (p !== idx) return;
    total += salle.hypo[i] ? PLATEAU[i].prix / 2 : PLATEAU[i].prix;
    if (salle.maisons[i]) total += salle.maisons[i] * PLATEAU[i].maison;
  });
  return total;
}

function actifs(salle) {
  return salle.joueurs.map((j, i) => i).filter((i) => !salle.joueurs[i].faillite);
}

function terminer(salle, raison) {
  salle.phase = 'fin';
  salle.etape = null;
  const ordre = salle.joueurs.map((j, i) => i).sort((a, b) => {
    const fa = salle.joueurs[a].faillite ? -1 : fortune(salle, a);
    const fb = salle.joueurs[b].faillite ? -1 : fortune(salle, b);
    return fb - fa;
  });
  salle.classement = ordre.map((i) => ({
    nom: salle.joueurs[i].nom,
    couleur: salle.joueurs[i].couleur,
    fortune: salle.joueurs[i].faillite ? 0 : fortune(salle, i),
    faillite: salle.joueurs[i].faillite,
  }));
  noter(salle, raison + ' ' + salle.classement[0].nom + ' gagne la partie !');
}

function verifierFin(salle) {
  if (salle.phase === 'jeu' && actifs(salle).length <= 1) terminer(salle, 'Plus qu\'un joueur en lice.');
}

function proprietesDe(salle, idx) {
  return salle.proprio.map((p, i) => (p === idx ? i : -1)).filter((i) => i >= 0);
}

/**
 * Utilisé seulement pour un joueur absent (« Jouer à sa place ») : un joueur
 * présent choisit lui-même quoi revendre ou hypothéquer.
 * Trouve l'argent manquant : revend d'abord les constructions (à moitié prix,
 * toujours sur la rue la plus bâtie pour rester équilibré), puis hypothèque
 * les biens, les moins chers d'abord.
 */
function liquider(salle, idx, montant) {
  const j = salle.joueurs[idx];
  const mien = proprietesDe(salle, idx);
  let vendues = 0;
  while (j.argent < montant) {
    const batie = mien.filter((i) => salle.maisons[i] > 0)
      .sort((a, b) => salle.maisons[b] - salle.maisons[a] || PLATEAU[b].maison - PLATEAU[a].maison)[0];
    if (batie === undefined) break;
    salle.maisons[batie] -= 1;
    j.argent += PLATEAU[batie].maison / 2;
    vendues++;
  }
  if (vendues) noter(salle, j.nom + ' revend ' + vendues + ' construction' + (vendues > 1 ? 's' : '') + ' à la banque.');
  const libres = mien.filter((i) => !salle.hypo[i]).sort((a, b) => PLATEAU[a].prix - PLATEAU[b].prix);
  for (const i of libres) {
    if (j.argent >= montant) break;
    salle.hypo[i] = true;
    j.argent += PLATEAU[i].prix / 2;
    noter(salle, j.nom + ' hypothèque ' + PLATEAU[i].nom + ' (+' + PLATEAU[i].prix / 2 + ' €).');
  }
}

function faillite(salle, idx) {
  const j = salle.joueurs[idx];
  // Les créanciers ont été crédités d'avance : on leur reprend la part impayée.
  let manque = Math.max(0, -j.argent);
  const dus = j.dus || [];
  const creancier = dus.length ? dus[dus.length - 1].a : null;
  for (let k = dus.length - 1; k >= 0 && manque > 0; k--) {
    const repris = Math.min(dus[k].m, manque);
    if (dus[k].a !== null) salle.joueurs[dus[k].a].argent -= repris;
    manque -= repris;
  }
  j.argent = 0;
  j.dus = [];
  j.faillite = true;
  if (salle.echange && (salle.echange.de === idx || salle.echange.a === idx)) salle.echange = null;
  j.enPrison = false;
  salle.proprio.forEach((p, i) => {
    if (p !== idx) return;
    salle.proprio[i] = null;
    salle.maisons[i] = 0;
    salle.hypo[i] = false;
  });
  if (salle.enchere) {
    if (salle.enchere.meneur === idx) { salle.enchere.meneur = null; salle.enchere.prix = 0; }
    if (!salle.enchere.passe.includes(idx)) salle.enchere.passe.push(idx);
  }
  for (const paquet of j.cartesSortie) salle.paquets[paquet].push(CARTES[paquet].findIndex((c) => c.sortie));
  j.cartesSortie = [];
  noter(salle, j.nom + ' fait faillite' + (creancier === null || creancier === undefined ? '.' : ' face à ' + salle.joueurs[creancier].nom + '.'));
  verifierFin(salle);
}

/**
 * Fait payer `montant` à `de` au profit de `a` (null = la banque). Le solde
 * peut devenir négatif : la partie attend alors que le joueur trouve l'argent
 * lui-même (étape « dette »), ou qu'il déclare faillite.
 */
function payer(salle, de, montant, a) {
  const j = salle.joueurs[de];
  if (j.faillite || montant <= 0) return;
  j.argent -= montant;
  if (a !== null) salle.joueurs[a].argent += montant;
  if (j.argent < 0) {
    j.dus = j.dus || [];
    j.dus.push({ a, m: montant });
  }
}

function debiteurs(salle) {
  return actifs(salle).filter((i) => salle.joueurs[i].argent < 0);
}

/** Valeur que le joueur peut encore tirer de ses biens (constructions, hypothèques). */
function ressources(salle, idx) {
  let total = 0;
  proprietesDe(salle, idx).forEach((i) => {
    total += salle.maisons[i] * PLATEAU[i].maison / 2;
    if (!salle.hypo[i]) total += PLATEAU[i].prix / 2;
  });
  return total;
}

/** Reprend la partie quand plus personne n'est dans le rouge. */
function verifierDettes(salle) {
  if (salle.phase !== 'jeu' || salle.etape !== 'dette' || debiteurs(salle).length) return;
  salle.joueurs.forEach((j) => { j.dus = []; });
  salle.etape = salle.etapeAvantDette || 'deplacement';
  salle.etapeAvantDette = null;
  apresCoup(salle);
}

function ruesDuQuartier(g) {
  return PLATEAU.map((c, i) => (c.t === 'rue' && c.g === g ? i : -1)).filter((i) => i >= 0);
}

function quartierEntier(salle, g, proprio) {
  return proprio !== null && ruesDuQuartier(g).every((i) => salle.proprio[i] === proprio);
}

function loyerDe(salle, pos) {
  const c = PLATEAU[pos];
  const proprio = salle.proprio[pos];
  const possedes = (filtre) => PLATEAU.filter((x, i) => filtre(x) && salle.proprio[i] === proprio).length;
  if (salle.hypo[pos]) return 0;
  if (c.t === 'rue') {
    if (salle.maisons[pos]) return c.loyer * MULT_MAISONS[salle.maisons[pos]];
    return quartierEntier(salle, c.g, proprio) ? c.loyer * 2 : c.loyer;
  }
  if (c.t === 'gare') return 25 * Math.pow(2, possedes((x) => x.t === 'gare') - 1);
  const total = salle.des ? salle.des[0] + salle.des[1] : 7;
  return total * (possedes((x) => x.t === 'service') === 2 ? 10 : 4);
}

function envoyerAuPoste(salle, idx) {
  const j = salle.joueurs[idx];
  j.position = CASE_POSTE;
  j.enPrison = true;
  j.essais = 0;
  salle.rejouer = false;
  animer(salle, { t: 'saut', j: idx, a: CASE_POSTE });
  noter(salle, j.nom + ' file au poste de police.');
}

function deplacer(salle, idx, destination, avecDepart) {
  const j = salle.joueurs[idx];
  const depart = j.position;
  animer(salle, { t: 'pas', j: idx, de: depart, a: destination, recule: !avecDepart && destination < depart });
  j.position = destination;
  if (avecDepart && destination <= depart) {
    j.argent += SALAIRE;
    noter(salle, j.nom + ' passe par le Départ : +' + SALAIRE + ' €.');
  }
  arriver(salle, idx);
}

function tirerCarte(salle, idx, paquet) {
  const j = salle.joueurs[idx];
  const numero = salle.paquets[paquet].shift();
  const carte = CARTES[paquet][numero];
  if (carte.sortie) j.cartesSortie.push(paquet);
  else salle.paquets[paquet].push(numero);
  salle.derniereCarte = { paquet, texte: carte.texte, joueur: idx };
  salle.carteEnAttente = { paquet, numero };
  salle.etape = 'carte';
  noter(salle, j.nom + ' tire une carte ' + (paquet === 'mairie' ? 'Caisse commune' : 'Surprise') + '.');
}

/** Applique la carte tirée, une fois que le joueur l'a lue (« OK »). */
function appliquerCarte(salle) {
  const idx = salle.tour;
  const j = salle.joueurs[idx];
  const { paquet, numero } = salle.carteEnAttente;
  const carte = CARTES[paquet][numero];
  salle.carteEnAttente = null;
  salle.etape = 'deplacement';
  noter(salle, j.nom + ' : ' + carte.texte);

  if (carte.gain) j.argent += carte.gain;
  else if (carte.paie) payer(salle, idx, carte.paie, null);
  else if (carte.prison) envoyerAuPoste(salle, idx);
  else if (carte.recule) {
    deplacer(salle, idx, (j.position - carte.recule + PLATEAU.length) % PLATEAU.length, false);
  } else if (carte.aller !== undefined) deplacer(salle, idx, carte.aller, !carte.sansDepart);
  else if (carte.chacun) {
    for (const k of actifs(salle)) if (k !== idx) payer(salle, idx, carte.chacun, k);
  } else if (carte.anniversaire) {
    for (const k of actifs(salle)) if (k !== idx) payer(salle, k, carte.anniversaire, idx);
  }
  apresCoup(salle);
}

/** Résout l'arrivée du joueur `idx` sur sa case. */
function arriver(salle, idx) {
  const j = salle.joueurs[idx];
  const pos = j.position;
  const c = PLATEAU[pos];
  if (c.prix) {
    const proprio = salle.proprio[pos];
    if (proprio === null) {
      if (j.argent >= c.prix) salle.etape = 'achat';
      else {
        noter(salle, j.nom + ' n\'a pas de quoi acheter ' + c.nom + '.');
        ouvrirEnchere(salle, pos);
      }
    } else if (proprio !== idx && salle.hypo[pos]) {
      noter(salle, j.nom + ' arrive sur ' + c.nom + ', hypothéqué : pas de loyer.');
    } else if (proprio !== idx) {
      const loyer = loyerDe(salle, pos);
      noter(salle, j.nom + ' paie ' + loyer + ' € de loyer à ' + salle.joueurs[proprio].nom + ' (' + c.nom + ').');
      payer(salle, idx, loyer, proprio);
    }
  } else if (c.t === 'taxe') {
    noter(salle, j.nom + ' paie ' + c.nom.toLowerCase() + ' : ' + c.montant + ' €.');
    payer(salle, idx, c.montant, null);
  } else if (c.t === 'carte') {
    tirerCarte(salle, idx, c.p);
  } else if (c.t === 'poste') {
    noter(salle, j.nom + ' s\'arrête au poste en simple visite.');
  } else if (c.t === 'police') {
    envoyerAuPoste(salle, idx);
  }
}

function avancer(salle, idx, pas) {
  const j = salle.joueurs[idx];
  deplacer(salle, idx, (j.position + pas) % PLATEAU.length, true);
}

function joueurSuivant(salle) {
  salle.doubles = 0;
  salle.rejouer = false;
  const n = salle.joueurs.length;
  let suivant = salle.tour;
  do {
    suivant = (suivant + 1) % n;
    if (suivant === 0) salle.tourNo += 1;
  } while (salle.joueurs[suivant].faillite);

  if (salle.toursMax && salle.tourNo > salle.toursMax) {
    terminer(salle, 'Les ' + salle.toursMax + ' tours sont joués.');
    return;
  }
  salle.tour = suivant;
  salle.etape = salle.joueurs[suivant].enPrison ? 'prison' : 'lancer';
}

/** Après un coup : on attend un achat, on rejoue sur un double, ou on passe la main. */
function apresCoup(salle) {
  if (salle.phase !== 'jeu') return;
  if (salle.etape === 'dette') return;
  if (debiteurs(salle).length) {
    salle.etapeAvantDette = salle.etape;
    salle.etape = 'dette';
    for (const i of debiteurs(salle)) {
      noter(salle, salle.joueurs[i].nom + ' doit trouver ' + (-salle.joueurs[i].argent) + ' € (revendre ou hypothéquer).');
    }
    return;
  }
  const j = salle.joueurs[salle.tour];
  if (!j.faillite && (salle.etape === 'achat' || salle.etape === 'carte')) return;
  if (salle.etape === 'enchere') return;
  if (!j.faillite && salle.rejouer && !j.enPrison) {
    salle.etape = 'lancer';
    noter(salle, 'Double : ' + j.nom + ' rejoue.');
    return;
  }
  joueurSuivant(salle);
}

function lancerDes(salle) {
  salle.des = [aleatoire(6) + 1, aleatoire(6) + 1];
  return salle.des;
}

function texteDes(des) {
  return des[0] + ' + ' + des[1];
}

function actionLancer(salle) {
  const idx = salle.tour;
  const j = salle.joueurs[idx];
  salle.derniereCarte = null;
  const des = lancerDes(salle);
  animer(salle, { t: 'des', des });
  const double = des[0] === des[1];

  if (salle.etape === 'prison') {
    if (double) {
      j.enPrison = false;
      salle.rejouer = false;
      noter(salle, j.nom + ' fait un double (' + texteDes(des) + ') et sort du poste.');
      salle.etape = 'deplacement';
      avancer(salle, idx, des[0] + des[1]);
    } else {
      j.essais += 1;
      if (j.essais >= 3) {
        noter(salle, j.nom + ' rate son 3e essai (' + texteDes(des) + ') et paie ' + CAUTION + ' € de caution.');
        payer(salle, idx, CAUTION, null);
        j.enPrison = false;
        salle.etape = 'deplacement';
        avancer(salle, idx, des[0] + des[1]);
      } else {
        noter(salle, j.nom + ' tente un double (' + texteDes(des) + ') : raté, encore au poste.');
      }
    }
    apresCoup(salle);
    return;
  }

  if (double) {
    salle.doubles += 1;
    if (salle.doubles === 3) {
      noter(salle, j.nom + ' fait trois doubles de suite !');
      envoyerAuPoste(salle, idx);
      apresCoup(salle);
      return;
    }
    salle.rejouer = true;
  } else {
    salle.rejouer = false;
  }
  noter(salle, j.nom + ' lance ' + texteDes(des) + '.');
  salle.etape = 'deplacement';
  avancer(salle, idx, des[0] + des[1]);
  apresCoup(salle);
}

function actionAchat(salle, acheter) {
  const idx = salle.tour;
  const j = salle.joueurs[idx];
  const c = PLATEAU[j.position];
  if (acheter) {
    if (j.argent < c.prix) refuser('Pas assez d\'argent.');
    j.argent -= c.prix;
    salle.proprio[j.position] = idx;
    noter(salle, j.nom + ' achète ' + c.nom + ' pour ' + c.prix + ' €.');
    salle.etape = 'deplacement';
  } else {
    noter(salle, j.nom + ' ne l\'achète pas : ' + c.nom + ' part aux enchères.');
    ouvrirEnchere(salle, j.position);
  }
  apresCoup(salle);
}

/* --------------------------------------------------------------- enchères */

function ouvrirEnchere(salle, pos) {
  salle.enchere = { case: pos, prix: 0, meneur: null, passe: [], depuis: Date.now() };
  salle.etape = 'enchere';
  resoudreEnchereSiFinie(salle);
}

function enLice(salle) {
  const e = salle.enchere;
  return actifs(salle).filter((i) => !e.passe.includes(i) && i !== e.meneur);
}

function cloreEnchere(salle) {
  const e = salle.enchere;
  const c = PLATEAU[e.case];
  if (e.meneur !== null && salle.joueurs[e.meneur].argent >= e.prix && !salle.joueurs[e.meneur].faillite) {
    salle.joueurs[e.meneur].argent -= e.prix;
    salle.proprio[e.case] = e.meneur;
    noter(salle, salle.joueurs[e.meneur].nom + ' remporte ' + c.nom + ' aux enchères pour ' + e.prix + ' €.');
  } else {
    noter(salle, 'Personne ne prend ' + c.nom + ' : le bien reste à la banque.');
  }
  salle.enchere = null;
  if (salle.phase !== 'jeu') return;
  salle.etape = 'deplacement';
  apresCoup(salle);
}

/** L'enchère se termine dès qu'il ne reste plus personne pour surenchérir. */
function resoudreEnchereSiFinie(salle) {
  if (salle.enchere && enLice(salle).length === 0) cloreEnchere(salle);
}

function actionEnchere(salle, moi, action, valeur) {
  const e = salle.enchere;
  if (!e || salle.etape !== 'enchere') refuser('Aucune enchère en cours.');
  const j = salle.joueurs[moi];
  if (action === 'clore') {
    if (Date.now() - e.depuis < DELAI_ENCHERE_S * 1000) refuser('Attends encore un peu les autres enchérisseurs.');
    noter(salle, 'Enchère close, faute de nouvelle offre.');
    cloreEnchere(salle);
    return;
  }
  if (j.faillite) refuser('Tu n\'es plus dans la partie.');
  if (e.passe.includes(moi)) refuser('Tu as déjà passé ton tour pour cette enchère.');
  if (action === 'passerEnchere') {
    if (e.meneur === moi) refuser('Tu mènes l\'enchère.');
    e.passe.push(moi);
  } else {
    if (e.meneur === moi) refuser('Tu mènes déjà l\'enchère.');
    const mise = parseInt(valeur, 10);
    if (!Number.isInteger(mise) || mise <= e.prix || mise > MISE_MAX) refuser('Mise trop basse : il faut dépasser ' + e.prix + ' €.');
    if (mise > j.argent) refuser('Tu n\'as que ' + j.argent + ' €.');
    e.prix = mise;
    e.meneur = moi;
    noter(salle, j.nom + ' mise ' + mise + ' € sur ' + PLATEAU[e.case].nom + '.');
  }
  e.depuis = Date.now();
  resoudreEnchereSiFinie(salle);
}

/* ---------------------------------------------- constructions, hypothèques */

function actionGestion(salle, moi, action, pos) {
  const j = salle.joueurs[moi];
  if (j.faillite) refuser('Tu n\'es plus dans la partie.');
  if (!Number.isInteger(pos) || pos < 0 || pos >= PLATEAU.length) refuser('Case inconnue.');
  if (salle.proprio[pos] !== moi) refuser('Ce bien n\'est pas à toi.');
  const c = PLATEAU[pos];
  const rues = c.t === 'rue' ? ruesDuQuartier(c.g) : [pos];
  const niveaux = rues.map((i) => salle.maisons[i]);

  if (action === 'construire') {
    if (c.t !== 'rue') refuser('On ne construit que sur les rues.');
    if (!quartierEntier(salle, c.g, moi)) refuser('Il faut posséder tout le quartier pour construire.');
    if (rues.some((i) => salle.hypo[i])) refuser('Lève d\'abord les hypothèques du quartier.');
    if (salle.maisons[pos] >= 5) refuser('Il y a déjà un hôtel.');
    if (salle.maisons[pos] > Math.min(...niveaux)) refuser('Construis d\'abord sur les autres rues du quartier.');
    if (j.argent < c.maison) refuser('Pas assez d\'argent (' + c.maison + ' €).');
    j.argent -= c.maison;
    salle.maisons[pos] += 1;
    noter(salle, j.nom + (salle.maisons[pos] === 5 ? ' construit un hôtel' : ' construit une maison') + ' ' + c.nom + '.');
  } else if (action === 'demolir') {
    if (!salle.maisons[pos]) refuser('Aucune construction ici.');
    if (salle.maisons[pos] < Math.max(...niveaux)) refuser('Vends d\'abord sur les rues les plus bâties du quartier.');
    salle.maisons[pos] -= 1;
    j.argent += c.maison / 2;
    noter(salle, j.nom + ' revend une construction ' + c.nom + ' (+' + c.maison / 2 + ' €).');
  } else if (action === 'hypothequer') {
    if (salle.hypo[pos]) refuser('Déjà hypothéqué.');
    if (niveaux.some((n) => n > 0)) refuser('Vends d\'abord les constructions du quartier.');
    salle.hypo[pos] = true;
    j.argent += c.prix / 2;
    noter(salle, j.nom + ' hypothèque ' + c.nom + ' (+' + c.prix / 2 + ' €).');
  } else if (action === 'lever') {
    if (!salle.hypo[pos]) refuser('Ce bien n\'est pas hypothéqué.');
    if (j.argent < c.leve) refuser('Pas assez d\'argent (' + c.leve + ' €).');
    j.argent -= c.leve;
    salle.hypo[pos] = false;
    noter(salle, j.nom + ' lève l\'hypothèque de ' + c.nom + ' (' + c.leve + ' €).');
  }
}

/* ---------------------------------------------------------------- échanges */

/**
 * Un échange : `de` propose à `a` de lui donner des biens (`donne`) et de
 * l'argent (`argentDonne`) contre ses biens (`recoit`) et de l'argent
 * (`argentRecu`). Une seule proposition à la fois dans la salle ; tout est
 * revérifié au moment de l'acceptation.
 */
function lireEchange(salle, de, brut) {
  const v = brut && typeof brut === 'object' ? brut : {};
  const liste = (x) => (Array.isArray(x) ? [...new Set(x.map((n) => parseInt(n, 10)))] : []);
  const somme = (x) => Math.max(0, Math.min(MISE_MAX * 4, parseInt(x, 10) || 0));
  return {
    de,
    a: parseInt(v.a, 10),
    donne: liste(v.donne),
    recoit: liste(v.recoit),
    argentDonne: somme(v.argentDonne),
    argentRecu: somme(v.argentRecu),
    depuis: Date.now(),
  };
}

function validerEchange(salle, e) {
  const J = salle.joueurs;
  if (!J[e.a] || e.a === e.de) refuser('Choisis avec qui échanger.');
  if (J[e.de].faillite || J[e.a].faillite) refuser('Ce joueur n\'est plus dans la partie.');
  if (!e.donne.length && !e.recoit.length && !e.argentDonne && !e.argentRecu) refuser('L\'échange est vide.');
  if (e.argentDonne && e.argentRecu) refuser('L\'argent ne va que dans un sens.');
  const verifier = (cases, proprio) => cases.forEach((i) => {
    const c = PLATEAU[i];
    if (!c || !c.prix || salle.proprio[i] !== proprio) refuser('Un des biens a changé de main.');
    if (c.t === 'rue' && ruesDuQuartier(c.g).some((k) => salle.maisons[k] > 0)) {
      refuser('Il faut d\'abord revendre les maisons du quartier de ' + c.nom + '.');
    }
  });
  verifier(e.donne, e.de);
  verifier(e.recoit, e.a);
  if (e.argentDonne > J[e.de].argent) refuser(J[e.de].nom + ' n\'a pas ' + e.argentDonne + ' €.');
  if (e.argentRecu > J[e.a].argent) refuser(J[e.a].nom + ' n\'a pas ' + e.argentRecu + ' €.');
}

function texteEchange(salle, e) {
  const noms = (cases) => cases.map((i) => PLATEAU[i].nom);
  const part = (cases, argent) => [...noms(cases), ...(argent ? [argent + ' €'] : [])].join(', ') || 'rien';
  return salle.joueurs[e.de].nom + ' donne ' + part(e.donne, e.argentDonne)
    + ' contre ' + part(e.recoit, e.argentRecu) + ' de ' + salle.joueurs[e.a].nom;
}

function realiserEchange(salle, e) {
  const J = salle.joueurs;
  e.donne.forEach((i) => { salle.proprio[i] = e.a; });
  e.recoit.forEach((i) => { salle.proprio[i] = e.de; });
  J[e.de].argent += e.argentRecu - e.argentDonne;
  J[e.a].argent += e.argentDonne - e.argentRecu;
  noter(salle, 'Échange conclu : ' + texteEchange(salle, e) + '.');
}

function actionEchange(salle, moi, action, valeur) {
  if (salle.etape === 'enchere') refuser('Attends la fin de l\'enchère.');
  const e = salle.echange;
  if (action === 'proposerEchange') {
    if (e) refuser('Un échange est déjà en cours de discussion.');
    const nouveau = lireEchange(salle, moi, valeur);
    validerEchange(salle, nouveau);
    salle.echange = nouveau;
    noter(salle, 'Proposition : ' + texteEchange(salle, nouveau) + '.');
    return;
  }
  if (!e) refuser('Aucun échange en cours.');
  if (action === 'annulerEchange') {
    if (moi !== e.de) refuser('Seul celui qui propose peut annuler.');
    if (salle.joueurs[moi].robot) noterRefusRobot(salle, e);
    salle.echange = null;
    noter(salle, salle.joueurs[moi].nom + ' retire sa proposition d\'échange.');
    return;
  }
  if (moi !== e.a) refuser('Cette proposition ne t\'est pas adressée.');
  salle.echange = null;
  if (action === 'refuserEchange') {
    noterRefusRobot(salle, e);
    noter(salle, salle.joueurs[moi].nom + ' refuse l\'échange.');
    return;
  }
  try {
    validerEchange(salle, e);
  } catch (err) {
    noter(salle, 'Échange impossible : ' + err.message);
    return;
  }
  realiserEchange(salle, e);
  verifierDettes(salle);
}

/** Mémorise qu'une offre d'un robot pour une rue a été refusée (il surenchérira ou abandonnera). */
function noterRefusRobot(salle, e) {
  if (!salle.joueurs[e.de].robot || e.recoit.length !== 1) return;
  const cle = e.de + '-' + e.recoit[0];
  salle.refusRobot = salle.refusRobot || {};
  salle.refusRobot[cle] = (salle.refusRobot[cle] || 0) + 1;
}

const ECHANGE = ['proposerEchange', 'annulerEchange', 'accepterEchange', 'refuserEchange'];

const GESTION = ['construire', 'demolir', 'hypothequer', 'lever'];
const ENCHERE = ['miser', 'passerEnchere', 'clore'];

function appliquerAction(salle, jeton, action, valeur) {
  const moi = indexJoueur(salle, jeton);
  if (moi === -1) refuser('Tu n\'es pas dans cette salle.');

  if (action === 'demarrer') {
    if (salle.phase !== 'attente') refuser('La partie a déjà commencé.');
    if (salle.hote !== jeton) refuser('Seul l\'hôte lance la partie.');
    if (salle.joueurs.length < MIN_JOUEURS) refuser('Il faut au moins ' + MIN_JOUEURS + ' joueurs.');
    demarrer(salle);
    salle.dernierCoup = Date.now();
    return;
  }
  if (action === 'ajouterRobot') {
    if (salle.phase !== 'attente') refuser('La partie a déjà commencé.');
    if (salle.hote !== jeton) refuser('Seul l\'hôte ajoute des robots.');
    if (salle.joueurs.length >= MAX_JOUEURS) refuser('La salle est complète (' + MAX_JOUEURS + ' joueurs).');
    const pris = salle.joueurs.map((j) => j.nom.toLowerCase());
    const nom = NOMS_ROBOTS.find((n) => !pris.includes(n.toLowerCase())) || ('Robot ' + (salle.joueurs.length + 1));
    const jetonRobot = 'robot-' + Array.from(crypto.getRandomValues(new Uint8Array(8)), (o) => o.toString(16).padStart(2, '0')).join('');
    salle.joueurs.push(Object.assign(nouveauJoueur(jetonRobot, nom, couleurLibre(salle)), { robot: true }));
    noter(salle, 'Le robot ' + nom + ' rejoint la salle.');
    return;
  }
  if (action === 'retirerRobot') {
    if (salle.phase !== 'attente') refuser('La partie a déjà commencé.');
    if (salle.hote !== jeton) refuser('Seul l\'hôte retire des robots.');
    const k = parseInt(valeur, 10);
    const r = salle.joueurs[k];
    if (!r || !r.jeton.startsWith('robot-')) refuser('Ce joueur n\'est pas un robot.');
    salle.joueurs.splice(k, 1);
    return;
  }
  if (action === 'robot') {
    if (salle.phase !== 'jeu') refuser('Pas de partie en cours.');
    const k = parseInt(valeur, 10);
    const r = salle.joueurs[k];
    if (!r || r.faillite) refuser('Joueur introuvable.');
    r.robot = !r.robot;
    noter(salle, r.robot ? 'Un robot joue maintenant pour ' + r.nom + '.' : r.nom + ' reprend la main.');
    return;
  }
  if (action === 'nouvelle') {
    if (salle.phase !== 'fin') refuser('La partie n\'est pas finie.');
    if (salle.hote !== jeton) refuser('Seul l\'hôte relance une partie.');
    salle.phase = 'attente';
    salle.classement = null;
    noter(salle, 'Nouvelle partie : l\'hôte la lance quand tout le monde est là.');
    return;
  }
  if (action === 'quitter' && salle.phase === 'attente') {
    salle.joueurs.splice(moi, 1);
    if (salle.hote === jeton) salle.hote = salle.joueurs.length ? salle.joueurs[0].jeton : null;
    return;
  }
  if (salle.phase !== 'jeu') refuser('Pas de partie en cours.');
  salle.anim = { id: ((salle.anim && salle.anim.id) || 0) + 1, etapes: [] };

  if (action === 'quitter') {
    if (salle.joueurs[moi].faillite) return;
    noter(salle, salle.joueurs[moi].nom + ' abandonne la partie.');
    const sonTour = salle.tour === moi;
    faillite(salle, moi);
    if (salle.phase === 'jeu') resoudreEnchereSiFinie(salle);
    if (salle.etape === 'dette') verifierDettes(salle);
    else if (sonTour) apresCoup(salle);
    salle.dernierCoup = Date.now();
    return;
  }

  if (GESTION.includes(action)) {
    if (salle.etape === 'enchere') refuser('Attends la fin de l\'enchère.');
    if (salle.etape === 'dette' && salle.joueurs[moi].argent >= 0) refuser('Attends que les dettes soient réglées.');
    actionGestion(salle, moi, action, parseInt(valeur, 10));
    verifierDettes(salle);
    return;
  }
  if (ECHANGE.includes(action)) {
    actionEchange(salle, moi, action, valeur);
    salle.dernierCoup = Date.now();
    return;
  }
  if (action === 'robotDette') {
    const r = salle.joueurs[moi];
    if (!r.robot || salle.etape !== 'dette' || r.argent >= 0) refuser('Rien à régler.');
    liquider(salle, moi, 0);
    if (r.argent < 0) faillite(salle, moi);
    verifierDettes(salle);
    salle.dernierCoup = Date.now();
    return;
  }
  if (action === 'faillite') {
    if (salle.etape !== 'dette' || salle.joueurs[moi].argent >= 0) refuser('Tu n\'as pas de dette à régler.');
    noter(salle, salle.joueurs[moi].nom + ' déclare faillite.');
    faillite(salle, moi);
    verifierDettes(salle);
    salle.dernierCoup = Date.now();
    return;
  }
  if (ENCHERE.includes(action)) {
    actionEnchere(salle, moi, action, valeur);
    salle.dernierCoup = Date.now();
    return;
  }

  let qui = moi;
  if (action === 'forcer') {
    if (salle.etape === 'enchere') refuser('Une enchère est en cours.');
    if (Date.now() - salle.dernierCoup < DELAI_INACTIF_S * 1000) refuser('Laisse-lui encore un peu de temps.');
    if (salle.etape === 'dette') {
      const absent = debiteurs(salle).find((i) => i !== moi);
      if (absent === undefined) refuser('C\'est à toi de régler ta dette.');
      const a = salle.joueurs[absent];
      noter(salle, salle.joueurs[moi].nom + ' règle la dette de ' + a.nom + ' à sa place.');
      liquider(salle, absent, 0);
      if (a.argent < 0) faillite(salle, absent);
      verifierDettes(salle);
      salle.dernierCoup = Date.now();
      return;
    }
    if (salle.tour === moi) refuser('C\'est ton tour, joue !');
    qui = salle.tour;
    noter(salle, salle.joueurs[moi].nom + ' joue à la place de ' + salle.joueurs[qui].nom + '.');
    if (salle.etape === 'achat') action = 'passer';
    else if (salle.etape === 'carte') action = 'okCarte';
    else action = 'lancer';
  } else if (salle.tour !== moi) {
    refuser('Ce n\'est pas ton tour.');
  }

  const j = salle.joueurs[qui];
  if (action === 'lancer') {
    if (salle.etape !== 'lancer' && salle.etape !== 'prison') refuser('Termine d\'abord ton action.');
    actionLancer(salle);
  } else if (action === 'okCarte') {
    if (salle.etape !== 'carte' || !salle.carteEnAttente) refuser('Aucune carte à lire.');
    appliquerCarte(salle);
  } else if (action === 'acheter' || action === 'passer') {
    if (salle.etape !== 'achat') refuser('Rien à acheter pour l\'instant.');
    actionAchat(salle, action === 'acheter');
  } else if (action === 'caution') {
    if (salle.etape !== 'prison') refuser('Tu n\'es pas au poste.');
    if (j.argent < CAUTION) refuser('Pas assez d\'argent pour la caution.');
    j.argent -= CAUTION;
    j.enPrison = false;
    salle.etape = 'lancer';
    noter(salle, j.nom + ' paie ' + CAUTION + ' € de caution et sort du poste.');
  } else if (action === 'carte') {
    if (salle.etape !== 'prison') refuser('Tu n\'es pas au poste.');
    if (!j.cartesSortie.length) refuser('Tu n\'as pas de carte « Libéré sur parole ».');
    const paquet = j.cartesSortie.shift();
    salle.paquets[paquet].push(CARTES[paquet].findIndex((c) => c.sortie));
    j.enPrison = false;
    salle.etape = 'lancer';
    noter(salle, j.nom + ' utilise sa carte « Libéré sur parole ».');
  } else {
    refuser('Action inconnue.');
  }
  salle.dernierCoup = Date.now();
}

/* ----------------------------------------------------------------- robots */

/** Durée de l'animation du dernier coup sur les téléphones (même rythme que le client). */
function dureeAnimation(anim) {
  if (!anim) return 0;
  let ms = 300;
  for (const e of anim.etapes) {
    if (e.t === 'des') ms += 1030;
    else if (e.t === 'pas') ms += 260 * (((e.recule ? e.de - e.a : e.a - e.de) + PLATEAU.length) % PLATEAU.length + 1) + 300;
    else if (e.t === 'saut') ms += 800;
    else ms += 1400;
  }
  return ms;
}

function robotEstDu(salle) {
  if (salle.phase !== 'jeu' || !salle.joueurs.some((j) => j.robot && !j.faillite)) return false;
  return Date.now() - (salle.horodatage || 0) >= dureeAnimation(salle.anim) + REFLEXION_ROBOT_MS;
}

/** Coup qu'un robot doit jouer maintenant, ou null si c'est à un humain. */
/** Valeur d'un lot de biens pour `idx` une fois l'échange fait (quartier complété = bonus). */
function valeurLot(salle, idx, cases, proprioApres) {
  let total = 0;
  for (const i of cases) {
    const c = PLATEAU[i];
    total += salle.hypo[i] ? c.prix / 2 : c.prix;
    if (c.t === 'rue') {
      const complet = ruesDuQuartier(c.g).every((k) => proprioApres(k) === idx);
      if (complet) total += c.prix;
    }
  }
  return total;
}

function robotAccepteEchange(salle, e) {
  const apres = (k) => (e.donne.includes(k) ? e.a : e.recoit.includes(k) ? e.de : salle.proprio[k]);
  const gagne = valeurLot(salle, e.a, e.donne, apres) + e.argentDonne;
  // Ce que le robot cède vaut aussi ce que l'autre y gagne (quartier complété en face).
  const cede = valeurLot(salle, e.de, e.recoit, apres) + e.argentRecu;
  return gagne >= cede * 1.15 && salle.joueurs[e.a].argent - e.argentRecu >= 50;
}

function choisirCoupRobot(salle) {
  const J = salle.joueurs;
  if (salle.echange && J[salle.echange.a] && J[salle.echange.a].robot && salle.etape !== 'enchere') {
    const e = salle.echange;
    return { jeton: J[e.a].jeton, action: robotAccepteEchange(salle, e) ? 'accepterEchange' : 'refuserEchange' };
  }
  // Un robot retire sa proposition restée sans réponse une minute.
  if (salle.echange && J[salle.echange.de].robot && Date.now() - salle.echange.depuis > 60000 && salle.etape !== 'enchere') {
    return { jeton: J[salle.echange.de].jeton, action: 'annulerEchange' };
  }
  if (salle.etape === 'enchere' && salle.enchere) {
    const e = salle.enchere;
    const r = enLice(salle).find((i) => J[i].robot);
    if (r === undefined) return null;
    const c = PLATEAU[e.case];
    const mise = e.prix + (e.prix < c.prix / 2 ? 50 : 10);
    // Plus offensif si le bien complète (ou bloque) un quartier.
    const utile = c.t === 'rue' && ruesDuQuartier(c.g).some((k) => k !== e.case && salle.proprio[k] !== null);
    const veut = mise <= c.prix * (utile ? 1.5 : 1) && J[r].argent - mise >= 100;
    return { jeton: J[r].jeton, action: veut ? 'miser' : 'passerEnchere', valeur: mise };
  }
  if (salle.etape === 'dette') {
    const r = debiteurs(salle).find((i) => J[i].robot);
    return r === undefined ? null : { jeton: J[r].jeton, action: 'robotDette' };
  }
  const t = J[salle.tour];
  if (!t || !t.robot || t.faillite) return null;
  const coup = (action, valeur) => ({ jeton: t.jeton, action, valeur });
  if (salle.etape === 'achat') return coup(t.argent - PLATEAU[t.position].prix >= 50 ? 'acheter' : 'passer');
  if (salle.etape === 'carte') return coup('okCarte');
  if (salle.etape === 'prison') return coup(t.cartesSortie.length ? 'carte' : (t.argent >= 400 ? 'caution' : 'lancer'));
  if (salle.etape !== 'lancer') return null;
  // Avant de lancer : proposer d'acheter la rue qui lui manque pour compléter un quartier…
  if (!salle.echange) {
    for (let g = 0; g < GROUPES.length; g++) {
      const rues = ruesDuQuartier(g);
      const manque = rues.filter((k) => salle.proprio[k] !== salle.tour);
      if (manque.length !== 1 || manque.length === rues.length) continue;
      const k = manque[0];
      const autre = salle.proprio[k];
      if (autre === null || J[autre].faillite || rues.some((x) => salle.maisons[x] > 0)) continue;
      const cle = salle.tour + '-' + k;
      const refus = (salle.refusRobot || {})[cle] || 0;
      if (refus >= OFFRE_ROBOT_REFUS_MAX) continue; // abandon : il cherche une autre cible
      const essai = (salle.essaisEchange || {})[cle];
      if (essai !== undefined && salle.tourNo - essai < OFFRE_ROBOT_PAUSE_TOURS) continue;
      const offre = Math.ceil((PLATEAU[k].prix * (OFFRE_ROBOT_BASE + OFFRE_ROBOT_HAUSSE * refus)) / 10) * 10;
      if (t.argent - offre < 150) continue;
      return Object.assign(coup('proposerEchange', { a: autre, recoit: [k], argentDonne: offre }), { essai: salle.tour + '-' + k });
    }
  }
  // … puis construire s'il a un quartier et de la marge, ou lever une hypothèque.
  const mien = proprietesDe(salle, salle.tour);
  for (const i of mien) {
    const c = PLATEAU[i];
    if (c.t !== 'rue' || salle.maisons[i] >= 5 || !quartierEntier(salle, c.g, salle.tour)) continue;
    const rues = ruesDuQuartier(c.g);
    if (rues.some((k) => salle.hypo[k])) continue;
    if (salle.maisons[i] > Math.min(...rues.map((k) => salle.maisons[k]))) continue;
    if (t.argent - c.maison >= 200) return coup('construire', i);
  }
  const hypo = mien.find((i) => salle.hypo[i] && t.argent - PLATEAU[i].leve >= 500);
  if (hypo !== undefined) return coup('lever', hypo);
  return coup('lancer');
}

/**
 * Fait jouer un robot si c'est son tour et que l'animation précédente est
 * finie. Appelé à chaque interrogation d'état : ce sont les téléphones
 * connectés qui « réveillent » les robots.
 */
async function faireJouerRobot(env, code, courant) {
  if (!robotEstDu(courant.salle)) return courant;
  const coup = choisirCoupRobot(courant.salle);
  if (!coup) return courant;
  let salle = JSON.parse(JSON.stringify(courant.salle));
  try {
    appliquerAction(salle, coup.jeton, coup.action, coup.valeur);
  } catch (err) {
    if (!(err instanceof ErreurJeu)) throw err;
    // Coup refusé (cas imprévu) : le robot se contente de jouer le coup le plus simple.
    salle = JSON.parse(JSON.stringify(courant.salle));
    const repli = { achat: 'passer', carte: 'okCarte', enchere: 'passerEnchere' }[salle.etape] || 'lancer';
    try { appliquerAction(salle, coup.jeton, repli); } catch (err2) { return courant; }
  }
  if (coup.essai) {
    salle.essaisEchange = salle.essaisEchange || {};
    salle.essaisEchange[coup.essai] = salle.tourNo;
  }
  salle.horodatage = Date.now();
  const version = courant.version + 1;
  const res = await bdd(env)
    .prepare('UPDATE paves_salles SET etat = ?, version = ?, maj = ? WHERE code = ? AND version = ?')
    .bind(JSON.stringify(salle), version, new Date().toISOString(), code, courant.version)
    .run();
  if (res.meta.changes === 1) return { version, salle };
  return (await lireSalle(env, code)) || courant;
}

function vuePour(salle, version, jeton) {
  const moi = indexJoueur(salle, jeton);
  return {
    code: salle.code,
    version,
    phase: salle.phase,
    moi: moi === -1 ? null : moi,
    hote: indexJoueur(salle, salle.hote),
    toursMax: salle.toursMax,
    tourNo: salle.tourNo,
    tour: salle.tour,
    etape: salle.etape,
    des: salle.des,
    derniereCarte: salle.derniereCarte,
    proprio: salle.proprio,
    maisons: salle.maisons,
    hypo: salle.hypo,
    loyers: PLATEAU.map((c, i) => (c.prix && salle.proprio[i] !== null && c.t !== 'service' ? loyerDe(salle, i) : null)),
    echange: salle.echange || null,
    enchere: salle.enchere ? {
      case: salle.enchere.case, prix: salle.enchere.prix, meneur: salle.enchere.meneur,
      passe: salle.enchere.passe, depuis: salle.enchere.depuis,
    } : null,
    delaiEnchere: DELAI_ENCHERE_S,
    anim: salle.anim || null,
    noms: PLATEAU.map((c) => [c.nom, c.court]),
    ressources: salle.joueurs.map((j, i) => (salle.phase === 'jeu' && !j.faillite ? ressources(salle, i) : 0)),
    journal: salle.journal,
    classement: salle.classement || null,
    dernierCoup: salle.dernierCoup,
    maintenant: Date.now(),
    delaiInactif: DELAI_INACTIF_S,
    joueurs: salle.joueurs.map((j, i) => ({
      nom: j.nom,
      couleur: COULEURS[j.couleur],
      argent: j.argent,
      position: j.position,
      enPrison: j.enPrison,
      essais: j.essais,
      cartesSortie: j.cartesSortie.length,
      faillite: j.faillite,
      robot: !!j.robot,
      fortune: fortune(salle, i),
    })),
  };
}

/* -------------------------------------------------------------------- D1 */

function bdd(env) {
  return env && env.DB ? env.DB : null;
}

let tablesPretes = false;
async function preparerTables(env) {
  if (tablesPretes) return;
  await bdd(env).batch([
    bdd(env).prepare('CREATE TABLE IF NOT EXISTS paves_salles (code TEXT PRIMARY KEY, version INTEGER NOT NULL, etat TEXT NOT NULL, maj TEXT NOT NULL)'),
    bdd(env).prepare('CREATE TABLE IF NOT EXISTS joueurs (nom TEXT PRIMARY KEY COLLATE NOCASE)'),
    bdd(env).prepare('CREATE TABLE IF NOT EXISTS paves_config (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL, maj TEXT NOT NULL)'),
  ]);
  tablesPretes = true;
}

async function lireNoms(env) {
  const ligne = await bdd(env).prepare("SELECT valeur FROM paves_config WHERE cle = 'noms'").first();
  if (!ligne) return {};
  try {
    const noms = JSON.parse(ligne.valeur);
    return noms && typeof noms === 'object' ? noms : {};
  } catch (err) {
    return {};
  }
}

/** Nettoie les noms envoyés par la page de réglages (cases modifiables seulement). */
function nomsValides(brut) {
  const propres = {};
  if (!brut || typeof brut !== 'object') return propres;
  for (const [cle, v] of Object.entries(brut)) {
    const i = parseInt(cle, 10);
    if (!nomModifiable(i) || !v || typeof v !== 'object') continue;
    const nom = String(v.nom || '').trim().replace(/\s+/g, ' ').slice(0, NOM_MAX);
    const court = String(v.court || '').trim().replace(/\s+/g, ' ').slice(0, COURT_MAX);
    if (!nom && !court) continue;
    if (nom === NOMS_ORIGINE[i].nom && (!court || court === NOMS_ORIGINE[i].court)) continue;
    propres[i] = { nom: nom || NOMS_ORIGINE[i].nom, court };
  }
  return propres;
}

async function ecrireNoms(env, noms) {
  await bdd(env)
    .prepare("INSERT INTO paves_config (cle, valeur, maj) VALUES ('noms', ?, ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur, maj = excluded.maj")
    .bind(JSON.stringify(noms), new Date().toISOString())
    .run();
}

async function lireSalle(env, code) {
  const ligne = await bdd(env).prepare('SELECT version, etat FROM paves_salles WHERE code = ?').bind(code).first();
  if (!ligne) return null;
  try {
    const salle = JSON.parse(ligne.etat);
    // Salles créées avant les constructions : champs manquants.
    if (!salle.maisons) salle.maisons = PLATEAU.map(() => 0);
    if (!salle.hypo) salle.hypo = PLATEAU.map(() => false);
    if (salle.enchere === undefined) salle.enchere = null;
    return { version: ligne.version, salle };
  } catch (err) {
    return null;
  }
}

/** Relit, modifie, et n'écrit que si personne n'a joué entre-temps ; sinon on recommence. */
async function modifierSalle(env, code, modifier) {
  for (let essai = 0; essai < 4; essai++) {
    const courant = await lireSalle(env, code);
    if (!courant) refuser('Salle introuvable ou expirée.');
    modifier(courant.salle);
    const version = courant.version + 1;
    const res = await bdd(env)
      .prepare('UPDATE paves_salles SET etat = ?, version = ?, maj = ? WHERE code = ? AND version = ?')
      .bind(JSON.stringify(courant.salle), version, new Date().toISOString(), code, courant.version)
      .run();
    if (res.meta.changes === 1) return { version, salle: courant.salle };
  }
  refuser('Trop de coups en même temps, réessaie.');
}

async function creerSalle(env, toursMax) {
  const limite = new Date(Date.now() - SALLE_TTL_H * 3600 * 1000).toISOString();
  await bdd(env).prepare('DELETE FROM paves_salles WHERE maj < ?').bind(limite).run();
  for (let essai = 0; essai < 5; essai++) {
    const code = nouveauCode();
    const res = await bdd(env)
      .prepare('INSERT OR IGNORE INTO paves_salles (code, version, etat, maj) VALUES (?, 1, ?, ?)')
      .bind(code, JSON.stringify(nouvelleSalle(code, toursMax)), new Date().toISOString())
      .run();
    if (res.meta.changes === 1) return code;
  }
  refuser('Impossible de créer une salle, réessaie.');
}

async function lireJoueurs(env) {
  const res = await bdd(env).prepare('SELECT nom FROM joueurs ORDER BY nom COLLATE NOCASE').all();
  return (res.results || []).map((l) => l.nom);
}

async function ajouterJoueur(env, nom) {
  await bdd(env).prepare('INSERT OR IGNORE INTO joueurs (nom) VALUES (?)').bind(nom).run();
}

/* ------------------------------------------------------------------ page */

const CSS = `
  :root{ --bg:#1B2A41; --panel:#FDF6E3; --ink:#1B2A41; --muted:#9FB0C8; --or:#F2C14E; --plateau:#E8F1E4; }
  *{box-sizing:border-box;}
  body{ margin:0; min-height:100vh; background:var(--bg); color:var(--panel);
    font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding:12px 12px 28px; }
  @media (max-width:520px){ body{padding:6px 4px 28px;} .bloc, .joueurs{margin-left:4px; margin-right:4px;} }
  .wrap{max-width:640px; margin:0 auto;}
  .centre .titre-prop{font-size:clamp(0.6rem, 2.5cqw, 1.9rem); width:min(92%, 62cqw);}
  /* Écran large (PC) : plateau à gauche, aussi grand que la hauteur le permet ; infos à droite. */
  @media (min-width:1000px){
    .wrap.large{max-width:1800px;}
    .cadre-jeu{display:grid; grid-template-columns:min(calc(100vh - 28px), 66vw) minmax(320px, 1fr);
      gap:18px; align-items:start;}
    .col-infos{max-height:calc(100vh - 28px); overflow-y:auto; padding-right:4px;}
    .col-infos > .second:first-child, .col-infos > .bloc:first-child{margin-top:0;}
  }
  h1{text-align:center; font-size:1.6rem; margin:4px 0 2px; letter-spacing:0.5px;}
  .sous{text-align:center; color:var(--muted); font-size:0.85rem; margin-bottom:14px;}
  .bloc{background:rgba(255,255,255,0.07); border-radius:14px; padding:12px; margin-bottom:10px;}
  .bloc h2{font-size:1rem; margin:0 0 8px;}
  label{display:block; font-size:0.8rem; color:var(--muted); margin:10px 0 4px;}
  input, select{ width:100%; padding:10px 8px; border-radius:10px; border:1px solid #ccc;
    font-size:1rem; text-align:center; color:var(--ink); background:#fff; }
  button{border:none; border-radius:10px; padding:10px 14px; font-size:0.95rem; font-weight:600; cursor:pointer;}
  button:disabled{opacity:0.45; cursor:default;}
  .principal{background:var(--or); color:var(--ink); width:100%; font-size:1.05rem; margin-top:10px;}
  .second{background:rgba(255,255,255,0.15); color:var(--panel); width:100%; margin-top:8px;}
  .discret{background:none; color:var(--muted); text-decoration:underline; font-weight:400; width:100%; margin-top:10px;}
  .statut{min-height:1.2em; text-align:center; font-size:0.85rem; color:var(--muted); margin:6px 0;}
  .statut.erreur{color:#FF8A80;}
  .code{font-size:2.4rem; font-weight:800; letter-spacing:6px; text-align:center; color:var(--or);}
  .liste-j{list-style:none; padding:0; margin:8px 0;}
  .liste-j li{display:flex; align-items:center; gap:8px; padding:6px 0;}
  .pastille{width:14px; height:14px; border-radius:50%; display:inline-block; flex:none; border:2px solid #fff;}

  .plateau{ container-type:inline-size; display:grid; grid-template-columns:minmax(0, 1.9fr) repeat(9, minmax(0, 1fr)) minmax(0, 1.9fr);
    grid-template-rows:minmax(0, 1.9fr) repeat(9, minmax(0, 1fr)) minmax(0, 1.9fr); gap:1px; background:#3D5A40;
    border:2px solid #3D5A40; border-radius:6px; aspect-ratio:1/1; width:100%; color:var(--ink); }
  .case{ background:var(--plateau); position:relative; overflow:hidden; display:flex; min-width:0; min-height:0;
    align-items:stretch; cursor:pointer; line-height:1.05; text-align:center; }
  /* Bande de couleur côté intérieur du plateau ; le nom juste à côté d'elle, le prix à l'autre bout. */
  .case.bas{flex-direction:column;} .case.haut{flex-direction:column-reverse;}
  .case.haut .texte{flex-direction:column-reverse;}
  .case.bas .bande + .texte .nom, .tourne .bande + .texte .nom{margin-top:0.35cqw;}
  .case.haut .bande + .texte .nom{margin-bottom:0.35cqw;}
  /* Côtés gauche et droit : la case du bas, tournée d'un quart de tour (bande vers le centre). */
  .case.gauche, .case.droite{display:block;}
  .tourne{position:absolute; left:50%; top:50%; display:flex; flex-direction:column;
    width:calc((100cqw - 10px) / 12.8); height:calc((100cqw - 10px) * 1.9 / 12.8);
    transform:translate(-50%, -50%) rotate(90deg);}
  .case.droite .tourne{transform:translate(-50%, -50%) rotate(-90deg);}
  .case .bande{flex:none; display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:1px;}
  .case.bas .bande, .case.haut .bande, .tourne .bande{height:20%; width:100%;}
  .case .texte{flex:1; display:flex; flex-direction:column; align-items:center; justify-content:space-between;
    padding:0.6cqw 1px; min-width:0; min-height:0;}
  .case.coin .texte{justify-content:center;}
  .case > .texte:first-child, .tourne > .texte:first-child{padding-top:3px;}
  .logo svg{display:block; margin:0 auto;}
  .logo.train svg{width:clamp(12px, 3.6cqw, 46px); height:auto;}
  .logo.prison svg{width:clamp(18px, 5.4cqw, 70px); height:auto;}
  .logo.caisse svg{width:clamp(16px, 4.6cqw, 60px); height:auto;}
  .ico-titre svg{display:inline-block; width:1.6em; height:auto; vertical-align:-3px;}
  .case .nom{font-size:clamp(5.5px, 1.55cqw, 20.7px); word-break:break-word; hyphens:auto;}
  .case .ico{font-size:clamp(8px, 2.4cqw, 32.2px); line-height:1;}
  .case .prix{font-size:clamp(7.5px, 2.25cqw, 27.6px); font-weight:800; color:#1B2A41; margin-top:1px;}
  .case.coin .texte{font-weight:700;} .case.coin .nom{font-size:clamp(6.5px, 1.8cqw, 25.3px);}
  .case .prix.taxe{color:#B00020;}
  .case .hypo{font-size:clamp(4.5px, 1.25cqw, 18.4px); font-weight:800; color:#B00020; max-width:100%; overflow:hidden;}
  .maison{width:clamp(6px, 1.85cqw, 25.3px); height:clamp(6px, 1.85cqw, 25.3px); background:#1FA84A;
    border:1px solid #0B5E25; border-radius:2px; box-shadow:0 1px 1px rgba(0,0,0,0.35);}
  .hotel{width:clamp(12px, 3.8cqw, 50.6px); height:clamp(8px, 2.4cqw, 29.9px); background:#D62828;
    border:1px solid #7A0A0A; border-radius:2px; box-shadow:0 1px 1px rgba(0,0,0,0.35);}
  .enchere{background:#fff; border:2px solid var(--or); border-radius:8px; padding:5px 8px;
    font-size:clamp(0.65rem, 2.6cqw, 2.07rem); max-width:96%;}
  .gestion{display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;}
  .gestion button{flex:1 1 45%; background:rgba(255,255,255,0.15); color:var(--panel); padding:8px;}
  .gestion button.btn-or{background:var(--or); color:var(--ink);}
  .titre-mini.hypo{opacity:0.35;}
  .echange{border:2px solid var(--or); margin-top:10px;}
  .echange h3{font-size:0.85rem; margin:10px 0 4px; color:var(--or);}
  .echange .colonnes{display:grid; grid-template-columns:1fr 1fr; gap:10px;}
  .echange .bien{display:flex; align-items:center; gap:4px; font-size:0.82rem; padding:3px 0;}
  .echange .bien input{width:18px; height:18px; flex:none; margin:0;}
  .echange select{margin-bottom:4px;}
  .case-robot{display:flex; align-items:center; gap:4px; margin:6px 0 0; font-size:0.8rem; color:var(--muted); cursor:pointer;}
  .case-robot input{width:18px; height:18px; margin:0; flex:none;}
  button.mini{margin-left:auto; padding:3px 8px; font-size:0.75rem; background:rgba(255,255,255,0.15); color:var(--panel);}
  table.loyers{width:100%; font-size:0.8rem; border-collapse:collapse; margin-top:6px; color:var(--muted);}
  table.loyers td{padding:2px 0;} table.loyers td:last-child{text-align:right;}
  table.loyers tr.actuel td{color:var(--or); font-weight:700;}
  .case.choisie{outline:2px solid #000; outline-offset:-2px; z-index:2;}
  .case .pions{position:absolute; display:flex; flex-wrap:wrap; align-items:center; align-content:center;
    justify-content:center; gap:1px; pointer-events:none;}
  /* Pions au milieu de la case ; plusieurs pions se chevauchent légèrement. */
  .case .pions{inset:0;}
  .case .pion + .pion{margin-left:-7px;}
  .case .pions{flex-wrap:nowrap; overflow:visible; z-index:4;}
  .case{overflow:visible;} .case .texte, .case .bande{overflow:hidden;}
  .case .nom.long{font-size:clamp(5px, 1.3cqw, 18.4px);} .case .nom.tres-long{font-size:clamp(4.5px, 1.15cqw, 16.1px);}
  .pion{width:clamp(18px, 6cqw, 69px); height:clamp(18px, 6cqw, 69px); border-radius:50%; flex:none;
    border:2px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,0.8); color:#fff; font-weight:900;
    font-size:clamp(10px, 3.3cqw, 39.1px); display:flex; align-items:center; justify-content:center;
    text-shadow:0 0 2px #000;}
  .pion.actif{animation:pulse 1s infinite; z-index:3;}
  .pion.retenu{border-color:#1B2A41; border-radius:3px; position:relative;
    background-image:repeating-linear-gradient(90deg, transparent 0 3px, rgba(0,0,0,0.75) 3px 5px) !important;}
  .pion.retenu::after{content:'🔒'; position:absolute; top:-7px; right:-8px; font-size:12px; text-shadow:none;}
  @keyframes pulse{50%{transform:scale(1.2);}}
  .centre{ grid-row:2 / 11; grid-column:2 / 11; background:#F6FAF3; display:flex; flex-direction:column;
    align-items:center; justify-content:center; padding:5px; text-align:center; gap:4px; color:var(--ink);
    overflow:hidden; }
  .centre .titre{font-weight:800; font-size:clamp(0.8rem, 3.4cqw, 2.99rem); color:#3D5A40;}
  .centre .info{font-size:clamp(0.7rem, 2.8cqw, 2.18rem);}
  .centre .message{font-size:clamp(0.75rem, 3cqw, 2.3rem); font-weight:600; min-height:1.2em; padding:0 4px;}
  .des{font-size:clamp(1.8rem, 9cqw, 6.9rem); line-height:1;}
  .des.roule{animation:roule 0.15s infinite;}
  @keyframes roule{50%{transform:rotate(12deg) scale(1.05);}}
  .carte-tiree{background:#fff; border-radius:10px; padding:10px; font-size:clamp(0.75rem, 3.2cqw, 2.3rem);
    border:3px solid; max-width:92%; box-shadow:0 3px 10px rgba(0,0,0,0.2);}
  .carte-tiree b{display:block; margin-bottom:4px;}
  .carte-tiree.surprise{border-color:#F28C28;} .carte-tiree.mairie{border-color:#1F5FBF;}
  .case .ico{display:block;} .ico-titre svg{vertical-align:-3px;}
  .titre-prop{background:#fff; color:var(--ink); border:2px solid #1B2A41; border-radius:6px; width:min(92%, 260px);
    font-size:clamp(0.6rem, 2.5vw, 0.85rem); box-shadow:0 3px 10px rgba(0,0,0,0.2); overflow:hidden;}
  .titre-prop .entete{padding:4px; color:#fff; font-weight:800; text-shadow:0 0 3px rgba(0,0,0,0.6);}
  .titre-prop .entete small{display:block; font-weight:600; font-size:0.8em;}
  .titre-prop .corps{padding:3px 8px;}
  .titre-prop .l{display:flex; justify-content:space-between; padding:1px 0;}
  .titre-prop .l.fort{font-weight:800; font-size:1.1em;}
  .titre-prop .l.actuel{color:#B5179E; font-weight:800;}
  .titre-prop .sep{border-top:1px solid #ccd; margin:2px 0;}
  .centre button{padding:7px 10px; font-size:clamp(0.75rem, 3cqw, 2.18rem); margin:2px;}
  .centre .boutons{display:flex; flex-wrap:wrap; justify-content:center;}
  .btn-or{background:var(--or); color:var(--ink);} .btn-gris{background:#D9E2D5; color:var(--ink);}
  .btn-rouge{background:#E63946; color:#fff;}
  .dette{border:2px solid #E63946;}

  .joueurs{display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:8px; margin-top:10px;}
  .fiche{background:rgba(255,255,255,0.07); border-radius:12px; padding:8px; border-left:5px solid;}
  .fiche.son-tour{background:rgba(242,193,78,0.18);}
  .fiche.ko{opacity:0.45;}
  .fiche .haut{display:flex; justify-content:space-between; font-weight:700;}
  .fiche .bas{font-size:0.75rem; color:var(--muted); margin-top:2px;}
  .titres{display:flex; flex-wrap:wrap; gap:3px; margin-top:5px;}
  .titre-mini{width:12px; height:16px; border-radius:2px; border:1px solid rgba(255,255,255,0.6);}
  .detail{font-size:0.85rem;}
  .detail .ligne{display:flex; justify-content:space-between; padding:2px 0;}
  .journal{font-size:0.8rem; color:var(--muted); list-style:none; padding:0; margin:0;}
  .journal li{padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.06);}
  .journal li:last-child{color:var(--panel);}
  table.classement{width:100%; border-collapse:collapse;}
  table.classement td{padding:6px 4px; border-bottom:1px solid rgba(255,255,255,0.1);}
`;

const FAVICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
  + '<rect width="64" height="64" rx="14" fill="#1B2A41"/>'
  + '<rect x="14" y="14" width="36" height="36" rx="4" fill="#E8F1E4"/>'
  + '<rect x="14" y="14" width="36" height="10" rx="3" fill="#E03B3B"/>'
  + '<text x="32" y="46" font-size="20" font-family="system-ui, sans-serif" '
  + 'font-weight="800" text-anchor="middle" fill="#1B2A41">P</text></svg>';

/* ------------------------------------------------------------ client web */

/* Exécuté tel quel dans le navigateur (sérialisé par toString) :
   ne doit utiliser que les globales injectées dans la page. */
function client() {
  var app = document.getElementById('app');
  var ETAT = null;
  var CODE = null;
  var STATUT = '';
  var ERREUR = false;
  var CHOISIE = null;
  var ECART = 0;
  var enCours = false;
  var echecs = 0;

  var JETON = localStorage.getItem('paves:jeton');
  if (!JETON) {
    JETON = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + String(Math.random()).slice(2));
    localStorage.setItem('paves:jeton', JETON);
  }
  var MON_NOM = localStorage.getItem('paves:nom') || '';

  function el(balise, classe, texte) {
    var n = document.createElement(balise);
    if (classe) n.className = classe;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }
  function bouton(texte, classe, action) {
    var b = el('button', classe, texte);
    b.onclick = action;
    return b;
  }
  function euros(n) { return n.toLocaleString('fr-FR') + ' €'; }

  function dire(texte, estErreur) {
    STATUT = texte || '';
    ERREUR = !!estErreur;
    var zone = document.getElementById('statut');
    if (zone) { zone.textContent = STATUT; zone.className = 'statut' + (ERREUR ? ' erreur' : ''); }
  }
  function zoneStatut() {
    var z = el('div', 'statut' + (ERREUR ? ' erreur' : ''), STATUT);
    z.id = 'statut';
    return z;
  }
  function panneReseau(err) {
    return /failed to fetch|networkerror|load failed|network request failed/i.test(String(err && err.message ? err.message : err));
  }

  function lireReponse(r) {
    return r.json().then(function (d) {
      if (!r.ok) throw new Error(d && d.erreur ? d.erreur : 'Erreur ' + r.status);
      return d;
    });
  }
  function poster(chemin, corps) {
    if (enCours) return Promise.resolve(null);
    enCours = true;
    corps = corps || {};
    corps.jeton = JETON;
    if (CODE && !corps.code) corps.code = CODE;
    return fetch(chemin, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(corps) })
      .then(lireReponse)
      .then(function (d) { enCours = false; dire(''); return d; })
      .catch(function (err) {
        enCours = false;
        dire(panneReseau(err) ? "Connexion perdue : ton coup n'est pas parti, réessaie." : err.message, true);
        return null;
      });
  }
  /* Animation : le serveur résout le coup d'un bloc et en décrit les étapes
     (dés, déplacements, messages) ; chaque téléphone les rejoue au rythme
     d'un vrai plateau avant d'afficher l'état final. */
  var BROUILLON = null;
  var EDITION = false;
  var RENDU_DIFFERE = false;
  var AFF = null;
  var ANIM = null;
  var ANIM_VUE = null;
  var EN_ATTENTE = null;

  function aDuMouvement(a) {
    return a && a.etapes.some(function (e) { return e.t !== 'msg'; });
  }
  function positionDe(k) {
    return AFF ? AFF[k] : ETAT.joueurs[k].position;
  }
  function recevoir(d) {
    if (ANIM) { EN_ATTENTE = d; return; }
    var ancien = ETAT;
    if (d.noms) d.noms.forEach(function (n, i) { if (PLATEAU[i]) { PLATEAU[i].nom = n[0]; PLATEAU[i].court = n[1]; } });
    ETAT = d;
    ECART = Date.now() - d.maintenant;
    if (ETAT.moi === null) { quitterLocal(); return; }
    var nouvelle = d.anim && ANIM_VUE !== null && d.anim.id !== ANIM_VUE;
    ANIM_VUE = d.anim ? d.anim.id : 0;
    if (nouvelle && aDuMouvement(d.anim) && ancien && ancien.joueurs.length === d.joueurs.length) {
      jouerAnimation(d.anim.etapes, ancien);
      return;
    }
    rendre();
  }
  function jouerAnimation(etapes, ancien) {
    AFF = ETAT.joueurs.map(function (j, k) { return ancien.joueurs[k].position; });
    ANIM = { message: '', des: ancien.des, roule: false };
    var i = 0;
    function finir() {
      ANIM = null;
      AFF = null;
      var d = EN_ATTENTE;
      EN_ATTENTE = null;
      if (d) recevoir(d); else rendre();
    }
    function suivant() {
      if (i >= etapes.length) { setTimeout(finir, 300); return; }
      var e = etapes[i++];
      if (e.t === 'des') {
        var n = 0;
        ANIM.roule = true;
        var t = setInterval(function () {
          ANIM.des = [1 + Math.floor(Math.random() * 6), 1 + Math.floor(Math.random() * 6)];
          rendre();
          if (++n >= 7) {
            clearInterval(t);
            ANIM.roule = false;
            ANIM.des = e.des;
            rendre();
            setTimeout(suivant, 400);
          }
        }, 90);
      } else if (e.t === 'pas') {
        AFF[e.j] = e.de;
        var pas = function () {
          if (AFF[e.j] === e.a) { setTimeout(suivant, 300); return; }
          AFF[e.j] = e.recule ? (AFF[e.j] + PLATEAU.length - 1) % PLATEAU.length : (AFF[e.j] + 1) % PLATEAU.length;
          rendre();
          setTimeout(pas, 260);
        };
        rendre();
        setTimeout(pas, 260);
      } else if (e.t === 'saut') {
        setTimeout(function () { AFF[e.j] = e.a; rendre(); setTimeout(suivant, 500); }, 300);
      } else {
        ANIM.message = e.texte;
        rendre();
        setTimeout(suivant, 1400);
      }
    }
    suivant();
  }
  function rafraichir(forcer) {
    if (!CODE) return Promise.resolve();
    var url = '/api/etat?code=' + encodeURIComponent(CODE) + '&jeton=' + encodeURIComponent(JETON)
      + '&v=' + (forcer || !ETAT ? 0 : ETAT.version);
    return fetch(url).then(lireReponse).then(function (d) {
      if (echecs > 0) { echecs = 0; dire(''); }
      if (d.inchange) return;
      recevoir(d);
    }).catch(function (err) {
      echecs++;
      if (!panneReseau(err) && /introuvable/i.test(err.message)) { quitterLocal(); dire(err.message, true); return; }
      if (echecs >= 2 || !panneReseau(err)) dire(panneReseau(err) ? 'Connexion interrompue, reprise dès que le réseau revient…' : err.message, true);
    });
  }
  function agir(action, valeur) {
    return poster('/api/action', { action: action, valeur: valeur }).then(function (d) { if (d) recevoir(d); });
  }
  function entrer(d) {
    CODE = d.code;
    localStorage.setItem('paves:code', CODE);
    history.replaceState(null, '', '/?code=' + CODE);
    recevoir(d);
  }
  function quitterLocal() {
    CODE = null;
    ETAT = null;
    localStorage.removeItem('paves:code');
    history.replaceState(null, '', '/');
    rendre();
  }

  setInterval(function () { rafraichir(false); }, 1500);
  // Le bouton « Jouer à sa place » apparaît après le délai même sans nouveau coup.
  setInterval(function () {
    if (!ANIM && ETAT && ETAT.phase === 'jeu' && (ETAT.tour !== ETAT.moi || ETAT.etape === 'enchere' || ETAT.etape === 'dette')) rendre();
  }, 5000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden && CODE) rafraichir(true); });
  window.addEventListener('online', function () { if (CODE) rafraichir(true); });

  /* --------------------------------------------------------------- accueil */

  function champNom() {
    var input = el('input');
    input.id = 'nom';
    input.placeholder = 'Ton prénom';
    input.maxLength = 20;
    input.value = MON_NOM;
    input.setAttribute('list', 'connus');
    var liste = el('datalist');
    liste.id = 'connus';
    JOUEURS.forEach(function (n) { var o = el('option'); o.value = n; liste.appendChild(o); });
    var f = document.createDocumentFragment();
    f.appendChild(input);
    f.appendChild(liste);
    return f;
  }
  function nomSaisi() {
    var nom = document.getElementById('nom').value.trim();
    if (!nom) { dire('Choisis ton nom.', true); return null; }
    MON_NOM = nom;
    localStorage.setItem('paves:nom', nom);
    return nom;
  }

  function rendreAccueil() {
    app.appendChild(el('h1', '', 'Pavés de Paris'));
    app.appendChild(el('div', 'sous', 'Achète les rues de Paris, encaisse les loyers, ruine tes amis.'));

    var b = el('div', 'bloc');
    b.appendChild(el('label', '', 'Ton nom'));
    b.appendChild(champNom());
    app.appendChild(b);

    var rej = el('div', 'bloc');
    rej.appendChild(el('h2', '', 'Rejoindre une salle'));
    var code = el('input');
    code.id = 'code';
    code.placeholder = 'Code (ex. F78N)';
    code.maxLength = 4;
    code.style.textTransform = 'uppercase';
    code.value = new URLSearchParams(location.search).get('code') || '';
    rej.appendChild(code);
    rej.appendChild(bouton('Rejoindre', 'principal', function () {
      var nom = nomSaisi();
      if (!nom) return;
      poster('/api/rejoindre', { code: code.value, nom: nom }).then(function (d) { if (d) entrer(d); });
    }));
    app.appendChild(rej);

    var cre = el('div', 'bloc');
    cre.appendChild(el('h2', '', 'Créer une salle'));
    cre.appendChild(el('label', '', 'Durée de la partie'));
    var tours = el('select');
    tours.id = 'tours';
    TOURS.forEach(function (t) {
      var o = el('option', '', t ? t + ' tours (le plus riche gagne)' : 'Sans limite (jusqu’à la faillite)');
      o.value = t;
      if (t === TOURS_DEFAUT) o.selected = true;
      tours.appendChild(o);
    });
    cre.appendChild(tours);
    cre.appendChild(bouton('Créer la salle', 'principal', function () {
      var nom = nomSaisi();
      if (!nom) return;
      poster('/api/salle', { nom: nom, toursMax: tours.value }).then(function (d) { if (d) entrer(d); });
    }));
    app.appendChild(cre);
    var lien = el('a', 'discret', '✏️ Changer les noms des rues');
    lien.href = '/noms';
    lien.style.display = 'block';
    lien.style.textAlign = 'center';
    lien.style.margin = '14px 0';
    app.appendChild(lien);
    app.appendChild(zoneStatut());
  }

  function rendreAttente() {
    app.appendChild(el('h1', '', 'Pavés de Paris'));
    var b = el('div', 'bloc');
    b.appendChild(el('div', 'sous', 'Code de la salle'));
    b.appendChild(el('div', 'code', ETAT.code));
    b.appendChild(el('div', 'sous', location.origin + '/?code=' + ETAT.code));
    b.appendChild(el('div', 'sous', ETAT.toursMax ? ETAT.toursMax + ' tours, puis le plus riche gagne' : 'Sans limite de tours'));
    var ul = el('ul', 'liste-j');
    ETAT.joueurs.forEach(function (j, i) {
      var li = el('li');
      var p = el('span', 'pastille');
      p.style.background = j.couleur;
      li.appendChild(p);
      li.appendChild(el('span', '', (j.robot ? '🤖 ' : '') + j.nom + (i === ETAT.hote ? ' (hôte)' : '') + (i === ETAT.moi ? ' — toi' : '')));
      if (j.robot && ETAT.moi === ETAT.hote) {
        var retirer = bouton('retirer', 'mini', function () { agir('retirerRobot', i); });
        li.appendChild(retirer);
      }
      ul.appendChild(li);
    });
    b.appendChild(ul);
    if (ETAT.moi === ETAT.hote && ETAT.joueurs.length < MAX_JOUEURS) {
      b.appendChild(bouton('🤖 Ajouter un robot', 'second', function () { agir('ajouterRobot'); }));
    }
    if (ETAT.moi === ETAT.hote) {
      var go = bouton('Lancer la partie', 'principal', function () { agir('demarrer'); });
      go.disabled = ETAT.joueurs.length < MIN_JOUEURS;
      b.appendChild(go);
      if (ETAT.joueurs.length < MIN_JOUEURS) b.appendChild(el('div', 'sous', 'En attente d’un autre joueur…'));
    } else {
      b.appendChild(el('div', 'sous', 'L’hôte lancera la partie quand tout le monde sera là.'));
    }
    if (navigator.share) {
      b.appendChild(bouton('Partager le lien', 'second', function () {
        navigator.share({ title: 'Pavés de Paris', url: location.origin + '/?code=' + ETAT.code });
      }));
    }
    b.appendChild(bouton('Quitter la salle', 'discret', function () {
      agir('quitter').then(quitterLocal);
    }));
    app.appendChild(b);
    app.appendChild(zoneStatut());
  }

  /* --------------------------------------------------------------- plateau */

  function placeCase(i) {
    if (i <= 10) return [11, 11 - i];
    if (i <= 20) return [11 - (i - 10), 1];
    if (i <= 30) return [1, 1 + (i - 20)];
    return [1 + (i - 30), 11];
  }
  function icone(c) {
    return { depart: '⬅', poste: '', pause: '☕', police: '👮', carte: c.p === 'mairie' ? '' : '❓',
      gare: '', service: c.court === 'Gaz' ? '🔥' : '📶', taxe: '💶' }[c.t] || '';
  }
  function loyerAffiche(i) {
    var c = PLATEAU[i];
    var p = ETAT.proprio[i];
    if (p !== null && ETAT.hypo[i]) return 'aucun (hypothéqué)';
    if (c.t === 'rue' && ETAT.maisons[i]) {
      return euros(ETAT.loyers[i]) + ' (' + (ETAT.maisons[i] === 5 ? 'hôtel' : ETAT.maisons[i] + ' maison' + (ETAT.maisons[i] > 1 ? 's' : '')) + ')';
    }
    if (c.t === 'rue') {
      var entier = p !== null && PLATEAU.every(function (x, k) { return x.t !== 'rue' || x.g !== c.g || ETAT.proprio[k] === p; });
      return euros(entier ? c.loyer * 2 : c.loyer) + (entier ? ' (quartier complet)' : '');
    }
    if (c.t === 'gare') {
      var n = p === null ? 1 : PLATEAU.filter(function (x, k) { return x.t === 'gare' && ETAT.proprio[k] === p; }).length;
      return euros(25 * Math.pow(2, n - 1)) + ' (' + n + ' gare' + (n > 1 ? 's' : '') + ')';
    }
    var deux = p !== null && PLATEAU.filter(function (x, k) { return x.t === 'service' && ETAT.proprio[k] === p; }).length === 2;
    return (deux ? '10' : '4') + ' × les dés';
  }

  /** Logo de la Caisse commune : un coffre bleu rectangulaire, angles droits, ferrures dorées. */
  function logoCaisse(classe) {
    var d = el('span', classe || 'logo caisse');
    d.innerHTML = '<svg viewBox="0 0 32 22" aria-hidden="true">'
      + '<rect x="1" y="1" width="30" height="7" fill="#3A7BD5" stroke="#12356B" stroke-width="1.3"/>'
      + '<rect x="1" y="8" width="30" height="13" fill="#1F5FBF" stroke="#12356B" stroke-width="1.3"/>'
      + '<rect x="1" y="7" width="30" height="2.2" fill="#F2C14E" stroke="#12356B" stroke-width="0.7"/>'
      + '<rect x="6" y="1" width="2.2" height="20" fill="#F2C14E" stroke="#12356B" stroke-width="0.5"/>'
      + '<rect x="23.8" y="1" width="2.2" height="20" fill="#F2C14E" stroke="#12356B" stroke-width="0.5"/>'
      + '<rect x="13" y="5.5" width="6" height="7" fill="#F2C14E" stroke="#12356B" stroke-width="0.9"/>'
      + '<rect x="15.3" y="8" width="1.4" height="2.6" fill="#12356B"/></svg>';
    return d;
  }

  /** Locomotive noire vue de face, sur ses rails. */
  function logoTrain() {
    var d = el('span', 'logo train');
    d.innerHTML = '<svg viewBox="0 0 24 26" aria-hidden="true">'
      + '<path d="M6 3 Q6 1 9 1 H15 Q18 1 18 3 V17 Q18 19 16 19 H8 Q6 19 6 17 Z" fill="#141414"/>'
      + '<rect x="7.6" y="3.6" width="8.8" height="5.4" rx="1" fill="#CFE8F7"/>'
      + '<rect x="11.4" y="3.6" width="1.2" height="5.4" fill="#141414"/>'
      + '<rect x="7.6" y="10.6" width="8.8" height="1.4" fill="#3A3A3A"/>'
      + '<circle cx="8.9" cy="15" r="1.5" fill="#FFE08A"/><circle cx="15.1" cy="15" r="1.5" fill="#FFE08A"/>'
      + '<rect x="10.6" y="14.2" width="2.8" height="1.6" rx="0.4" fill="#555"/>'
      + '<path d="M8 19 L5.5 23.5 M16 19 L18.5 23.5" stroke="#141414" stroke-width="1.9" stroke-linecap="round"/>'
      + '<path d="M2.5 24.5 H21.5" stroke="#141414" stroke-width="1.6" stroke-linecap="round"/></svg>';
    return d;
  }

  /** Un bonhomme derrière les barreaux (case Poste). */
  function logoPrison() {
    var d = el('span', 'logo prison');
    d.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">'
      + '<rect x="1.5" y="1.5" width="21" height="21" fill="#F28C28" stroke="#141414" stroke-width="1.5"/>'
      + '<circle cx="12" cy="9" r="3.3" fill="#F6C9A0" stroke="#141414" stroke-width="0.8"/>'
      + '<path d="M10.4 8.4 h0.01 M13.6 8.4 h0.01" stroke="#141414" stroke-width="1.1" stroke-linecap="round"/>'
      + '<path d="M10.6 10.6 Q12 9.8 13.4 10.6" stroke="#141414" stroke-width="0.6" fill="none"/>'
      + '<path d="M5.5 22.5 Q5.5 13.6 12 13.6 Q18.5 13.6 18.5 22.5 Z" fill="#ECECEC" stroke="#141414" stroke-width="0.8"/>'
      + '<path d="M6.5 17 H17.5 M6 20 H18" stroke="#141414" stroke-width="1"/>'
      + '<path d="M6 1.5 V22.5 M10 1.5 V22.5 M14 1.5 V22.5 M18 1.5 V22.5" stroke="#2B2B2B" stroke-width="1.6"/></svg>';
    return d;
  }

  /** Logo dessiné d'une case, ou null si elle se contente d'un émoji. */
  function logoCase(c) {
    if (c.t === 'carte' && c.p === 'mairie') return logoCaisse();
    if (c.t === 'gare') return logoTrain();
    if (c.t === 'poste') return logoPrison();
    return null;
  }

  function orientation(i) {
    if (i % 10 === 0) return 'coin bas';
    if (i < 10) return 'bas';
    if (i < 20) return 'gauche';
    if (i < 30) return 'haut';
    return 'droite';
  }

  function rendrePlateau() {
    var grille = el('div', 'plateau');
    PLATEAU.forEach(function (c, i) {
      var place = placeCase(i);
      var d = el('div', 'case ' + orientation(i) + (CHOISIE === i ? ' choisie' : ''));
      d.style.gridRow = place[0];
      d.style.gridColumn = place[1];
      var p = ETAT.proprio[i];
      // Côtés gauche et droit : contenu tourné d'un quart de tour, comme sur un vrai plateau.
      var cote = i % 10 !== 0 && ((i > 10 && i < 20) || i > 30);
      var support = cote ? el('div', 'tourne') : d;
      if (cote) d.appendChild(support);
      if (c.t === 'rue') {
        var bande = el('div', 'bande');
        bande.style.background = GROUPES[c.g];
        var n = ETAT.maisons[i];
        if (n === 5) bande.appendChild(el('span', 'hotel'));
        else for (var m = 0; m < n; m++) bande.appendChild(el('span', 'maison'));
        support.appendChild(bande);
      }
      var texte = el('div', 'texte');
      var lettres = c.court.length;
      var nom = el('div', 'nom' + (lettres >= 10 ? ' tres-long' : lettres >= 8 ? ' long' : ''), c.court);
      var ico = logoCase(c);
      if (!ico && c.t !== 'rue') ico = el('div', 'ico', icone(c));
      // Coins : icône puis nom, centrés. Autres cases : nom en haut, icône au milieu, prix en bas.
      if (i % 10 === 0) { if (ico) texte.appendChild(ico); texte.appendChild(nom); }
      else { texte.appendChild(nom); if (ico) texte.appendChild(ico); }
      if (c.prix) texte.appendChild(el('div', 'prix', c.prix + ' €'));
      else if (c.t === 'taxe') texte.appendChild(el('div', 'prix taxe', c.montant + ' €'));
      if (p !== null && ETAT.hypo[i]) texte.appendChild(el('div', 'hypo', 'HYPO'));
      support.appendChild(texte);
      if (p !== null) {
        d.style.boxShadow = 'inset 0 0 0 2px ' + ETAT.joueurs[p].couleur;
        d.style.background = ETAT.hypo[i]
          ? 'repeating-linear-gradient(45deg, #E8F1E4 0 4px, #C9CFC6 4px 8px)'
          : 'color-mix(in srgb, ' + ETAT.joueurs[p].couleur + ' 25%, #E8F1E4)';
      }
      var pions = el('div', 'pions');
      ETAT.joueurs.forEach(function (j, k) {
        if (j.faillite || positionDe(k) !== i) return;
        var retenu = j.enPrison && !AFF;
        var pion = el('div', 'pion' + (k === ETAT.tour && ETAT.phase === 'jeu' ? ' actif' : '') + (retenu ? ' retenu' : ''),
          j.nom.charAt(0).toUpperCase());
        pion.style.backgroundColor = j.couleur;
        pion.title = j.nom + (retenu ? ' (retenu au poste)' : '');
        pions.appendChild(pion);
      });
      d.appendChild(pions);
      d.onclick = function () { CHOISIE = CHOISIE === i ? null : i; rendre(); };
      grille.appendChild(d);
    });
    grille.appendChild(rendreCentre());
    return grille;
  }

  /** Titre de propriété : prix, loyers, constructions, hypothèque. */
  function titrePropriete(i, compact) {
    var c = PLATEAU[i];
    var p = ETAT.proprio[i];
    var t = el('div', 'titre-prop');
    var h = el('div', 'entete');
    h.style.background = c.t === 'rue' ? GROUPES[c.g] : '#1B2A41';
    h.appendChild(el('small', '', c.t === 'rue' ? 'Titre de propriété' : (c.t === 'gare' ? 'Gare' : 'Service')));
    h.appendChild(document.createTextNode(c.nom));
    t.appendChild(h);
    var corps = el('div', 'corps');
    function l(g, d, classe) {
      var ligne = el('div', 'l' + (classe ? ' ' + classe : ''));
      ligne.appendChild(el('span', '', g));
      ligne.appendChild(el('span', '', d));
      corps.appendChild(ligne);
    }
    l('Prix', euros(c.prix), 'fort');
    var lignes = [];
    var actuel = -1;
    if (c.t === 'rue') {
      lignes = [['Loyer terrain nu', euros(c.loyer)], ['Quartier complet', euros(c.loyer * 2)]];
      for (var n = 1; n <= 5; n++) lignes.push([n === 5 ? 'Avec hôtel' : 'Avec ' + n + ' maison' + (n > 1 ? 's' : ''), euros(c.loyer * MULT_MAISONS[n])]);
      if (p !== null) {
        var entier = PLATEAU.every(function (x, k) { return x.t !== 'rue' || x.g !== c.g || ETAT.proprio[k] === p; });
        actuel = ETAT.maisons[i] ? ETAT.maisons[i] + 1 : (entier ? 1 : 0);
      }
    } else if (c.t === 'gare') {
      lignes = [['1 gare', euros(25)], ['2 gares', euros(50)], ['3 gares', euros(100)], ['4 gares', euros(200)]];
      if (p !== null) actuel = PLATEAU.filter(function (x, k) { return x.t === 'gare' && ETAT.proprio[k] === p; }).length - 1;
    } else {
      lignes = [['1 service', '4 × les dés'], ['2 services', '10 × les dés']];
      if (p !== null) actuel = PLATEAU.filter(function (x, k) { return x.t === 'service' && ETAT.proprio[k] === p; }).length - 1;
    }
    if (compact) lignes = lignes.slice(0, 1);
    lignes.forEach(function (x, k) { l(x[0], x[1], k === actuel && !ETAT.hypo[i] ? 'actuel' : ''); });
    if (!compact) {
      corps.appendChild(el('div', 'sep'));
      if (c.t === 'rue') l('Maison ou hôtel', euros(c.maison));
      l('Hypothèque', '+' + euros(c.prix / 2) + ' (levée ' + euros(c.leve) + ')');
    }
    t.appendChild(corps);
    return t;
  }

  function dernierMessage() {
    return ETAT.journal.length ? ETAT.journal[ETAT.journal.length - 1] : '';
  }

  function rendreCentre() {
    var c = el('div', 'centre');

    if (ANIM) {
      c.appendChild(el('div', 'titre', 'Pavés de Paris'));
      if (ANIM.des) c.appendChild(el('div', 'des' + (ANIM.roule ? ' roule' : ''), DES[ANIM.des[0] - 1] + ' ' + DES[ANIM.des[1] - 1]));
      c.appendChild(el('div', 'message', ANIM.message));
      return c;
    }

    if (ETAT.phase === 'fin') {
      c.appendChild(el('div', 'titre', 'Pavés de Paris'));
      c.appendChild(el('div', 'info', '🏆 ' + ETAT.classement[0].nom + ' gagne !'));
      if (ETAT.moi === ETAT.hote) c.appendChild(bouton('Nouvelle partie', 'btn-or', function () { agir('nouvelle'); }));
      return c;
    }

    var courant = ETAT.joueurs[ETAT.tour];
    var moi = ETAT.moi !== null ? ETAT.joueurs[ETAT.moi] : null;
    var remplace = moi && moi.robot;
    var monTour = ETAT.tour === ETAT.moi && !remplace;
    var boutons = el('div', 'boutons');
    var inactif = (Date.now() - ECART - ETAT.dernierCoup) / 1000;
    var peutForcer = moi && !moi.faillite && !remplace && !courant.robot && inactif > ETAT.delaiInactif;
    if (remplace) c.appendChild(el('div', 'info', '🤖 Un robot joue pour toi (décoche « Robot » pour reprendre).'));

    if (ETAT.etape === 'achat') {
      c.appendChild(titrePropriete(courant.position, false));
      if (monTour) {
        var cs = PLATEAU[moi.position];
        boutons.appendChild(bouton('Acheter ' + euros(cs.prix), 'btn-or', function () { agir('acheter'); }));
        boutons.appendChild(bouton('Ne pas acheter', 'btn-gris', function () { agir('passer'); }));
      } else {
        c.appendChild(el('div', 'info', courant.nom + ' hésite…'));
        if (peutForcer) boutons.appendChild(bouton('Jouer à sa place', 'btn-gris', function () { agir('forcer'); }));
      }
      c.appendChild(boutons);
      return c;
    }

    if (ETAT.etape === 'carte' && ETAT.derniereCarte) {
      var carte = el('div', 'carte-tiree ' + ETAT.derniereCarte.paquet);
      var entete = el('b');
      if (ETAT.derniereCarte.paquet === 'mairie') {
        entete.appendChild(logoCaisse('ico-titre'));
        entete.appendChild(document.createTextNode(' Caisse commune'));
      } else {
        entete.appendChild(document.createTextNode('❓ Surprise'));
      }
      if (!monTour) entete.appendChild(document.createTextNode(' — ' + courant.nom));
      carte.appendChild(entete);
      carte.appendChild(document.createTextNode(ETAT.derniereCarte.texte));
      c.appendChild(carte);
      if (monTour) boutons.appendChild(bouton('OK', 'btn-or', function () { agir('okCarte'); }));
      else {
        c.appendChild(el('div', 'info', courant.nom + ' lit sa carte…'));
        if (peutForcer) boutons.appendChild(bouton('Jouer à sa place', 'btn-gris', function () { agir('forcer'); }));
      }
      c.appendChild(boutons);
      return c;
    }

    if (ETAT.etape === 'enchere' && ETAT.enchere) {
      var e = ETAT.enchere;
      c.appendChild(titrePropriete(e.case, true));
      c.appendChild(el('div', 'info', '🔨 ' + (e.meneur === null
        ? 'Aucune offre pour l\u2019instant.'
        : 'Meilleure offre : ' + euros(e.prix) + ' (' + ETAT.joueurs[e.meneur].nom + ')')));
      var restants = ETAT.joueurs.filter(function (j, k) { return !j.faillite && e.passe.indexOf(k) === -1 && k !== e.meneur; })
        .map(function (j) { return j.nom; });
      if (restants.length) c.appendChild(el('div', 'info', 'En attente : ' + restants.join(', ')));
      var peutMiser = moi && !moi.faillite && !remplace && e.passe.indexOf(ETAT.moi) === -1;
      if (peutMiser && e.meneur === ETAT.moi) {
        c.appendChild(el('div', 'info', 'Tu mènes l\u2019enchère.'));
      } else if (peutMiser) {
        [10, 50, 100].forEach(function (pas) {
          var mise = e.prix + pas;
          var b = bouton(euros(mise), 'btn-or', function () { agir('miser', mise); });
          b.disabled = mise > moi.argent;
          boutons.appendChild(b);
        });
        boutons.appendChild(bouton('Je passe', 'btn-gris', function () { agir('passerEnchere'); }));
      }
      if ((Date.now() - ECART - e.depuis) / 1000 > ETAT.delaiEnchere) {
        boutons.appendChild(bouton('Clore l\u2019enchère', 'btn-gris', function () { agir('clore'); }));
      }
      c.appendChild(boutons);
      return c;
    }

    if (ETAT.etape === 'dette') {
      c.appendChild(el('div', 'titre', '💸 Dette'));
      var dette = ETAT.joueurs.filter(function (j) { return !j.faillite && j.argent < 0; });
      dette.forEach(function (j) {
        c.appendChild(el('div', 'info', j.nom + ' doit trouver ' + euros(-j.argent) + '.'));
      });
      if (moi && moi.argent < 0 && !remplace) {
        var possible = moi.argent + ETAT.ressources[ETAT.moi] >= 0;
        c.appendChild(el('div', 'message', possible
          ? 'Choisis ci-dessous les maisons à revendre ou les biens à hypothéquer.'
          : 'Même en vendant tout, tu ne peux pas payer : déclare faillite.'));
        boutons.appendChild(bouton('Déclarer faillite', 'btn-rouge', function () {
          if (confirm('Déclarer faillite ? Tu quittes la partie et tes biens retournent à la banque.')) agir('faillite');
        }));
      } else {
        c.appendChild(el('div', 'info', 'La partie reprend dès que la dette est réglée.'));
        if (peutForcer) boutons.appendChild(bouton('Régler à sa place', 'btn-gris', function () { agir('forcer'); }));
      }
      c.appendChild(boutons);
      return c;
    }

    c.appendChild(el('div', 'titre', 'Pavés de Paris'));
    c.appendChild(el('div', 'info', 'Salle ' + ETAT.code + ' · tour ' + ETAT.tourNo + (ETAT.toursMax ? '/' + ETAT.toursMax : '')));
    if (ETAT.des) c.appendChild(el('div', 'des', DES[ETAT.des[0] - 1] + ' ' + DES[ETAT.des[1] - 1]));
    c.appendChild(el('div', 'message', dernierMessage()));
    if (monTour) {
      if (ETAT.etape === 'lancer') {
        c.appendChild(el('div', 'info', 'À toi de jouer !'));
        boutons.appendChild(bouton('🎲 Lancer les dés', 'btn-or', function () { agir('lancer'); }));
      } else if (ETAT.etape === 'prison') {
        c.appendChild(el('div', 'info', 'Tu es au poste (essai ' + (moi.essais + 1) + '/3).'));
        boutons.appendChild(bouton('🎲 Tenter un double', 'btn-or', function () { agir('lancer'); }));
        var caution = bouton('Payer ' + CAUTION + ' €', 'btn-gris', function () { agir('caution'); });
        caution.disabled = moi.argent < CAUTION;
        boutons.appendChild(caution);
        if (moi.cartesSortie) boutons.appendChild(bouton('Libéré sur parole', 'btn-gris', function () { agir('carte'); }));
      }
    } else {
      c.appendChild(el('div', 'info', 'Au tour de ' + (courant.robot ? '🤖 ' : '') + courant.nom + (courant.robot ? ' (robot)' : '')));
      if (peutForcer) boutons.appendChild(bouton('Jouer à sa place', 'btn-gris', function () { agir('forcer'); }));
    }
    c.appendChild(boutons);
    return c;
  }

  /** Pendant une dette : la liste de ses biens, avec revente et hypothèque. */
  function rendreDette() {
    var b = el('div', 'bloc dette');
    var moi = ETAT.joueurs[ETAT.moi];
    b.appendChild(el('h2', '', 'Trouver ' + euros(-moi.argent)));
    var mien = ETAT.proprio.map(function (p, i) { return p === ETAT.moi ? i : -1; }).filter(function (i) { return i >= 0; });
    if (!mien.length) b.appendChild(el('div', 'sous', 'Tu n\u2019as plus aucun bien.'));
    mien.forEach(function (i) {
      var c = PLATEAU[i];
      var ligne = el('div', 'detail');
      ligne.style.marginTop = '8px';
      var nom = el('b', '', c.nom + (ETAT.hypo[i] ? ' (hypothéqué)' : '')
        + (ETAT.maisons[i] ? ' — ' + (ETAT.maisons[i] === 5 ? 'hôtel' : ETAT.maisons[i] + ' maison' + (ETAT.maisons[i] > 1 ? 's' : '')) : ''));
      if (c.t === 'rue') nom.style.borderLeft = '6px solid ' + GROUPES[c.g];
      nom.style.paddingLeft = '6px';
      ligne.appendChild(nom);
      var g = rendreGestion(i);
      if (g.childNodes.length) ligne.appendChild(g);
      b.appendChild(ligne);
    });
    return b;
  }

  function rendreDetail() {
    var c = PLATEAU[CHOISIE];
    var b = el('div', 'bloc detail');
    if (!c.prix && c.t !== 'taxe') {
      var h2 = el('h2', '', (icone(c) ? icone(c) + ' ' : '') + c.nom);
      var logo = logoCase(c);
      if (logo) { logo.className = 'ico-titre'; h2.insertBefore(document.createTextNode(' '), h2.firstChild); h2.insertBefore(logo, h2.firstChild); }
      b.appendChild(h2);
    }
    function ligne(g, d) {
      var l = el('div', 'ligne');
      l.appendChild(el('span', '', g));
      l.appendChild(el('b', '', d));
      b.appendChild(l);
    }
    if (c.prix) {
      var tp = titrePropriete(CHOISIE, false);
      tp.style.width = '100%';
      tp.style.marginBottom = '8px';
      b.appendChild(tp);
      var p = ETAT.proprio[CHOISIE];
      ligne('Propriétaire', p === null ? 'la banque (libre)' : ETAT.joueurs[p].nom);
      if (p !== null) ligne('Loyer actuel', loyerAffiche(CHOISIE));
      if (p !== null && p === ETAT.moi && ETAT.phase === 'jeu' && !ETAT.joueurs[p].faillite) b.appendChild(rendreGestion(CHOISIE));
    } else if (c.t === 'taxe') {
      var t = el('div', 'titre-prop');
      t.style.width = '100%';
      var h = el('div', 'entete');
      h.style.background = '#B00020';
      h.appendChild(el('small', '', c.court === 'Amende' ? 'Amende' : 'Impôt'));
      h.appendChild(document.createTextNode(c.nom));
      t.appendChild(h);
      var corps = el('div', 'corps');
      var l = el('div', 'l fort');
      l.appendChild(el('span', '', 'À payer à la banque'));
      l.appendChild(el('span', '', euros(c.montant)));
      corps.appendChild(l);
      corps.appendChild(el('div', 'sep'));
      var n = el('div', 'l');
      n.appendChild(el('span', '', 'Quand on s\u2019arrête sur la case'));
      corps.appendChild(n);
      t.appendChild(corps);
      b.appendChild(t);
    } else {
      b.appendChild(el('div', 'sous', {
        depart: 'Chaque passage rapporte ' + SALAIRE + ' €.',
        poste: 'Simple visite, sauf si on t’y conduit : il faut alors un double, ' + CAUTION + ' € ou une carte pour sortir (3 essais max).',
        pause: 'Rien ne se passe, profite du soleil.',
        police: 'Direction le poste de police, sans passer par le Départ.',
        carte: 'Tire une carte ' + c.nom + '.'
      }[c.t] || ''));
    }
    return b;
  }

  function rendreGestion(i) {
    var c = PLATEAU[i];
    var g = el('div', 'gestion');
    var moi = ETAT.joueurs[ETAT.moi];
    var rues = PLATEAU.map(function (x, k) { return x.t === 'rue' && x.g === c.g ? k : -1; }).filter(function (k) { return k >= 0; });
    var niveaux = rues.map(function (k) { return ETAT.maisons[k]; });
    var bati = niveaux.some(function (n) { return n > 0; });
    if (c.t === 'rue' && !ETAT.hypo[i]) {
      var complet = rues.every(function (k) { return ETAT.proprio[k] === ETAT.moi && !ETAT.hypo[k]; });
      if (complet && ETAT.maisons[i] < 5) {
        var cb = bouton((ETAT.maisons[i] === 4 ? 'Construire un hôtel' : 'Construire une maison') + ' (' + euros(c.maison) + ')', 'btn-or',
          function () { agir('construire', i); });
        cb.disabled = moi.argent < c.maison || ETAT.maisons[i] > Math.min.apply(null, niveaux) || ETAT.etape === 'enchere';
        g.appendChild(cb);
      }
      if (ETAT.maisons[i]) {
        var vb = bouton('Revendre ' + (ETAT.maisons[i] === 5 ? 'l\u2019hôtel' : 'une maison') + ' (+' + euros(c.maison / 2) + ')', '',
          function () { agir('demolir', i); });
        vb.disabled = ETAT.maisons[i] < Math.max.apply(null, niveaux) || ETAT.etape === 'enchere';
        g.appendChild(vb);
      }
    }
    if (ETAT.hypo[i]) {
      var lb = bouton('Lever l\u2019hypothèque (' + euros(c.leve) + ')', 'btn-or', function () { agir('lever', i); });
      lb.disabled = moi.argent < c.leve || ETAT.etape === 'enchere';
      g.appendChild(lb);
    } else if (!bati) {
      var hb = bouton('Hypothéquer (+' + euros(c.prix / 2) + ')', '', function () { agir('hypothequer', i); });
      hb.disabled = ETAT.etape === 'enchere';
      g.appendChild(hb);
    }
    return g;
  }

  /* --------------------------------------------------------------- échanges */

  function biensDe(k) {
    return ETAT.proprio.map(function (p, i) { return p === k ? i : -1; }).filter(function (i) { return i >= 0; });
  }
  function quartierBati(i) {
    var c = PLATEAU[i];
    return c.t === 'rue' && PLATEAU.some(function (x, k) { return x.t === 'rue' && x.g === c.g && ETAT.maisons[k] > 0; });
  }
  function pastilleBien(i) {
    var c = PLATEAU[i];
    var m = el('span', 'titre-mini');
    m.style.background = c.t === 'rue' ? GROUPES[c.g] : (c.t === 'gare' ? '#222' : '#999');
    m.style.display = 'inline-block';
    m.style.verticalAlign = 'middle';
    m.style.marginRight = '6px';
    return m;
  }

  function colonneEchange(titre, k, cle, cleArgent) {
    var col = el('div', 'colonne');
    col.appendChild(el('h3', '', titre));
    var biens = biensDe(k);
    if (!biens.length) col.appendChild(el('div', 'sous', 'Aucun bien.'));
    biens.forEach(function (i) {
      var lab = el('label', 'bien');
      var coche = el('input');
      coche.type = 'checkbox';
      coche.checked = BROUILLON[cle].indexOf(i) !== -1;
      coche.disabled = quartierBati(i);
      coche.onchange = function () {
        var l = BROUILLON[cle];
        if (coche.checked) l.push(i); else l.splice(l.indexOf(i), 1);
      };
      lab.appendChild(coche);
      lab.appendChild(pastilleBien(i));
      lab.appendChild(document.createTextNode(PLATEAU[i].nom + (ETAT.hypo[i] ? ' (hypo)' : '')
        + (quartierBati(i) ? ' — maisons à revendre' : '')));
      col.appendChild(lab);
    });
    var argent = el('input');
    argent.type = 'number';
    argent.min = '0';
    argent.step = '10';
    argent.inputMode = 'numeric';
    argent.placeholder = '0 €';
    argent.value = BROUILLON[cleArgent];
    argent.oninput = function () { BROUILLON[cleArgent] = argent.value; };
    argent.onfocus = function () { EDITION = true; };
    argent.onblur = function () { EDITION = false; if (RENDU_DIFFERE) rendre(); };
    var l = el('label', '', 'Argent (max ' + euros(Math.max(0, ETAT.joueurs[k].argent)) + ')');
    col.appendChild(l);
    col.appendChild(argent);
    return col;
  }

  function rendreEditeur() {
    var b = el('div', 'bloc echange');
    b.appendChild(el('h2', '', '🤝 Proposer un échange'));
    var autres = ETAT.joueurs.map(function (j, k) { return k; })
      .filter(function (k) { return k !== ETAT.moi && !ETAT.joueurs[k].faillite; });
    if (autres.indexOf(BROUILLON.a) === -1) { BROUILLON.a = autres[0]; BROUILLON.recoit = []; }
    var choix = el('select');
    autres.forEach(function (k) {
      var o = el('option', '', (ETAT.joueurs[k].robot ? '🤖 ' : '') + ETAT.joueurs[k].nom);
      o.value = k;
      if (k === BROUILLON.a) o.selected = true;
      choix.appendChild(o);
    });
    choix.onchange = function () { BROUILLON.a = parseInt(choix.value, 10); BROUILLON.recoit = []; BROUILLON.argentRecu = ''; rendre(); };
    b.appendChild(el('label', '', 'Avec qui ?'));
    b.appendChild(choix);
    var grille = el('div', 'colonnes');
    grille.appendChild(colonneEchange('Je donne', ETAT.moi, 'donne', 'argentDonne'));
    grille.appendChild(colonneEchange('Je reçois de ' + ETAT.joueurs[BROUILLON.a].nom, BROUILLON.a, 'recoit', 'argentRecu'));
    b.appendChild(grille);
    b.appendChild(el('div', 'sous', 'Les biens d\u2019un quartier bâti ne s\u2019échangent pas : revends d\u2019abord ses maisons. '
      + 'Un bien hypothéqué reste hypothéqué.'));
    b.appendChild(bouton('Envoyer la proposition', 'principal', function () {
      agir('proposerEchange', {
        a: BROUILLON.a, donne: BROUILLON.donne, recoit: BROUILLON.recoit,
        argentDonne: BROUILLON.argentDonne, argentRecu: BROUILLON.argentRecu
      }).then(function () { if (ETAT.echange) { BROUILLON = null; rendre(); } });
    }));
    b.appendChild(bouton('Annuler', 'discret', function () { BROUILLON = null; rendre(); }));
    return b;
  }

  function rendreEchangeEnCours() {
    var e = ETAT.echange;
    var J = ETAT.joueurs;
    var b = el('div', 'bloc echange en-cours');
    b.appendChild(el('h2', '', '🤝 Échange proposé'));
    function lot(titre, cases, argent) {
      b.appendChild(el('h3', '', titre));
      if (!cases.length && !argent) b.appendChild(el('div', 'sous', 'rien'));
      cases.forEach(function (i) {
        var l = el('div', 'bien');
        l.appendChild(pastilleBien(i));
        l.appendChild(document.createTextNode(PLATEAU[i].nom + (ETAT.hypo[i] ? ' (hypo)' : '') + ' — ' + euros(PLATEAU[i].prix)));
        b.appendChild(l);
      });
      if (argent) b.appendChild(el('div', 'bien', '💶 ' + euros(argent)));
    }
    lot(J[e.de].nom + ' donne :', e.donne, e.argentDonne);
    lot(J[e.a].nom + ' donne :', e.recoit, e.argentRecu);
    var moi = ETAT.moi !== null ? J[ETAT.moi] : null;
    if (ETAT.moi === e.a && moi && !moi.robot) {
      b.appendChild(bouton('Accepter', 'principal', function () { agir('accepterEchange'); }));
      b.appendChild(bouton('Refuser', 'second', function () { agir('refuserEchange'); }));
    } else {
      b.appendChild(el('div', 'sous', 'En attente de la réponse de ' + (J[e.a].robot ? '🤖 ' : '') + J[e.a].nom + '…'));
      if (ETAT.moi === e.de) b.appendChild(bouton('Retirer ma proposition', 'discret', function () { agir('annulerEchange'); }));
    }
    return b;
  }

  function rendreJoueurs() {
    var z = el('div', 'joueurs');
    ETAT.joueurs.forEach(function (j, i) {
      var f = el('div', 'fiche' + (i === ETAT.tour && ETAT.phase === 'jeu' ? ' son-tour' : '') + (j.faillite ? ' ko' : ''));
      f.style.borderLeftColor = j.couleur;
      var h = el('div', 'haut');
      h.appendChild(el('span', '', (j.robot ? '🤖 ' : '') + j.nom + (i === ETAT.moi ? ' (toi)' : '')));
      h.appendChild(el('span', '', j.faillite ? 'faillite' : euros(j.argent)));
      f.appendChild(h);
      if (!j.faillite) {
        var info = (j.enPrison ? 'Retenu au poste 🔒' : PLATEAU[j.position].court)
          + (j.cartesSortie ? ' · 🎟️ ' + j.cartesSortie : '') + ' · fortune ' + euros(j.fortune);
        f.appendChild(el('div', 'bas', info));
      }
      if (ETAT.phase === 'jeu' && !j.faillite) {
        var lab = el('label', 'case-robot');
        var coche = el('input');
        coche.type = 'checkbox';
        coche.checked = !!j.robot;
        coche.onchange = function () { agir('robot', i); };
        lab.appendChild(coche);
        lab.appendChild(document.createTextNode(' 🤖 Robot' + (j.robot ? ' (joue à sa place)' : '')));
        f.appendChild(lab);
      }
      var t = el('div', 'titres');
      ETAT.proprio.forEach(function (p, k) {
        if (p !== i) return;
        var c = PLATEAU[k];
        var m = el('div', 'titre-mini' + (ETAT.hypo[k] ? ' hypo' : ''));
        m.style.background = c.t === 'rue' ? GROUPES[c.g] : (c.t === 'gare' ? '#222' : '#999');
        m.title = c.nom;
        m.onclick = function () { CHOISIE = k; rendre(); };
        t.appendChild(m);
      });
      f.appendChild(t);
      z.appendChild(f);
    });
    return z;
  }

  function rendreClassement() {
    var b = el('div', 'bloc');
    b.appendChild(el('h2', '', 'Classement final'));
    var t = el('table', 'classement');
    ETAT.classement.forEach(function (r, i) {
      var tr = el('tr');
      tr.appendChild(el('td', '', (i + 1) + '.'));
      tr.appendChild(el('td', '', r.nom));
      tr.appendChild(el('td', '', r.faillite ? 'faillite' : euros(r.fortune)));
      t.appendChild(tr);
    });
    b.appendChild(t);
    b.appendChild(el('div', 'sous', 'Fortune = argent + biens + constructions (un bien hypothéqué compte pour moitié).'));
    return b;
  }

  function rendreJeu() {
    var cadre = el('div', 'cadre-jeu');
    var gauche = el('div', 'col-plateau');
    var droite = el('div', 'col-infos');
    cadre.appendChild(gauche);
    cadre.appendChild(droite);
    app.appendChild(cadre);
    gauche.appendChild(rendrePlateau());
    gauche.appendChild(zoneStatut());
    if (!ANIM && ETAT.phase === 'jeu' && ETAT.etape === 'dette' && ETAT.moi !== null && ETAT.joueurs[ETAT.moi].argent < 0
      && !ETAT.joueurs[ETAT.moi].robot) {
      droite.appendChild(rendreDette());
    }
    if (ETAT.phase === 'fin') droite.appendChild(rendreClassement());
    if (ETAT.phase === 'jeu') {
      var moiJ = ETAT.moi !== null ? ETAT.joueurs[ETAT.moi] : null;
      var peutEchanger = moiJ && !moiJ.faillite && !moiJ.robot && ETAT.etape !== 'enchere'
        && ETAT.joueurs.some(function (j, k) { return k !== ETAT.moi && !j.faillite; });
      if (ETAT.echange) { BROUILLON = null; droite.appendChild(rendreEchangeEnCours()); }
      else if (BROUILLON && peutEchanger) droite.appendChild(rendreEditeur());
      else if (peutEchanger) {
        droite.appendChild(bouton('🤝 Proposer un échange', 'second', function () {
          BROUILLON = { a: null, donne: [], recoit: [], argentDonne: '', argentRecu: '' };
          rendre();
        }));
      }
    }
    if (CHOISIE !== null) droite.appendChild(rendreDetail());
    droite.appendChild(rendreJoueurs());
    var jb = el('div', 'bloc');
    jb.style.marginTop = '10px';
    jb.appendChild(el('h2', '', 'Derniers coups'));
    var ul = el('ul', 'journal');
    ETAT.journal.forEach(function (m) { ul.appendChild(el('li', '', m)); });
    jb.appendChild(ul);
    droite.appendChild(jb);
    var moi = ETAT.joueurs[ETAT.moi];
    if (ETAT.phase === 'jeu' && !moi.faillite) {
      droite.appendChild(bouton('Abandonner la partie', 'discret', function () {
        if (confirm('Abandonner ? Tes biens retournent à la banque et tu ne pourras plus jouer cette partie.')) agir('quitter');
      }));
    }
    droite.appendChild(bouton('Retour à l’accueil', 'discret', quitterLocal));
  }

  function rendre() {
    // Ne pas effacer un montant en cours de saisie dans l'éditeur d'échange.
    if (EDITION) { RENDU_DIFFERE = true; return; }
    RENDU_DIFFERE = false;
    app.innerHTML = '';
    var wrap = document.querySelector('.wrap');
    if (wrap) wrap.classList.toggle('large', !!ETAT && ETAT.phase !== 'attente');
    if (!ETAT) rendreAccueil();
    else if (ETAT.phase === 'attente') rendreAttente();
    else rendreJeu();
  }

  var codeUrl = new URLSearchParams(location.search).get('code');
  var codeMemo = localStorage.getItem('paves:code');
  rendre();
  if (codeMemo && (!codeUrl || codeUrl.toUpperCase() === codeMemo)) {
    CODE = codeMemo;
    rafraichir(true);
  }
}

/* Page « Noms des rues » (sérialisée par toString, comme le client du jeu). */
function clientNoms() {
  var app = document.getElementById('app');
  function el(balise, classe, texte) {
    var n = document.createElement(balise);
    if (classe) n.className = classe;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }
  var statut = el('div', 'statut');
  var champs = {};

  function envoyer(corps) {
    statut.textContent = 'Enregistrement…';
    statut.className = 'statut';
    return fetch('/api/noms', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(corps) })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.erreur || 'Erreur'); return d; }); })
      .then(function (d) {
        d.noms.forEach(function (n, i) {
          if (!champs[i]) return;
          champs[i].nom.value = n.nom;
          champs[i].court.value = n.court === n.nom || n.court === ORIGINE[i].court ? '' : n.court;
        });
        statut.textContent = '✔ Noms enregistrés : ils s\u2019affichent dans toutes les parties.';
      })
      .catch(function (err) { statut.textContent = err.message; statut.className = 'statut erreur'; });
  }

  app.appendChild(el('h1', '', 'Noms des rues'));
  app.appendChild(el('div', 'sous', 'Nom complet (titres de propriété, journal) et nom court affiché sur le plateau. '
    + 'Laisse le nom court vide pour reprendre le nom complet.'));
  var bloc = el('div', 'bloc');
  PLATEAU.forEach(function (c, i) {
    if (!c.prix) return;
    var ligne = el('div', 'ligne-nom');
    var pastille = el('span', 'pastille-nom');
    pastille.style.background = c.t === 'rue' ? GROUPES[c.g] : (c.t === 'gare' ? '#141414' : '#999');
    ligne.appendChild(pastille);
    var nom = el('input');
    nom.maxLength = NOM_MAX;
    nom.value = c.nom;
    nom.placeholder = ORIGINE[i].nom;
    var court = el('input');
    court.maxLength = COURT_MAX;
    // Vide tant que le nom court n'a pas été personnalisé : on reprend alors le nom saisi.
    court.value = c.court === c.nom || c.court === ORIGINE[i].court ? '' : c.court;
    court.placeholder = 'court : ' + ORIGINE[i].court;
    ligne.appendChild(nom);
    ligne.appendChild(court);
    champs[i] = { nom: nom, court: court };
    bloc.appendChild(ligne);
  });
  app.appendChild(bloc);
  var enregistrer = el('button', 'principal', 'Enregistrer les noms');
  enregistrer.onclick = function () {
    var noms = {};
    Object.keys(champs).forEach(function (i) { noms[i] = { nom: champs[i].nom.value, court: champs[i].court.value }; });
    envoyer({ noms: noms });
  };
  app.appendChild(enregistrer);
  app.appendChild(statut);
  var retablir = el('button', 'discret', 'Rétablir les noms d\u2019origine');
  retablir.onclick = function () {
    if (confirm('Remettre tous les noms d\u2019origine ?')) envoyer({ retablir: true });
  };
  app.appendChild(retablir);
  var retour = el('a', 'discret', '← Retour au jeu');
  retour.href = '/';
  retour.style.display = 'block';
  retour.style.textAlign = 'center';
  retour.style.marginTop = '10px';
  app.appendChild(retour);
}

function pageNomsHtml() {
  const donnees = 'var __name = function (f) { return f; };'
    + 'var PLATEAU = ' + toScriptJson(PLATEAU) + ';'
    + 'var ORIGINE = ' + toScriptJson(NOMS_ORIGINE) + ';'
    + 'var GROUPES = ' + toScriptJson(GROUPES) + ';'
    + 'var NOM_MAX = ' + NOM_MAX + ', COURT_MAX = ' + COURT_MAX + ';';
  const css = CSS + `
  .ligne-nom{display:grid; grid-template-columns:14px 1fr 34%; gap:6px; align-items:center; margin:6px 0;}
  .ligne-nom input{text-align:left; padding:8px; font-size:0.9rem;}
  .pastille-nom{width:14px; height:28px; border-radius:3px;}`;
  return '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + '<title>Noms des rues</title><style>' + css + '</style></head>'
    + '<body><div class="wrap"><div id="app"></div></div>'
    + '<script>' + donnees + '(' + clientNoms.toString() + ')();</script>'
    + '</body></html>';
}

function pageHtml(joueursConnus) {
  // Wrangler (keep_names) peut glisser des appels __name() dans le code sérialisé.
  const donnees = 'var __name = function (f) { return f; };'
    + 'var PLATEAU = ' + toScriptJson(PLATEAU) + ';'
    + 'var GROUPES = ' + toScriptJson(GROUPES) + ';'
    + 'var JOUEURS = ' + toScriptJson(joueursConnus) + ';'
    + 'var TOURS = ' + toScriptJson(TOURS_CHOIX) + ';'
    + 'var TOURS_DEFAUT = ' + TOURS_DEFAUT + ';'
    + 'var MIN_JOUEURS = ' + MIN_JOUEURS + ';'
    + 'var MAX_JOUEURS = ' + MAX_JOUEURS + ';'
    + 'var SALAIRE = ' + SALAIRE + ';'
    + 'var CAUTION = ' + CAUTION + ';'
    + 'var MULT_MAISONS = ' + toScriptJson(MULT_MAISONS) + ';'
    + "var DES = ['⚀','⚁','⚂','⚃','⚄','⚅'];";
  return '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + '<title>Pavés de Paris</title><style>' + CSS + '</style></head>'
    + '<body><div class="wrap"><div id="app"></div></div>'
    + '<script>' + donnees + '(' + client.toString() + ')();</script>'
    + '</body></html>';
}

/* ---------------------------------------------------------------- routes */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const chemin = url.pathname.replace(/\/+$/, '') || '/';

    if (chemin === '/favicon.svg') {
      return new Response(FAVICON, { headers: { 'content-type': 'image/svg+xml', 'cache-control': 'public, max-age=86400' } });
    }
    if (chemin === '/favicon.ico') return new Response(null, { status: 204 });
    if (!bdd(env)) return erreur('Stockage non configuré (binding D1 « DB »).', 500);

    const api = chemin.startsWith('/api/');
    try {
      await preparerTables(env);
      const nomsEnregistres = await lireNoms(env);
      appliquerNoms(nomsEnregistres);

      if (chemin === '/api/noms' && request.method === 'POST') {
        const corps = await corpsJson(request);
        const noms = corps.retablir ? {} : nomsValides(corps.noms);
        await ecrireNoms(env, noms);
        appliquerNoms(noms);
        return json({ ok: true, noms: PLATEAU.map((c) => ({ nom: c.nom, court: c.court })) });
      }
      if (chemin === '/noms') {
        return new Response(pageNomsHtml(), {
          headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
        });
      }

      if (chemin === '/api/etat') {
        const code = normaliserCode(url.searchParams.get('code'));
        const jeton = jetonValide(url.searchParams.get('jeton'));
        if (!code || !jeton) return erreur('Requête incomplète.');
        let courant = await lireSalle(env, code);
        if (!courant) return erreur('Salle introuvable ou expirée.', 404);
        courant = await faireJouerRobot(env, code, courant);
        const connue = parseInt(url.searchParams.get('v') || '0', 10);
        if (connue === courant.version) return json({ inchange: true, version: courant.version });
        return json(vuePour(courant.salle, courant.version, jeton));
      }

      if (api && request.method !== 'POST') return erreur('Méthode non autorisée.', 405);

      if (api) {
        const corps = await corpsJson(request);
        const jeton = jetonValide(corps.jeton);
        if (!jeton) return erreur('Session invalide, recharge la page.');

        if (chemin === '/api/salle') {
          const nom = nomValide(corps.nom);
          if (!nom) return erreur('Choisis ton nom.');
          let toursMax = parseInt(corps.toursMax, 10);
          if (!TOURS_CHOIX.includes(toursMax)) toursMax = TOURS_DEFAUT;
          const code = await creerSalle(env, toursMax);
          await ajouterJoueur(env, nom);
          const apres = await modifierSalle(env, code, (salle) => {
            salle.joueurs.push(nouveauJoueur(jeton, nom, 0));
            salle.hote = jeton;
          });
          return json(vuePour(apres.salle, apres.version, jeton));
        }

        if (chemin === '/api/rejoindre') {
          const code = normaliserCode(corps.code);
          const nom = nomValide(corps.nom);
          if (!code) return erreur('Code de salle invalide.');
          if (!nom) return erreur('Choisis ton nom.');
          await ajouterJoueur(env, nom);
          const apres = await modifierSalle(env, code, (salle) => {
            const existant = salle.joueurs.find((j) => j.jeton === jeton);
            if (existant) return;
            if (salle.phase !== 'attente') refuser('La partie a déjà commencé dans cette salle.');
            if (salle.joueurs.length >= MAX_JOUEURS) refuser('La salle est complète (' + MAX_JOUEURS + ' joueurs).');
            if (salle.joueurs.some((j) => j.nom.toLowerCase() === nom.toLowerCase())) refuser('Ce nom est déjà pris dans la salle.');
            salle.joueurs.push(nouveauJoueur(jeton, nom, couleurLibre(salle)));
            if (!salle.hote) salle.hote = jeton;
            noter(salle, nom + ' rejoint la salle.');
          });
          return json(vuePour(apres.salle, apres.version, jeton));
        }

        if (chemin === '/api/action') {
          const code = normaliserCode(corps.code);
          if (!code) return erreur('Code de salle invalide.');
          const apres = await modifierSalle(env, code, (salle) => {
            appliquerAction(salle, jeton, String(corps.action || ''), corps.valeur);
            salle.horodatage = Date.now();
          });
          return json(vuePour(apres.salle, apres.version, jeton));
        }
        return erreur('Route inconnue.', 404);
      }

      if (chemin !== '/') {
        return new Response('Page introuvable', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
      }
      return new Response(pageHtml(await lireJoueurs(env)), {
        headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
      });
    } catch (err) {
      if (err instanceof ErreurJeu) return erreur(err.message, 409);
      console.log('erreur inattendue: ' + (err && err.stack ? err.stack : err));
      return erreur('Erreur interne, réessaie.', 500);
    }
  },
};

