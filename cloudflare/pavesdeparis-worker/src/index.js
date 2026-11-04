/**
 * Worker "pavesdeparis" — « Pavés de Paris », un jeu de plateau immobilier
 * original jouable à plusieurs en ligne, sur le même principe que skyjoenligne.
 *
 * Chacun ouvre la page sur son téléphone, crée ou rejoint une salle avec un
 * code court et joue son tour : dés, déplacement, achat de rues, loyers,
 * cartes Surprise et Mairie, poste de police, faillite et fin de partie sont
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
  { t: 'carte', p: 'mairie', nom: 'Mairie', court: 'Mairie' },
  { t: 'rue', g: 0, nom: 'Rue de Ménilmontant', court: 'Ménilmontant', prix: 70 },
  { t: 'taxe', nom: 'Taxe foncière', court: 'Taxe 200 €', montant: 200 },
  { t: 'gare', nom: "Gare de l'Est", court: "G. de l'Est", prix: 200 },
  { t: 'rue', g: 1, nom: 'Rue Oberkampf', court: 'Oberkampf', prix: 100 },
  { t: 'carte', p: 'surprise', nom: 'Surprise', court: 'Surprise' },
  { t: 'rue', g: 1, nom: 'Rue des Martyrs', court: 'Martyrs', prix: 110 },
  { t: 'rue', g: 1, nom: 'Rue de la Roquette', court: 'Roquette', prix: 120 },
  { t: 'poste', nom: 'Poste de police (simple visite)', court: 'Poste' },
  { t: 'rue', g: 2, nom: 'Rue Montorgueil', court: 'Montorgueil', prix: 140 },
  { t: 'service', nom: 'Compagnie du gaz', court: 'Gaz', prix: 150 },
  { t: 'rue', g: 2, nom: 'Rue Cler', court: 'Cler', prix: 150 },
  { t: 'rue', g: 2, nom: 'Rue du Bac', court: 'Bac', prix: 160 },
  { t: 'gare', nom: "Gare d'Austerlitz", court: 'G. Austerlitz', prix: 200 },
  { t: 'rue', g: 3, nom: 'Rue des Rosiers', court: 'Rosiers', prix: 180 },
  { t: 'carte', p: 'mairie', nom: 'Mairie', court: 'Mairie' },
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
  { t: 'carte', p: 'mairie', nom: 'Mairie', court: 'Mairie' },
  { t: 'rue', g: 6, nom: 'Place Dauphine', court: 'Dauphine', prix: 320 },
  { t: 'gare', nom: 'Gare des Invalides', court: 'G. Invalides', prix: 200 },
  { t: 'carte', p: 'surprise', nom: 'Surprise', court: 'Surprise' },
  { t: 'rue', g: 7, nom: 'Avenue Montaigne', court: 'Montaigne', prix: 360 },
  { t: 'taxe', nom: 'Amende de stationnement', court: 'Amende 100 €', montant: 100 },
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
  salle.journal.push(message);
  if (salle.journal.length > JOURNAL_MAX) salle.journal = salle.journal.slice(-JOURNAL_MAX);
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
  for (const j of salle.joueurs) Object.assign(j, nouveauJoueur(j.jeton, j.nom, j.couleur));
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

function faillite(salle, idx, creancier) {
  const j = salle.joueurs[idx];
  j.faillite = true;
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
  noter(salle, j.nom + ' fait faillite' + (creancier === null ? '.' : ' face à ' + salle.joueurs[creancier].nom + '.'));
  verifierFin(salle);
}

/** Fait payer `montant` à `de` au profit de `a` (null = la banque). */
function payer(salle, de, montant, a) {
  const j = salle.joueurs[de];
  if (j.faillite || montant <= 0) return;
  if (j.argent < montant) liquider(salle, de, montant);
  if (j.argent >= montant) {
    j.argent -= montant;
    if (a !== null) salle.joueurs[a].argent += montant;
    return;
  }
  if (a !== null) salle.joueurs[a].argent += j.argent;
  j.argent = 0;
  faillite(salle, de, a);
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
  noter(salle, j.nom + ' file au poste de police.');
}

function deplacer(salle, idx, destination, avecDepart) {
  const j = salle.joueurs[idx];
  if (avecDepart && destination <= j.position) {
    j.argent += SALAIRE;
    noter(salle, j.nom + ' passe par le Départ : +' + SALAIRE + ' €.');
  }
  j.position = destination;
  arriver(salle, idx);
}

function tirerCarte(salle, idx, paquet) {
  const j = salle.joueurs[idx];
  const numero = salle.paquets[paquet].shift();
  const carte = CARTES[paquet][numero];
  if (carte.sortie) j.cartesSortie.push(paquet);
  else salle.paquets[paquet].push(numero);
  salle.derniereCarte = { paquet, texte: carte.texte, joueur: idx };
  noter(salle, j.nom + ' tire une carte ' + (paquet === 'mairie' ? 'Mairie' : 'Surprise') + ' : ' + carte.texte);

  if (carte.gain) j.argent += carte.gain;
  else if (carte.paie) payer(salle, idx, carte.paie, null);
  else if (carte.prison) envoyerAuPoste(salle, idx);
  else if (carte.recule) {
    j.position = (j.position - carte.recule + PLATEAU.length) % PLATEAU.length;
    arriver(salle, idx);
  } else if (carte.aller !== undefined) deplacer(salle, idx, carte.aller, !carte.sansDepart);
  else if (carte.chacun) {
    for (const k of actifs(salle)) if (k !== idx) payer(salle, idx, carte.chacun, k);
  } else if (carte.anniversaire) {
    for (const k of actifs(salle)) if (k !== idx) payer(salle, k, carte.anniversaire, idx);
  }
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
  const j = salle.joueurs[salle.tour];
  if (!j.faillite && salle.etape === 'achat') return;
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
        if (!j.faillite) {
          salle.etape = 'deplacement';
          avancer(salle, idx, des[0] + des[1]);
        }
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

  if (action === 'quitter') {
    if (salle.joueurs[moi].faillite) return;
    noter(salle, salle.joueurs[moi].nom + ' abandonne la partie.');
    const sonTour = salle.tour === moi;
    faillite(salle, moi, null);
    if (salle.phase === 'jeu') resoudreEnchereSiFinie(salle);
    if (sonTour) apresCoup(salle);
    salle.dernierCoup = Date.now();
    return;
  }

  if (GESTION.includes(action)) {
    if (salle.etape === 'enchere') refuser('Attends la fin de l\'enchère.');
    actionGestion(salle, moi, action, parseInt(valeur, 10));
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
    if (salle.tour === moi) refuser('C\'est ton tour, joue !');
    if (Date.now() - salle.dernierCoup < DELAI_INACTIF_S * 1000) refuser('Laisse-lui encore un peu de temps.');
    qui = salle.tour;
    noter(salle, salle.joueurs[moi].nom + ' joue à la place de ' + salle.joueurs[qui].nom + '.');
    if (salle.etape === 'achat') action = 'passer';
    else action = 'lancer';
  } else if (salle.tour !== moi) {
    refuser('Ce n\'est pas ton tour.');
  }

  const j = salle.joueurs[qui];
  if (action === 'lancer') {
    if (salle.etape !== 'lancer' && salle.etape !== 'prison') refuser('Termine d\'abord ton action.');
    actionLancer(salle);
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
    enchere: salle.enchere ? {
      case: salle.enchere.case, prix: salle.enchere.prix, meneur: salle.enchere.meneur,
      passe: salle.enchere.passe, depuis: salle.enchere.depuis,
    } : null,
    delaiEnchere: DELAI_ENCHERE_S,
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
  ]);
  tablesPretes = true;
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
  .wrap{max-width:640px; margin:0 auto;}
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

  .plateau{ display:grid; grid-template-columns:1.45fr repeat(9, 1fr) 1.45fr;
    grid-template-rows:1.45fr repeat(9, 1fr) 1.45fr; gap:1px; background:#3D5A40;
    border:2px solid #3D5A40; border-radius:8px; aspect-ratio:1/1; width:100%; color:var(--ink); }
  .case{ background:var(--plateau); position:relative; overflow:hidden; display:flex;
    flex-direction:column; align-items:center; justify-content:flex-start; cursor:pointer;
    font-size:clamp(5.5px, 1.45vw, 9px); line-height:1.05; text-align:center; padding:1px; }
  .case.coin{font-weight:700; justify-content:center; font-size:clamp(6px, 1.6vw, 10px);}
  .case .bande{width:100%; height:22%; flex:none; margin-bottom:1px;}
  .case .nom{word-break:break-word; hyphens:auto;}
  .case .prix{color:#556; margin-top:auto;}
  .case.cote .prix{display:none;}
  .case .bati{font-size:clamp(5px, 1.5vw, 9px); letter-spacing:-2px; font-weight:700; color:#555;}
  .enchere{background:#fff; border:2px solid var(--or); border-radius:8px; padding:5px 8px;
    font-size:clamp(0.65rem, 2.6vw, 0.9rem); max-width:96%;}
  .gestion{display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;}
  .gestion button{flex:1 1 45%; background:rgba(255,255,255,0.15); color:var(--panel); padding:8px;}
  .gestion button.btn-or{background:var(--or); color:var(--ink);}
  .titre-mini.hypo{opacity:0.35;}
  table.loyers{width:100%; font-size:0.8rem; border-collapse:collapse; margin-top:6px; color:var(--muted);}
  table.loyers td{padding:2px 0;} table.loyers td:last-child{text-align:right;}
  table.loyers tr.actuel td{color:var(--or); font-weight:700;}
  .case.choisie{outline:2px solid #000; outline-offset:-2px; z-index:2;}
  .case .pions{position:absolute; bottom:1px; left:1px; right:1px; display:flex; flex-wrap:wrap;
    justify-content:center; gap:1px;}
  .pion{width:clamp(7px, 2.3vw, 13px); height:clamp(7px, 2.3vw, 13px); border-radius:50%;
    border:1.5px solid #fff; box-shadow:0 0 2px #000;}
  .pion.actif{animation:pulse 1s infinite;}
  @keyframes pulse{50%{transform:scale(1.3);}}
  .centre{ grid-row:2 / 11; grid-column:2 / 11; background:#F6FAF3; display:flex; flex-direction:column;
    align-items:center; justify-content:center; padding:6px; text-align:center; gap:4px; color:var(--ink); }
  .centre .titre{font-weight:800; font-size:clamp(0.8rem, 3.4vw, 1.3rem); color:#3D5A40;}
  .centre .info{font-size:clamp(0.7rem, 2.8vw, 0.95rem);}
  .des{font-size:clamp(1.8rem, 9vw, 3rem); line-height:1;}
  .carte-tiree{background:#fff; border-radius:8px; padding:6px 8px; font-size:clamp(0.65rem, 2.6vw, 0.85rem);
    border:2px solid; max-width:95%;}
  .carte-tiree.surprise{border-color:#F28C28;} .carte-tiree.mairie{border-color:#2B4C9B;}
  .centre button{padding:7px 10px; font-size:clamp(0.75rem, 3vw, 0.95rem); margin:2px;}
  .centre .boutons{display:flex; flex-wrap:wrap; justify-content:center;}
  .btn-or{background:var(--or); color:var(--ink);} .btn-gris{background:#D9E2D5; color:var(--ink);}

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
  function recevoir(d) {
    ETAT = d;
    ECART = Date.now() - d.maintenant;
    if (ETAT.moi === null) { quitterLocal(); return; }
    rendre();
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
    if (ETAT && ETAT.phase === 'jeu' && (ETAT.tour !== ETAT.moi || ETAT.etape === 'enchere')) rendre();
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
      li.appendChild(el('span', '', j.nom + (i === ETAT.hote ? ' (hôte)' : '') + (i === ETAT.moi ? ' — toi' : '')));
      ul.appendChild(li);
    });
    b.appendChild(ul);
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
    return { depart: '➜', poste: '🚓', pause: '☕', police: '👮', carte: c.p === 'mairie' ? '🏛️' : '❓',
      gare: '🚆', service: c.court === 'Gaz' ? '🔥' : '📶', taxe: '💶' }[c.t] || '';
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

  function rendrePlateau() {
    var grille = el('div', 'plateau');
    PLATEAU.forEach(function (c, i) {
      var place = placeCase(i);
      var d = el('div', 'case' + (i % 10 === 0 ? ' coin' : '') + ((i > 10 && i < 20) || i > 30 ? ' cote' : '') + (CHOISIE === i ? ' choisie' : ''));
      d.style.gridRow = place[0];
      d.style.gridColumn = place[1];
      if (c.t === 'rue') {
        var bande = el('div', 'bande');
        bande.style.background = GROUPES[c.g];
        d.appendChild(bande);
      } else {
        d.appendChild(el('div', '', icone(c)));
      }
      d.appendChild(el('div', 'nom', c.court));
      var p = ETAT.proprio[i];
      if (p !== null) {
        d.style.boxShadow = 'inset 0 0 0 2px ' + ETAT.joueurs[p].couleur;
        var teinte = 'color-mix(in srgb, ' + ETAT.joueurs[p].couleur + ' 22%, #E8F1E4)';
        d.style.background = ETAT.hypo[i]
          ? 'repeating-linear-gradient(45deg, #E8F1E4 0 4px, #C9CFC6 4px 8px)'
          : teinte;
        if (ETAT.hypo[i]) d.appendChild(el('div', 'bati', 'hypo'));
        else if (ETAT.maisons[i] === 5) d.appendChild(el('div', 'bati', '🏨'));
        else if (ETAT.maisons[i]) d.appendChild(el('div', 'bati', '🏠'.repeat(ETAT.maisons[i])));
      } else if (c.prix) {
        d.appendChild(el('div', 'prix', c.prix + '€'));
      }
      var pions = el('div', 'pions');
      ETAT.joueurs.forEach(function (j, k) {
        if (j.faillite || j.position !== i) return;
        var pion = el('div', 'pion' + (k === ETAT.tour && ETAT.phase === 'jeu' ? ' actif' : ''));
        pion.style.background = j.couleur;
        pion.title = j.nom;
        pions.appendChild(pion);
      });
      d.appendChild(pions);
      d.onclick = function () { CHOISIE = CHOISIE === i ? null : i; rendre(); };
      grille.appendChild(d);
    });
    grille.appendChild(rendreCentre());
    return grille;
  }

  function rendreCentre() {
    var c = el('div', 'centre');
    c.appendChild(el('div', 'titre', 'Pavés de Paris'));
    c.appendChild(el('div', 'info', 'Salle ' + ETAT.code + ' · tour ' + ETAT.tourNo + (ETAT.toursMax ? '/' + ETAT.toursMax : '')));

    if (ETAT.phase === 'fin') {
      c.appendChild(el('div', 'info', '🏆 ' + ETAT.classement[0].nom + ' gagne !'));
      if (ETAT.moi === ETAT.hote) c.appendChild(bouton('Nouvelle partie', 'btn-or', function () { agir('nouvelle'); }));
      return c;
    }

    if (ETAT.des) c.appendChild(el('div', 'des', DES[ETAT.des[0] - 1] + ' ' + DES[ETAT.des[1] - 1]));
    if (ETAT.derniereCarte) {
      var carte = el('div', 'carte-tiree ' + ETAT.derniereCarte.paquet);
      carte.appendChild(el('b', '', (ETAT.derniereCarte.paquet === 'mairie' ? '🏛️ Mairie' : '❓ Surprise') + ' — '));
      carte.appendChild(document.createTextNode(ETAT.derniereCarte.texte));
      c.appendChild(carte);
    }

    var courant = ETAT.joueurs[ETAT.tour];
    var moi = ETAT.moi !== null ? ETAT.joueurs[ETAT.moi] : null;
    var boutons = el('div', 'boutons');
    if (ETAT.etape === 'enchere' && ETAT.enchere) {
      var e = ETAT.enchere;
      var bloc = el('div', 'enchere');
      bloc.appendChild(el('b', '', '🔨 Enchères : ' + PLATEAU[e.case].nom));
      bloc.appendChild(el('div', '', e.meneur === null
        ? 'Aucune offre pour l\u2019instant (prix d\u2019achat ' + euros(PLATEAU[e.case].prix) + ').'
        : 'Meilleure offre : ' + euros(e.prix) + ' par ' + ETAT.joueurs[e.meneur].nom + '.'));
      var restants = ETAT.joueurs.filter(function (j, k) { return !j.faillite && e.passe.indexOf(k) === -1 && k !== e.meneur; })
        .map(function (j) { return j.nom; });
      if (restants.length) bloc.appendChild(el('div', '', 'En attente : ' + restants.join(', ')));
      c.appendChild(bloc);
      var peutMiser = moi && !moi.faillite && e.passe.indexOf(ETAT.moi) === -1;
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
      var attente = (Date.now() - ECART - e.depuis) / 1000;
      if (attente > ETAT.delaiEnchere) {
        boutons.appendChild(bouton('Clore l\u2019enchère', 'btn-gris', function () { agir('clore'); }));
      }
    } else if (ETAT.tour === ETAT.moi) {
      if (ETAT.etape === 'lancer') {
        c.appendChild(el('div', 'info', 'À toi de jouer !'));
        boutons.appendChild(bouton('🎲 Lancer les dés', 'btn-or', function () { agir('lancer'); }));
      } else if (ETAT.etape === 'achat') {
        var cs = PLATEAU[moi.position];
        c.appendChild(el('div', 'info', cs.nom + ' est libre.'));
        boutons.appendChild(bouton('Acheter (' + euros(cs.prix) + ')', 'btn-or', function () { agir('acheter'); }));
        boutons.appendChild(bouton('Ne pas acheter', 'btn-gris', function () { agir('passer'); }));
      } else if (ETAT.etape === 'prison') {
        c.appendChild(el('div', 'info', 'Tu es au poste (essai ' + (moi.essais + 1) + '/3).'));
        boutons.appendChild(bouton('🎲 Tenter un double', 'btn-or', function () { agir('lancer'); }));
        var caution = bouton('Payer ' + CAUTION + ' €', 'btn-gris', function () { agir('caution'); });
        caution.disabled = moi.argent < CAUTION;
        boutons.appendChild(caution);
        if (moi.cartesSortie) boutons.appendChild(bouton('Libéré sur parole', 'btn-gris', function () { agir('carte'); }));
      }
    } else {
      c.appendChild(el('div', 'info', 'Au tour de ' + courant.nom + (ETAT.etape === 'achat' ? ' (achète ?)' : '')));
      var inactif = (Date.now() - ECART - ETAT.dernierCoup) / 1000;
      if (moi && !moi.faillite && inactif > ETAT.delaiInactif) {
        boutons.appendChild(bouton('Jouer à sa place', 'btn-gris', function () { agir('forcer'); }));
      }
    }
    c.appendChild(boutons);
    return c;
  }

  function rendreDetail() {
    var c = PLATEAU[CHOISIE];
    var b = el('div', 'bloc detail');
    b.appendChild(el('h2', '', icone(c) + ' ' + c.nom));
    function ligne(g, d) {
      var l = el('div', 'ligne');
      l.appendChild(el('span', '', g));
      l.appendChild(el('b', '', d));
      b.appendChild(l);
    }
    if (c.prix) {
      ligne('Prix', euros(c.prix));
      ligne('Loyer', loyerAffiche(CHOISIE));
      var p = ETAT.proprio[CHOISIE];
      ligne('Propriétaire', p === null ? 'la banque (libre)' : ETAT.joueurs[p].nom);
      if (ETAT.hypo[CHOISIE]) ligne('Hypothèque', 'levée pour ' + euros(c.leve));
      if (c.t === 'rue') {
        var t = el('table', 'loyers');
        var lignes = [['Terrain nu', c.loyer], ['Quartier complet', c.loyer * 2]];
        for (var n = 1; n <= 5; n++) lignes.push([n === 5 ? 'Hôtel' : n + ' maison' + (n > 1 ? 's' : ''), c.loyer * MULT_MAISONS[n]]);
        lignes.forEach(function (l, k) {
          var tr = el('tr');
          var niveau = ETAT.maisons[CHOISIE] ? ETAT.maisons[CHOISIE] + 1 : -1;
          if (k === niveau) tr.className = 'actuel';
          tr.appendChild(el('td', '', l[0]));
          tr.appendChild(el('td', '', euros(l[1])));
          t.appendChild(tr);
        });
        b.appendChild(t);
        b.appendChild(el('div', 'sous', 'Maison ou hôtel : ' + euros(c.maison) + ' (revente moitié prix). '
          + 'On construit quand on a tout le quartier, de façon équilibrée.'));
      }
      if (p !== null && p === ETAT.moi && ETAT.phase === 'jeu' && !ETAT.joueurs[p].faillite) b.appendChild(rendreGestion(CHOISIE));
    } else if (c.t === 'taxe') {
      ligne('À payer', euros(c.montant));
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

  function rendreJoueurs() {
    var z = el('div', 'joueurs');
    ETAT.joueurs.forEach(function (j, i) {
      var f = el('div', 'fiche' + (i === ETAT.tour && ETAT.phase === 'jeu' ? ' son-tour' : '') + (j.faillite ? ' ko' : ''));
      f.style.borderLeftColor = j.couleur;
      var h = el('div', 'haut');
      h.appendChild(el('span', '', j.nom + (i === ETAT.moi ? ' (toi)' : '')));
      h.appendChild(el('span', '', j.faillite ? 'faillite' : euros(j.argent)));
      f.appendChild(h);
      if (!j.faillite) {
        var info = PLATEAU[j.position].court + (j.enPrison ? ' — au poste 🚓' : '')
          + (j.cartesSortie ? ' · 🎟️ ' + j.cartesSortie : '') + ' · fortune ' + euros(j.fortune);
        f.appendChild(el('div', 'bas', info));
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
    app.appendChild(rendrePlateau());
    app.appendChild(zoneStatut());
    if (ETAT.phase === 'fin') app.appendChild(rendreClassement());
    if (CHOISIE !== null) app.appendChild(rendreDetail());
    app.appendChild(rendreJoueurs());
    var jb = el('div', 'bloc');
    jb.style.marginTop = '10px';
    jb.appendChild(el('h2', '', 'Derniers coups'));
    var ul = el('ul', 'journal');
    ETAT.journal.forEach(function (m) { ul.appendChild(el('li', '', m)); });
    jb.appendChild(ul);
    app.appendChild(jb);
    var moi = ETAT.joueurs[ETAT.moi];
    if (ETAT.phase === 'jeu' && !moi.faillite) {
      app.appendChild(bouton('Abandonner la partie', 'discret', function () {
        if (confirm('Abandonner ? Tes biens retournent à la banque et tu ne pourras plus jouer cette partie.')) agir('quitter');
      }));
    }
    app.appendChild(bouton('Retour à l’accueil', 'discret', quitterLocal));
  }

  function rendre() {
    app.innerHTML = '';
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

function pageHtml(joueursConnus) {
  // Wrangler (keep_names) peut glisser des appels __name() dans le code sérialisé.
  const donnees = 'var __name = function (f) { return f; };'
    + 'var PLATEAU = ' + toScriptJson(PLATEAU) + ';'
    + 'var GROUPES = ' + toScriptJson(GROUPES) + ';'
    + 'var JOUEURS = ' + toScriptJson(joueursConnus) + ';'
    + 'var TOURS = ' + toScriptJson(TOURS_CHOIX) + ';'
    + 'var TOURS_DEFAUT = ' + TOURS_DEFAUT + ';'
    + 'var MIN_JOUEURS = ' + MIN_JOUEURS + ';'
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

      if (chemin === '/api/etat') {
        const code = normaliserCode(url.searchParams.get('code'));
        const jeton = jetonValide(url.searchParams.get('jeton'));
        if (!code || !jeton) return erreur('Requête incomplète.');
        const courant = await lireSalle(env, code);
        if (!courant) return erreur('Salle introuvable ou expirée.', 404);
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

