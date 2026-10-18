/**
 * Worker "skyjoenligne" — le jeu de Skyjo jouable à plusieurs en ligne.
 *
 * Chaque joueur ouvre la page sur son téléphone, crée ou rejoint une salle
 * avec un code court, et joue son tour : pioche, défausse, échanges, colonnes
 * identiques, fin de manche et comptage sont gérés par le worker.
 *
 * L'état des salles vit dans D1 (binding DB) : contrairement au KV, une
 * lecture juste après une écriture renvoie bien la dernière version, ce dont
 * un jeu au tour par tour a besoin. Les clients interrogent /api/etat toutes
 * les 1,5 s et ne reçoivent que ce qu'ils ont le droit de voir : une carte
 * face cachée n'est jamais envoyée, pas même à son propriétaire.
 */

const LIMITE_DEFAUT = 100;
const LIMITE_MIN = 10;
const LIMITE_MAX = 1000;
const MIN_JOUEURS = 2;
const MAX_JOUEURS = 8;
const CASES = 12;
const COLONNES = 4;
const LIGNES = 3;
const JOURNAL_MAX = 6;
const SALLE_TTL_H = 48;

const COULEURS = [
  '#2A9D8F', '#E76F51', '#E9C46A', '#8ECAE6',
  '#B392AC', '#90BE6D', '#F4A261', '#7B8FD6',
];

/* ---------------------------------------------------------------- helpers */

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

function erreur(message, status = 400) {
  return json({ erreur: message }, status);
}

function toScriptJson(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

/** Code de salle lisible : pas de 0/O/1/I pour éviter les confusions. */
function nouveauCode() {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const tirage = crypto.getRandomValues(new Uint8Array(4));
  let code = '';
  for (const octet of tirage) code += alphabet[octet % alphabet.length];
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

function melanger(cartes) {
  for (let i = cartes.length - 1; i > 0; i--) {
    const j = crypto.getRandomValues(new Uint32Array(1))[0] % (i + 1);
    const tampon = cartes[i];
    cartes[i] = cartes[j];
    cartes[j] = tampon;
  }
  return cartes;
}

/* ------------------------------------------------------------------- jeu */

/** 150 cartes : cinq -2, dix -1, quinze 0, puis dix de chaque valeur 1 à 12. */
function nouveauPaquet() {
  const cartes = [];
  for (let i = 0; i < 5; i++) cartes.push(-2);
  for (let i = 0; i < 10; i++) cartes.push(-1);
  for (let i = 0; i < 15; i++) cartes.push(0);
  for (let valeur = 1; valeur <= 12; valeur++) {
    for (let i = 0; i < 10; i++) cartes.push(valeur);
  }
  return melanger(cartes);
}

function nouvelleSalle(code, limite) {
  const maintenant = new Date().toISOString();
  return {
    code,
    limite,
    creee: maintenant,
    phase: 'attente',
    manche: 0,
    joueurs: [],
    pioche: [],
    defausse: [],
    tour: null,
    carteEnMain: null,
    declencheur: null,
    journal: ['Salle créée. Partagez le code ' + code + '.'],
  };
}

function nouveauJoueur(jeton, nom) {
  return {
    jeton,
    nom,
    grille: [],
    pret: false,
    scoreTotal: 0,
    scoresManches: [],
    absent: false,
  };
}

function noter(salle, message) {
  salle.journal.push(message);
  if (salle.journal.length > JOURNAL_MAX) {
    salle.journal = salle.journal.slice(-JOURNAL_MAX);
  }
}

function cartesEnJeu(joueur) {
  return joueur.grille.filter((c) => !c.retiree);
}

function totalVisible(joueur) {
  return cartesEnJeu(joueur)
    .filter((c) => c.visible)
    .reduce((somme, c) => somme + c.v, 0);
}

function toutRetourne(joueur) {
  return cartesEnJeu(joueur).every((c) => c.visible);
}

function distribuer(salle) {
  const pioche = nouveauPaquet();
  salle.manche += 1;
  for (const joueur of salle.joueurs) {
    joueur.grille = [];
    for (let i = 0; i < CASES; i++) {
      joueur.grille.push({ v: pioche.pop(), visible: false, retiree: false });
    }
    joueur.pret = false;
  }
  salle.defausse = [pioche.pop()];
  salle.pioche = pioche;
  salle.phase = 'revelation';
  salle.tour = null;
  salle.carteEnMain = null;
  salle.declencheur = null;
  salle.journal = ['Manche ' + salle.manche + ' : chacun retourne deux cartes.'];
}

/** Le joueur dont les deux cartes retournées totalisent le plus commence. */
function choisirPremierJoueur(salle) {
  let meilleur = 0;
  let meilleureSomme = -Infinity;
  let meilleureCarte = -Infinity;

  salle.joueurs.forEach((joueur, index) => {
    if (joueur.absent) return;
    const visibles = joueur.grille.filter((c) => c.visible).map((c) => c.v);
    const somme = visibles.reduce((s, v) => s + v, 0);
    const plusHaute = Math.max(...visibles);
    if (somme > meilleureSomme || (somme === meilleureSomme && plusHaute > meilleureCarte)) {
      meilleur = index;
      meilleureSomme = somme;
      meilleureCarte = plusHaute;
    }
  });
  if (meilleureSomme === -Infinity) meilleureSomme = 0;

  salle.tour = meilleur;
  salle.phase = 'jeu';
  noter(salle, salle.joueurs[meilleur].nom + ' commence (' + meilleureSomme + ' points visibles).');
}

function tirerPioche(salle) {
  if (salle.pioche.length === 0) {
    if (salle.defausse.length <= 1) return null;
    const dessus = salle.defausse.pop();
    salle.pioche = melanger(salle.defausse);
    salle.defausse = [dessus];
    noter(salle, 'Pioche épuisée : la défausse est remélangée.');
  }
  return salle.pioche.pop();
}

/** Une colonne de trois cartes visibles identiques quitte le jeu. */
function retirerColonnes(salle, joueur) {
  for (let colonne = 0; colonne < COLONNES; colonne++) {
    const cases = [];
    for (let ligne = 0; ligne < LIGNES; ligne++) {
      cases.push(joueur.grille[colonne + ligne * COLONNES]);
    }
    const complete = cases.every((c) => c.visible && !c.retiree);
    if (!complete) continue;
    if (cases[0].v !== cases[1].v || cases[1].v !== cases[2].v) continue;

    for (const carte of cases) {
      carte.retiree = true;
      salle.defausse.push(carte.v);
    }
    noter(salle, joueur.nom + ' élimine une colonne de ' + cases[0].v + '.');
    return true;
  }
  return false;
}

function finDeTour(salle) {
  const joueur = salle.joueurs[salle.tour];
  salle.carteEnMain = null;
  retirerColonnes(salle, joueur);

  if (salle.declencheur === null && toutRetourne(joueur)) {
    salle.declencheur = salle.tour;
    noter(salle, joueur.nom + ' a retourné toutes ses cartes : dernier tour !');
  }

  const suivant = prochainActif(salle);
  if (suivant === null) {
    terminerManche(salle);
    return;
  }
  salle.tour = suivant;
}

/** Le prochain joueur encore là, ou null quand la manche doit s'arrêter. */
function prochainActif(salle) {
  const nombre = salle.joueurs.length;
  let index = salle.tour;
  for (let pas = 0; pas < nombre; pas++) {
    index = (index + 1) % nombre;
    if (salle.declencheur !== null && index === salle.declencheur) return null;
    if (!salle.joueurs[index].absent) return index;
  }
  return null;
}

function terminerManche(salle) {
  for (const joueur of salle.joueurs) {
    for (const carte of joueur.grille) {
      if (!carte.retiree) carte.visible = true;
    }
  }

  const scores = salle.joueurs.map((joueur) =>
    cartesEnJeu(joueur).reduce((somme, c) => somme + c.v, 0));

  const declencheur = salle.declencheur;
  if (declencheur !== null) {
    const mini = Math.min(...scores);
    const seulPlusBas = scores[declencheur] === mini
      && scores.filter((s) => s === mini).length === 1;
    if (!seulPlusBas && scores[declencheur] > 0) {
      noter(salle, salle.joueurs[declencheur].nom + ' n\'est pas le plus bas : score doublé.');
      scores[declencheur] *= 2;
    }
  }

  salle.joueurs.forEach((joueur, index) => {
    joueur.scoresManches.push(scores[index]);
    joueur.scoreTotal += scores[index];
  });

  salle.tour = null;
  salle.carteEnMain = null;

  if (salle.joueurs.some((j) => j.scoreTotal >= salle.limite)) {
    salle.phase = 'fin_partie';
    noter(salle, 'Partie terminée à ' + salle.limite + ' points. ' + phraseGagnants(salle));
  } else {
    salle.phase = 'fin_manche';
    noter(salle, 'Manche ' + salle.manche + ' terminée.');
  }
}

function gagnants(salle) {
  const mini = Math.min(...salle.joueurs.map((j) => j.scoreTotal));
  return salle.joueurs.filter((j) => j.scoreTotal === mini).map((j) => j.nom);
}

function phraseGagnants(salle) {
  const noms = gagnants(salle);
  return noms.length > 1 ? 'Égalité entre ' + noms.join(' et ') + '.' : noms[0] + ' gagne !';
}

/* --------------------------------------------------------------- actions */

class ErreurJeu extends Error {}

function refuser(message) {
  throw new ErreurJeu(message);
}

function indexJoueur(salle, jeton) {
  return salle.joueurs.findIndex((j) => j.jeton === jeton);
}

function caseValide(index) {
  return Number.isInteger(index) && index >= 0 && index < CASES;
}

/**
 * Applique une action d'un joueur sur la salle, ou lève une ErreurJeu.
 * L'appelant se charge d'enregistrer la salle modifiée.
 */
function appliquerAction(salle, jeton, action, index) {
  const moi = indexJoueur(salle, jeton);
  if (moi === -1) refuser('Tu n\'es pas dans cette salle.');
  const joueur = salle.joueurs[moi];

  if (action === 'demarrer') {
    if (salle.phase !== 'attente' && salle.phase !== 'fin_manche') {
      refuser('La partie est déjà en cours.');
    }
    if (salle.joueurs.length < MIN_JOUEURS) refuser('Il faut au moins deux joueurs.');
    if (salle.phase === 'attente' && moi !== 0) {
      refuser('Seul ' + salle.joueurs[0].nom + ' peut lancer la partie.');
    }
    distribuer(salle);
    return;
  }

  if (action === 'nouvellePartie') {
    if (salle.phase !== 'fin_partie') refuser('La partie n\'est pas terminée.');
    for (const j of salle.joueurs) {
      j.scoreTotal = 0;
      j.scoresManches = [];
      j.grille = [];
      j.pret = false;
    }
    salle.manche = 0;
    salle.phase = 'attente';
    salle.journal = ['Nouvelle partie : en attente du lancement.'];
    return;
  }

  if (action === 'quitter') {
    if (salle.phase === 'attente') {
      salle.joueurs.splice(moi, 1);
      noter(salle, joueur.nom + ' a quitté la salle.');
      return;
    }

    joueur.absent = true;
    noter(salle, joueur.nom + ' a quitté la partie.');

    // Sans ça, les autres resteraient à attendre le tour de quelqu'un de parti.
    if (salle.phase === 'revelation') {
      joueur.pret = true;
      if (salle.joueurs.every((j) => j.pret)) choisirPremierJoueur(salle);
    } else if (salle.phase === 'jeu' && salle.tour === moi) {
      if (salle.carteEnMain) {
        salle.defausse.push(salle.carteEnMain.v);
        salle.carteEnMain = null;
      }
      finDeTour(salle);
    }
    return;
  }

  if (action === 'reveler') {
    if (salle.phase !== 'revelation') refuser('Ce n\'est plus le moment de retourner des cartes.');
    if (!caseValide(index)) refuser('Carte inconnue.');
    if (joueur.pret) refuser('Tu as déjà retourné tes deux cartes.');
    const carte = joueur.grille[index];
    if (carte.visible) refuser('Cette carte est déjà retournée.');

    carte.visible = true;
    if (joueur.grille.filter((c) => c.visible).length >= 2) joueur.pret = true;

    if (salle.joueurs.every((j) => j.pret)) choisirPremierJoueur(salle);
    return;
  }

  if (salle.phase !== 'jeu') refuser('La manche n\'est pas en cours.');
  if (salle.tour !== moi) refuser('Ce n\'est pas ton tour.');

  if (action === 'piocher') {
    if (salle.carteEnMain) refuser('Tu as déjà une carte en main.');
    const valeur = tirerPioche(salle);
    if (valeur === null) refuser('Il n\'y a plus de cartes à piocher.');
    salle.carteEnMain = { v: valeur, origine: 'pioche' };
    return;
  }

  if (action === 'prendreDefausse') {
    if (salle.carteEnMain) refuser('Tu as déjà une carte en main.');
    if (salle.defausse.length === 0) refuser('La défausse est vide.');
    salle.carteEnMain = { v: salle.defausse.pop(), origine: 'defausse' };
    return;
  }

  if (action === 'echanger') {
    if (!salle.carteEnMain) refuser('Pioche une carte ou prends la défausse d\'abord.');
    if (!caseValide(index)) refuser('Carte inconnue.');
    const carte = joueur.grille[index];
    if (carte.retiree) refuser('Cette case a été éliminée.');

    const sortante = carte.v;
    carte.v = salle.carteEnMain.v;
    carte.visible = true;
    salle.defausse.push(sortante);
    noter(salle, joueur.nom + ' place un ' + carte.v + ' et défausse un ' + sortante + '.');
    finDeTour(salle);
    return;
  }

  if (action === 'defausser') {
    if (!salle.carteEnMain) refuser('Pioche une carte d\'abord.');
    if (salle.carteEnMain.origine !== 'pioche') {
      refuser('Une carte prise dans la défausse doit être placée dans ta grille.');
    }
    if (!caseValide(index)) refuser('Choisis la carte à retourner.');
    const carte = joueur.grille[index];
    if (carte.retiree) refuser('Cette case a été éliminée.');
    if (carte.visible) refuser('Choisis une carte encore face cachée.');

    salle.defausse.push(salle.carteEnMain.v);
    carte.visible = true;
    noter(salle, joueur.nom + ' défausse un ' + salle.carteEnMain.v + ' et retourne un ' + carte.v + '.');
    finDeTour(salle);
    return;
  }

  refuser('Action inconnue.');
}

/* ------------------------------------------------------------------- vue */

/** Ce qu'un joueur a le droit de voir : jamais une carte face cachée. */
function vuePour(salle, version, jeton) {
  const moi = indexJoueur(salle, jeton);

  const joueurs = salle.joueurs.map((joueur, index) => ({
    nom: joueur.nom,
    couleur: COULEURS[index % COULEURS.length],
    pret: joueur.pret,
    absent: joueur.absent,
    scoreTotal: joueur.scoreTotal,
    scoresManches: joueur.scoresManches,
    visible: totalVisible(joueur),
    grille: joueur.grille.map((carte) => {
      if (carte.retiree) return { etat: 'retiree' };
      if (carte.visible) return { etat: 'visible', v: carte.v };
      return { etat: 'cachee' };
    }),
  }));

  let carteEnMain = null;
  if (salle.carteEnMain) {
    const publique = salle.carteEnMain.origine === 'defausse' || salle.tour === moi;
    carteEnMain = {
      origine: salle.carteEnMain.origine,
      v: publique ? salle.carteEnMain.v : null,
    };
  }

  return {
    code: salle.code,
    version,
    phase: salle.phase,
    manche: salle.manche,
    limite: salle.limite,
    tour: salle.tour,
    moi: moi === -1 ? null : moi,
    joueurs,
    carteEnMain,
    defausse: salle.defausse.length ? salle.defausse[salle.defausse.length - 1] : null,
    piocheTaille: salle.pioche.length,
    declencheur: salle.declencheur,
    journal: salle.journal,
    gagnants: salle.phase === 'fin_partie' ? gagnants(salle) : [],
  };
}

/* -------------------------------------------------------------------- D1 */

function bdd(env) {
  return env && env.DB ? env.DB : null;
}

async function lireSalle(env, code) {
  const ligne = await bdd(env)
    .prepare('SELECT version, etat FROM salles WHERE code = ?')
    .bind(code)
    .first();
  if (!ligne) return null;
  try {
    return { version: ligne.version, salle: JSON.parse(ligne.etat) };
  } catch (err) {
    return null;
  }
}

/**
 * Relit la salle, applique `modifier`, puis n'écrit que si personne n'a joué
 * entre-temps ; sinon on recommence sur l'état frais.
 */
async function modifierSalle(env, code, modifier) {
  for (let essai = 0; essai < 4; essai++) {
    const courant = await lireSalle(env, code);
    if (!courant) refuser('Salle introuvable ou expirée.');

    modifier(courant.salle);

    const version = courant.version + 1;
    const resultat = await bdd(env)
      .prepare('UPDATE salles SET etat = ?, version = ?, maj = ? WHERE code = ? AND version = ?')
      .bind(JSON.stringify(courant.salle), version, new Date().toISOString(), code, courant.version)
      .run();

    if (resultat.meta.changes === 1) return { version, salle: courant.salle };
  }
  refuser('Trop de coups en même temps, réessaie.');
}

async function creerSalle(env, limite) {
  for (let essai = 0; essai < 5; essai++) {
    const code = nouveauCode();
    const salle = nouvelleSalle(code, limite);
    const resultat = await bdd(env)
      .prepare('INSERT OR IGNORE INTO salles (code, version, etat, maj) VALUES (?, 1, ?, ?)')
      .bind(code, JSON.stringify(salle), new Date().toISOString())
      .run();
    if (resultat.meta.changes === 1) return code;
  }
  refuser('Impossible de créer une salle, réessaie.');
}

async function purgerSalles(env) {
  const limite = new Date(Date.now() - SALLE_TTL_H * 3600 * 1000).toISOString();
  await bdd(env).prepare('DELETE FROM salles WHERE maj < ?').bind(limite).run();
}

async function lireJoueurs(env) {
  const res = await bdd(env).prepare('SELECT nom FROM joueurs ORDER BY nom COLLATE NOCASE').all();
  return (res.results || []).map((l) => l.nom);
}

async function ajouterJoueur(env, nom) {
  await bdd(env).prepare('INSERT OR IGNORE INTO joueurs (nom) VALUES (?)').bind(nom).run();
  return lireJoueurs(env);
}

async function supprimerJoueurConnu(env, nom) {
  await bdd(env).prepare('DELETE FROM joueurs WHERE nom = ? COLLATE NOCASE').bind(nom).run();
  return lireJoueurs(env);
}

/* ---------------------------------------------------------------- styles */

const CSS = `
  :root{ --bg:#14213D; --panel:#FFF8EC; --ink:#14213D; --muted:#9AA5C4; --or:#FFD166;
    /* Tailles de secours : ajusterGrilles() les recalcule dès le premier rendu. */
    --carte-moi:66px; --carte-adv:46px; --carte-pile:64px; --adv-larg:200px;
    --c:var(--carte-moi); --g:5px; }
  *{box-sizing:border-box;}
  body{
    margin:0; min-height:100vh; background:var(--bg);
    background-image: radial-gradient(circle at 20% 10%, rgba(255,255,255,0.06), transparent 45%);
    font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color:var(--panel); padding:12px 12px 24px;
  }
  .wrap{max-width:560px; margin:0 auto;}
  h1{text-align:center; font-size:1.5rem; margin:0 0 2px;}
  .subtitle{text-align:center; color:var(--muted); font-size:0.85rem; margin-bottom:16px;}
  .card{background:rgba(255,255,255,0.06); border-radius:14px; padding:10px; margin-bottom:10px;}
  .card h2{font-size:1rem; margin:0 0 8px;}
  .entete{display:flex; justify-content:space-between; gap:8px; font-size:0.76rem;
    color:var(--muted); margin-bottom:8px;}
  label{display:block; font-size:0.78rem; color:var(--muted); margin:10px 0 4px;}
  input, select{
    width:100%; padding:9px 8px; border-radius:10px; border:1px solid #ddd;
    font-size:1rem; text-align:center; color:var(--ink); background:#fff;
  }
  button{border:none; border-radius:10px; padding:10px 14px; font-size:0.95rem; font-weight:600; cursor:pointer;}
  button:disabled{opacity:0.45; cursor:default;}
  .primary{background:var(--or); color:#14213D; width:100%; font-size:1.05rem; margin-top:12px;}
  .ghost{background:transparent; border:1px solid var(--muted); color:var(--panel);}
  .rangee{display:flex; gap:8px; align-items:center;}
  .rangee > *{flex:1;}
  .rangee button{flex:0 0 auto;}
  .statut{text-align:center; font-size:0.8rem; color:var(--muted); min-height:16px; margin-bottom:8px;}
  .erreur{color:#FFB4A2;}
  .code-salle{
    text-align:center; font-size:2rem; font-weight:700; letter-spacing:6px;
    color:var(--or); margin:6px 0 2px;
  }
  .bandeau{
    text-align:center; border-radius:12px; padding:8px; font-weight:700; margin-bottom:10px;
    background:rgba(255,255,255,0.1);
  }
  .bandeau.moi{background:var(--or); color:#14213D;}
  .bandeau.fin{background:#2A9D8F; color:#fff;}

  .grille{display:grid; grid-template-columns:repeat(4, var(--c)); gap:var(--g);
    justify-content:center;}
  .card > .grille{--c:var(--carte-moi); --g:6px; margin:0 auto;}
  .carte{
    aspect-ratio:1; border-radius:calc(var(--c) * 0.13);
    display:flex; align-items:center; justify-content:center;
    font-weight:700; font-size:calc(var(--c) * 0.39); color:#14213D;
    border:2px solid rgba(0,0,0,0.15); padding:0; width:100%;
  }
  .carte.dos{
    background:repeating-linear-gradient(45deg,#1D3461,#1D3461 4px,#26457C 4px,#26457C 8px);
    color:rgba(255,255,255,0.4); font-size:calc(var(--c) * 0.34);
    border-color:rgba(255,255,255,0.25);
  }
  .carte.vide{background:transparent; border:2px dashed rgba(255,255,255,0.18); cursor:default;}
  .carte:disabled{opacity:1;}
  .carte.cliquable{cursor:pointer; box-shadow:0 0 0 2px var(--or);}
  .carte.cliquable:hover{transform:translateY(-2px);}

  .table{display:flex; gap:12px; justify-content:center; align-items:flex-start; margin-bottom:10px;}
  .pile{text-align:center; --c:var(--carte-pile); width:var(--c);}
  .pile .etiquette{font-size:0.7rem; color:var(--muted); margin-top:4px; display:block;}
  .pile .etiquette.jetee{color:var(--or); font-weight:600;}

  .adversaires{display:grid; gap:8px; justify-items:center;
    grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));}
  .adv{background:rgba(255,255,255,0.05); border-radius:12px; padding:7px;
    border-top:4px solid var(--accent); width:100%; max-width:var(--adv-larg);}
  .adv .nom{font-size:0.8rem; font-weight:600; display:flex; justify-content:space-between; gap:6px; margin-bottom:5px;}
  .adv .nom span{min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
  .adv .nom .pts{color:var(--muted); font-weight:400; flex:0 0 auto;}
  .adv .grille{--c:var(--carte-adv); --g:4px;}
  .adv .carte{border-width:1px;}
  .adv.actif{box-shadow:0 0 0 2px var(--or);}

  table{width:100%; border-collapse:collapse; font-size:0.88rem;}
  th, td{padding:7px 5px; text-align:center; border-bottom:1px solid rgba(255,255,255,0.08);}
  th{color:var(--muted); font-weight:600;}
  tr:last-child td{border-bottom:none;}
  .journal{font-size:0.72rem; color:var(--muted); line-height:1.45; margin-top:8px;}
  .chips{display:flex; flex-wrap:wrap; gap:8px; margin:6px 0 4px;}
  .chip{display:inline-flex; align-items:center; gap:8px; background:rgba(255,255,255,0.12);
    border-radius:999px; padding:5px 8px 5px 12px; font-size:0.82rem;}
  .chip button{background:none; color:var(--muted); padding:0 2px; font-size:0.8rem;}
  .empty{text-align:center; color:var(--muted); padding:12px 0; font-size:0.85rem;}
  .aide{font-size:0.76rem; color:var(--muted); text-align:center; margin-top:6px;}
  .lien{background:none; color:var(--or); text-decoration:underline; padding:0 2px; font-size:0.78rem;}
  a{color:var(--or);}

  /* Petits écrans : on rogne les marges pour rapprocher les cartes des bords. */
  @media (max-width: 420px), (max-height: 720px){
    body{padding:8px 5px 14px;}
    .card{padding:7px 5px;}
    .card > .grille{--g:5px;}
    .adv{padding:5px 4px;}
    .adv .grille{--g:3px;}
    .entete{margin-bottom:6px;}
  }

  /* Écrans courts : moins de bavardage, plus de place pour les cartes. */
  @media (max-height: 640px){
    .bandeau{padding:6px; margin-bottom:8px;}
    .journal div:not(:last-child){display:none;}
  }
`;

function pageHtml(joueursConnus) {
  return '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + '<title>Skyjo en ligne</title><style>' + CSS + '</style></head>'
    + '<body><div class="wrap"><div id="app"></div></div>'
    + '<script>var JOUEURS = ' + toScriptJson(joueursConnus) + ';' + JS_APP + '</script>'
    + '</body></html>';
}

const FAVICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
  + '<rect width="64" height="64" rx="14" fill="#14213D"/>'
  + '<text x="32" y="45" font-size="34" font-family="system-ui, sans-serif" '
  + 'font-weight="700" text-anchor="middle" fill="#FFD166">S</text></svg>';

/* ------------------------------------------------------------ client web */

const JS_APP_BASE = `
  var MIN_JOUEURS = ${MIN_JOUEURS}, MAX_JOUEURS = ${MAX_JOUEURS};
  var app = document.getElementById('app');
  var ETAT = null;
  var CODE = null;
  var STATUT = '';
  var ERREUR = false;
  var MODE = 'echanger';
  var minuteur = null;
  var enCours = false;
  var echecs = 0;

  var JETON = localStorage.getItem('skyjo:jeton');
  if (!JETON) {
    JETON = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
    localStorage.setItem('skyjo:jeton', JETON);
  }
  var MON_NOM = localStorage.getItem('skyjo:nom') || '';

  /* ---------------------------------------------------------- utilitaires */

  function el(balise, classe, texte) {
    var noeud = document.createElement(balise);
    if (classe) noeud.className = classe;
    if (texte !== undefined && texte !== null) noeud.textContent = texte;
    return noeud;
  }

  function couleurCarte(v) {
    if (v <= -1) return '#9B7EDE';
    if (v === 0) return '#8ECAE6';
    if (v <= 4) return '#90BE6D';
    if (v <= 8) return '#F4D35E';
    return '#E76F51';
  }

  function dire(texte, estErreur) {
    STATUT = texte || '';
    ERREUR = !!estErreur;
    var zone = document.getElementById('statut');
    if (zone) {
      zone.textContent = STATUT;
      zone.className = 'statut' + (ERREUR ? ' erreur' : '');
    }
  }

  /** « Failed to fetch » et consorts : la requête n'est jamais partie. */
  function estPanneReseau(err) {
    var texte = String(err && err.message ? err.message : err);
    return /failed to fetch|networkerror|load failed|network request failed/i.test(texte);
  }

  function messageErreur(err, pendantUnCoup) {
    if (!estPanneReseau(err)) return err.message;
    return pendantUnCoup
      ? "Connexion perdue : ton coup n'est pas parti, retouche la carte."
      : 'Connexion interrompue, reprise dès que le réseau revient…';
  }

  function poster(chemin, corps) {
    if (enCours) return Promise.resolve(null);
    enCours = true;
    corps = corps || {};
    corps.jeton = JETON;
    if (CODE) corps.code = CODE;
    return fetch(chemin, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(corps)
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data && data.erreur ? data.erreur : 'Erreur ' + r.status);
        return data;
      });
    }).then(function (data) {
      enCours = false;
      dire('');
      return data;
    }).catch(function (err) {
      enCours = false;
      dire(messageErreur(err, true), true);
      return null;
    });
  }

  /* -------------------------------------------------------------- réseau */

  function rafraichir(forcer) {
    if (!CODE) return Promise.resolve();
    var url = '/api/etat?code=' + encodeURIComponent(CODE) + '&jeton=' + encodeURIComponent(JETON)
      + '&v=' + (forcer || !ETAT ? 0 : ETAT.version);
    return fetch(url).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data && data.erreur ? data.erreur : 'Erreur ' + r.status);
        return data;
      });
    }).then(function (data) {
      if (echecs > 0) { echecs = 0; dire(''); }
      if (data.inchange) return;
      ETAT = data;
      if (ETAT.moi === null) { quitterLocal(); return; }
      rendre();
    }).catch(function (err) {
      echecs++;
      // Un téléphone qui se réveille rate souvent une requête : on laisse passer.
      if (echecs >= 2 || !estPanneReseau(err)) dire(messageErreur(err, false), true);
    });
  }

  function agir(action, index) {
    return poster('/api/action', { action: action, index: index }).then(function (data) {
      if (!data) return;
      ETAT = data;
      MODE = 'echanger';
      rendre();
    });
  }

  function demarrerBoucle() {
    if (minuteur) clearInterval(minuteur);
    minuteur = setInterval(function () { rafraichir(false); }, 1500);
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && CODE) rafraichir(true);
  });
  window.addEventListener('online', function () {
    if (CODE) rafraichir(true);
  });

  function quitterLocal() {
    CODE = null;
    ETAT = null;
    localStorage.removeItem('skyjo:code');
    if (minuteur) { clearInterval(minuteur); minuteur = null; }
    rendre();
  }

  /* ------------------------------------------------------------- accueil */

  function champNom(id) {
    var bloc = el('div');
    var select = el('select');
    select.id = id;
    var vide = el('option', null, '— choisir —');
    vide.value = '';
    select.appendChild(vide);
    JOUEURS.forEach(function (nom) {
      var o = el('option', null, nom);
      o.value = nom;
      select.appendChild(o);
    });
    var nouveau = el('option', null, '+ Nouveau joueur…');
    nouveau.value = '__nouveau__';
    select.appendChild(nouveau);

    var champ = el('input');
    champ.type = 'text';
    champ.maxLength = 20;
    champ.placeholder = 'Ton nom';
    champ.hidden = true;
    champ.id = id + '-texte';

    if (MON_NOM && JOUEURS.indexOf(MON_NOM) !== -1) {
      select.value = MON_NOM;
    } else if (MON_NOM) {
      select.value = '__nouveau__';
      champ.hidden = false;
      champ.value = MON_NOM;
    }

    select.addEventListener('change', function () {
      champ.hidden = select.value !== '__nouveau__';
      if (!champ.hidden) champ.focus();
    });

    bloc.appendChild(select);
    bloc.appendChild(champ);
    return bloc;
  }

  function lireNom(id) {
    var select = document.getElementById(id);
    var champ = document.getElementById(id + '-texte');
    var nom = select.value === '__nouveau__' ? champ.value.trim() : select.value;
    return nom;
  }

  function ecranAccueil() {
    var vue = document.createDocumentFragment();
    vue.appendChild(el('h1', null, 'Skyjo en ligne'));
    vue.appendChild(el('div', 'subtitle', 'Une salle, un code, chacun sur son téléphone'));
    var statut = el('div', 'statut' + (ERREUR ? ' erreur' : ''), STATUT);
    statut.id = 'statut';
    vue.appendChild(statut);

    var rejoindre = el('div', 'card');
    rejoindre.appendChild(el('h2', null, 'Rejoindre une partie'));
    rejoindre.appendChild(el('label', null, 'Code de la salle'));
    var champCode = el('input');
    champCode.id = 'code';
    champCode.maxLength = 4;
    champCode.placeholder = 'ABCD';
    champCode.style.textTransform = 'uppercase';
    champCode.style.letterSpacing = '4px';
    rejoindre.appendChild(champCode);
    rejoindre.appendChild(el('label', null, 'Ton nom'));
    rejoindre.appendChild(champNom('nom-rejoindre'));
    var btnRejoindre = el('button', 'primary', 'Rejoindre');
    btnRejoindre.addEventListener('click', function () {
      var code = champCode.value.trim().toUpperCase();
      var nom = lireNom('nom-rejoindre');
      if (!code) { dire('Entre le code de la salle.', true); return; }
      if (!nom) { dire('Choisis ton nom.', true); return; }
      CODE = code;
      poster('/api/rejoindre', { nom: nom }).then(function (data) {
        if (!data) { CODE = null; return; }
        retenirNom(nom);
        ETAT = data;
        localStorage.setItem('skyjo:code', CODE);
        demarrerBoucle();
        rendre();
      });
    });
    rejoindre.appendChild(btnRejoindre);
    vue.appendChild(rejoindre);

    var creer = el('div', 'card');
    creer.appendChild(el('h2', null, 'Créer une salle'));
    creer.appendChild(el('label', null, 'Ton nom'));
    creer.appendChild(champNom('nom-creer'));
    creer.appendChild(el('label', null, 'Partie terminée à'));
    var champLimite = el('input');
    champLimite.type = 'number';
    champLimite.id = 'limite';
    champLimite.value = '100';
    champLimite.min = '10';
    champLimite.max = '1000';
    creer.appendChild(champLimite);
    var btnCreer = el('button', 'primary', 'Créer la salle');
    btnCreer.addEventListener('click', function () {
      var nom = lireNom('nom-creer');
      if (!nom) { dire('Choisis ton nom.', true); return; }
      poster('/api/salle', { nom: nom, limite: parseInt(champLimite.value, 10) }).then(function (data) {
        if (!data) return;
        retenirNom(nom);
        CODE = data.code;
        ETAT = data;
        localStorage.setItem('skyjo:code', CODE);
        demarrerBoucle();
        rendre();
      });
    });
    creer.appendChild(btnCreer);
    vue.appendChild(creer);

    var gestion = el('div', 'card');
    gestion.appendChild(el('h2', null, 'Joueurs enregistrés'));
    var liste = el('div');
    liste.id = 'listeJoueurs';
    gestion.appendChild(liste);
    var ligne = el('div', 'rangee');
    var champJoueur = el('input');
    champJoueur.type = 'text';
    champJoueur.maxLength = 20;
    champJoueur.placeholder = 'Nouveau joueur';
    var btnAjout = el('button', 'ghost', 'Ajouter');
    btnAjout.addEventListener('click', function () {
      var nom = champJoueur.value.trim();
      if (!nom) { champJoueur.focus(); return; }
      champJoueur.value = '';
      poster('/api/joueurs', { nom: nom }).then(function (data) {
        if (!data) return;
        JOUEURS = data.joueurs;
        rendre();
      });
    });
    ligne.appendChild(champJoueur);
    ligne.appendChild(btnAjout);
    gestion.appendChild(ligne);
    vue.appendChild(gestion);

    var flip7 = el('div', 'aide');
    var lienFlip7 = el('a', null, 'Compter les points d\\'une partie de Flip 7');
    lienFlip7.href = '/flip7';
    flip7.appendChild(lienFlip7);
    vue.appendChild(flip7);

    app.textContent = '';
    app.appendChild(vue);
    rendreJoueursConnus();
  }

  function retenirNom(nom) {
    MON_NOM = nom;
    localStorage.setItem('skyjo:nom', nom);
  }

  function rendreJoueursConnus() {
    var zone = document.getElementById('listeJoueurs');
    if (!zone) return;
    zone.textContent = '';
    if (JOUEURS.length === 0) {
      zone.appendChild(el('div', 'empty', 'Aucun joueur enregistré'));
      return;
    }
    var boite = el('div', 'chips');
    JOUEURS.forEach(function (nom) {
      var puce = el('span', 'chip');
      puce.appendChild(el('span', null, nom));
      var croix = el('button', null, '✕');
      croix.type = 'button';
      croix.title = 'Retirer ' + nom;
      croix.addEventListener('click', function () {
        if (!confirm('Retirer ' + nom + ' de la liste ?')) return;
        poster('/api/joueurs/supprimer', { nom: nom }).then(function (data) {
          if (!data) return;
          JOUEURS = data.joueurs;
          rendre();
        });
      });
      puce.appendChild(croix);
      boite.appendChild(puce);
    });
    zone.appendChild(boite);
  }
`;

const JS_TABLE = `
  /* --------------------------------------------------------- salle et jeu */

  function enTete() {
    var bloc = el('div', 'entete');
    bloc.appendChild(el('span', null, 'Salle ' + ETAT.code));
    bloc.appendChild(el('span', null,
      ETAT.manche > 0 ? 'Manche ' + ETAT.manche + ' — fin à ' + ETAT.limite : 'Fin à ' + ETAT.limite));
    return bloc;
  }

  function carteEl(carte, surClic) {
    var bouton = el('button', 'carte');
    bouton.type = 'button';
    if (!carte || carte.etat === 'retiree') {
      bouton.className = 'carte vide';
      bouton.disabled = true;
      return bouton;
    }
    if (carte.etat === 'cachee') {
      bouton.className = 'carte dos';
      bouton.textContent = '?';
    } else {
      bouton.style.background = couleurCarte(carte.v);
      bouton.textContent = String(carte.v);
    }
    if (surClic) {
      bouton.className += ' cliquable';
      bouton.addEventListener('click', surClic);
    } else {
      bouton.disabled = true;
    }
    return bouton;
  }

  function grilleEl(joueur, interactive) {
    var grille = el('div', 'grille');
    joueur.grille.forEach(function (carte, index) {
      var clic = null;
      if (interactive) clic = cliquableGrille(carte, index);
      grille.appendChild(carteEl(carte, clic));
    });
    return grille;
  }

  /** Renvoie l'action à déclencher pour la case, ou null si elle est inerte. */
  function cliquableGrille(carte, index) {
    if (carte.etat === 'retiree') return null;

    if (ETAT.phase === 'revelation') {
      var moi = ETAT.joueurs[ETAT.moi];
      if (moi.pret || carte.etat === 'visible') return null;
      return function () { agir('reveler', index); };
    }

    if (ETAT.phase !== 'jeu' || ETAT.tour !== ETAT.moi || !ETAT.carteEnMain) return null;

    var obligatoire = ETAT.carteEnMain.origine === 'defausse';
    if (obligatoire || MODE === 'echanger') {
      return function () { agir('echanger', index); };
    }
    if (carte.etat === 'visible') return null;
    return function () { agir('defausser', index); };
  }

  function aCarteCachee() {
    return ETAT.joueurs[ETAT.moi].grille.some(function (c) { return c.etat === 'cachee'; });
  }

  function tableEl() {
    var zone = el('div', 'table');

    var pilePioche = el('div', 'pile');
    var monTour = ETAT.phase === 'jeu' && ETAT.tour === ETAT.moi;
    var dos = { etat: 'cachee' };
    pilePioche.appendChild(carteEl(
      ETAT.piocheTaille > 0 ? dos : null,
      monTour && !ETAT.carteEnMain && ETAT.piocheTaille > 0
        ? function () { agir('piocher'); }
        : null
    ));
    pilePioche.appendChild(el('span', 'etiquette', 'Pioche (' + ETAT.piocheTaille + ')'));
    zone.appendChild(pilePioche);

    var pileDefausse = el('div', 'pile');
    var piochee = monTour && ETAT.carteEnMain && ETAT.carteEnMain.origine === 'pioche';
    // Une fois le geste armé, la carte est montrée sur la pile : elle n'est plus en main.
    var jetee = piochee && MODE === 'defausser';
    var jeterIci = piochee && !jetee && aCarteCachee();

    var clicDefausse = null;
    if (monTour && !ETAT.carteEnMain && ETAT.defausse !== null) {
      clicDefausse = function () { agir('prendreDefausse'); };
    } else if (jeterIci) {
      clicDefausse = function () { MODE = 'defausser'; rendre(); };
    }

    var dessus = jetee ? ETAT.carteEnMain.v : ETAT.defausse;
    pileDefausse.appendChild(carteEl(
      dessus === null ? null : { etat: 'visible', v: dessus },
      clicDefausse
    ));
    pileDefausse.appendChild(el('span', 'etiquette' + (jetee ? ' jetee' : ''),
      jetee ? 'Jetée ✓' : (jeterIci ? 'Jeter ici' : 'Défausse')));
    zone.appendChild(pileDefausse);

    if (ETAT.carteEnMain && !jetee) {
      var pileMain = el('div', 'pile');
      var carte = ETAT.carteEnMain.v === null
        ? { etat: 'cachee' }
        : { etat: 'visible', v: ETAT.carteEnMain.v };
      pileMain.appendChild(carteEl(carte, null));
      pileMain.appendChild(el('span', 'etiquette', 'En main'));
      zone.appendChild(pileMain);
    }

    return zone;
  }

  function aideJeter() {
    var bloc = el('div', 'aide');
    bloc.appendChild(el('span', null,
      'Carte jetée. Touche maintenant une carte encore face cachée pour la retourner. '));
    var annuler = el('button', 'lien', 'Reprendre la carte');
    annuler.type = 'button';
    annuler.addEventListener('click', function () { MODE = 'echanger'; rendre(); });
    bloc.appendChild(annuler);
    return bloc;
  }

  function adversairesEl() {
    var zone = el('div', 'adversaires');
    ETAT.joueurs.forEach(function (joueur, index) {
      if (index === ETAT.moi) return;
      var bloc = el('div', 'adv' + (ETAT.tour === index ? ' actif' : ''));
      bloc.style.setProperty('--accent', joueur.couleur);
      var nom = el('div', 'nom');
      nom.appendChild(el('span', null, joueur.nom + (joueur.absent ? ' (parti)' : '')));
      // Même lecture que ma propre ligne : les points retournés, puis le total.
      nom.appendChild(el('span', 'pts', joueur.visible + ' — total ' + joueur.scoreTotal));
      bloc.appendChild(nom);
      bloc.appendChild(grilleEl(joueur, false));
      zone.appendChild(bloc);
    });
    return zone;
  }

  /** Toutes les grilles retournées en fin de manche, la sienne comprise. */
  function grillesFinalesEl() {
    var zone = el('div', 'adversaires');
    ETAT.joueurs.forEach(function (joueur, index) {
      var bloc = el('div', 'adv');
      bloc.style.setProperty('--accent', joueur.couleur);
      var nom = el('div', 'nom');
      nom.appendChild(el('span', null, joueur.nom + (index === ETAT.moi ? ' (toi)' : '')));
      var manche = joueur.scoresManches.length
        ? joueur.scoresManches[joueur.scoresManches.length - 1]
        : 0;
      nom.appendChild(el('span', 'pts', manche + ' pts'));
      bloc.appendChild(nom);
      bloc.appendChild(grilleEl(joueur, false));
      zone.appendChild(bloc);
    });
    return zone;
  }

  function scoresEl() {
    var table = el('table');
    var thead = el('thead');
    var trh = el('tr');
    trh.appendChild(el('th', null, 'Joueur'));
    var manches = ETAT.joueurs[0] ? ETAT.joueurs[0].scoresManches.length : 0;
    for (var m = 0; m < manches; m++) trh.appendChild(el('th', null, 'M' + (m + 1)));
    trh.appendChild(el('th', null, 'Total'));
    thead.appendChild(trh);
    table.appendChild(thead);

    var tbody = el('tbody');
    ETAT.joueurs.forEach(function (joueur) {
      var tr = el('tr');
      var nom = el('td', null, joueur.nom);
      nom.style.textAlign = 'left';
      tr.appendChild(nom);
      joueur.scoresManches.forEach(function (score) {
        tr.appendChild(el('td', null, String(score)));
      });
      var total = el('td', null, String(joueur.scoreTotal));
      total.style.fontWeight = '700';
      tr.appendChild(total);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function journalEl(maximum) {
    var bloc = el('div', 'journal');
    var lignes = maximum ? ETAT.journal.slice(-maximum) : ETAT.journal;
    lignes.forEach(function (ligne) {
      bloc.appendChild(el('div', null, ligne));
    });
    return bloc;
  }

  function boutonQuitter(libelle, question) {
    var bouton = el('button', 'ghost', libelle || 'Quitter la salle');
    bouton.style.marginTop = '12px';
    bouton.style.width = '100%';
    bouton.addEventListener('click', function () {
      if (!confirm(question || 'Quitter la salle ?')) return;
      agir('quitter').then(quitterLocal);
    });
    return bouton;
  }

  function ecranSalle() {
    var vue = document.createDocumentFragment();
    vue.appendChild(el('h1', null, 'Skyjo en ligne'));
    vue.appendChild(el('div', 'subtitle', 'Partage ce code avec les autres joueurs'));

    var bloc = el('div', 'card');
    bloc.appendChild(el('div', 'code-salle', ETAT.code));
    bloc.appendChild(el('div', 'aide', 'Ils entrent ce code sur cette même page.'));
    var statut = el('div', 'statut' + (ERREUR ? ' erreur' : ''), STATUT);
    statut.id = 'statut';
    bloc.appendChild(statut);

    var liste = el('div', 'chips');
    ETAT.joueurs.forEach(function (joueur, index) {
      liste.appendChild(el('span', 'chip', joueur.nom + (index === 0 ? ' (hôte)' : '')));
    });
    bloc.appendChild(liste);

    if (ETAT.moi === 0) {
      var bouton = el('button', 'primary',
        ETAT.joueurs.length < MIN_JOUEURS ? 'En attente d\\'un autre joueur…' : 'Commencer la partie');
      bouton.disabled = ETAT.joueurs.length < MIN_JOUEURS;
      bouton.addEventListener('click', function () { agir('demarrer'); });
      bloc.appendChild(bouton);
    } else {
      bloc.appendChild(el('div', 'aide', 'En attente du lancement par ' + ETAT.joueurs[0].nom + '…'));
    }

    bloc.appendChild(boutonQuitter());
    vue.appendChild(bloc);
    app.textContent = '';
    app.appendChild(vue);
  }

  function ecranJeu() {
    var vue = document.createDocumentFragment();
    vue.appendChild(enTete());

    var moi = ETAT.joueurs[ETAT.moi];
    var bandeau;
    if (ETAT.phase === 'revelation') {
      bandeau = moi.pret
        ? el('div', 'bandeau', 'En attente des autres joueurs…')
        : el('div', 'bandeau moi', 'Retourne deux cartes');
    } else if (ETAT.tour === ETAT.moi) {
      var texte = 'À toi de jouer';
      if (ETAT.carteEnMain) {
        texte = (MODE === 'defausser' && ETAT.carteEnMain.origine === 'pioche')
          ? 'Retourne une carte face cachée'
          : 'Place ou défausse ta carte';
      }
      bandeau = el('div', 'bandeau moi', texte);
    } else {
      bandeau = el('div', 'bandeau', 'Tour de ' + ETAT.joueurs[ETAT.tour].nom);
    }
    vue.appendChild(bandeau);

    var statut = el('div', 'statut' + (ERREUR ? ' erreur' : ''), STATUT);
    statut.id = 'statut';
    vue.appendChild(statut);

    if (ETAT.phase === 'jeu') vue.appendChild(tableEl());

    var maZone = el('div', 'card');
    var titre = el('div', 'nom');
    titre.style.display = 'flex';
    titre.style.justifyContent = 'space-between';
    titre.style.marginBottom = '8px';
    titre.appendChild(el('span', null, moi.nom + ' (toi)'));
    titre.appendChild(el('span', null, 'Visible : ' + moi.visible + ' — total ' + moi.scoreTotal));
    maZone.appendChild(titre);
    maZone.appendChild(grilleEl(moi, true));

    if (ETAT.phase === 'jeu' && ETAT.tour === ETAT.moi && ETAT.carteEnMain) {
      if (ETAT.carteEnMain.origine === 'defausse') {
        maZone.appendChild(el('div', 'aide', 'Touche la case de ta grille à remplacer.'));
      } else if (MODE === 'defausser') {
        maZone.appendChild(aideJeter());
      } else {
        maZone.appendChild(el('div', 'aide',
          aCarteCachee()
            ? 'Touche la case à remplacer, ou la défausse pour jeter cette carte.'
            : 'Touche la case de ta grille à remplacer.'));
      }
    } else if (ETAT.phase === 'jeu' && ETAT.tour === ETAT.moi) {
      maZone.appendChild(el('div', 'aide', 'Prends la carte de la défausse ou pioche.'));
    }
    vue.appendChild(maZone);

    vue.appendChild(adversairesEl());
    vue.appendChild(journalEl(3));
    vue.appendChild(boutonQuitter('Quitter la partie',
      'Quitter la partie en cours ? Les autres joueurs continueront sans toi.'));
    app.textContent = '';
    app.appendChild(vue);
  }

  function ecranScores() {
    var vue = document.createDocumentFragment();
    vue.appendChild(enTete());

    var fini = ETAT.phase === 'fin_partie';
    var texte = fini
      ? (ETAT.gagnants.length > 1
        ? 'Égalité entre ' + ETAT.gagnants.join(' et ')
        : ETAT.gagnants[0] + ' gagne la partie !')
      : 'Fin de la manche ' + ETAT.manche;
    vue.appendChild(el('div', 'bandeau ' + (fini ? 'fin' : 'moi'), texte));

    var statut = el('div', 'statut' + (ERREUR ? ' erreur' : ''), STATUT);
    statut.id = 'statut';
    vue.appendChild(statut);

    vue.appendChild(el('div', 'subtitle', 'Les cartes de la manche ' + ETAT.manche));
    vue.appendChild(grillesFinalesEl());

    var bloc = el('div', 'card');
    bloc.style.marginTop = '14px';
    bloc.appendChild(scoresEl());
    var bouton = el('button', 'primary', fini ? 'Nouvelle partie' : 'Manche suivante');
    bouton.addEventListener('click', function () {
      agir(fini ? 'nouvellePartie' : 'demarrer');
    });
    bloc.appendChild(bouton);
    bloc.appendChild(boutonQuitter());
    vue.appendChild(bloc);

    vue.appendChild(journalEl());
    app.textContent = '';
    app.appendChild(vue);
  }

  /* ------------------------------------------------- taille des grilles */

  // Plancher plus bas côté adversaire : sa grille est informative, la mienne
  // se touche, donc c'est elle qui garde la place quand l'écran est court.
  var CARTE_MIN = 38, CARTE_MAX = 104, ADV_MIN = 26;

  /** Part de la taille de ma carte laissée aux grilles adverses. */
  function ratioAdversaire() {
    // Fin de manche : toutes les grilles sont affichées au même format.
    if (!app.querySelector('.card > .grille')) return 1;
    var nb = ETAT && ETAT.joueurs ? ETAT.joueurs.length : 2;
    if (nb <= 2) return 0.78;
    if (nb === 3) return 0.62;
    return 0.5;
  }

  /** Une longueur calculée du CSS, en pixels : marges et gouttières du moment. */
  function mesure(noeud, propriete) {
    var valeur = parseFloat(getComputedStyle(noeud)[propriete]);
    return isNaN(valeur) ? 0 : valeur;
  }

  /** Ce qu'une grille de quatre cartes peut occuper dans cette largeur. */
  function carteTenantDans(largeur, gouttiere) {
    return Math.floor((largeur - 3 * gouttiere) / 4);
  }

  function appliquerTailles(taille, ratio) {
    var style = document.documentElement.style;
    var adv = Math.round(taille * ratio);
    var zone = app.querySelector('.adversaires');
    if (zone) {
      var bloc = zone.querySelector('.adv');
      var grille = zone.querySelector('.grille');
      var cadre = bloc ? mesure(bloc, 'paddingLeft') + mesure(bloc, 'paddingRight') : 14;
      var gouttiere = grille ? mesure(grille, 'columnGap') : 4;
      var nombre = zone.querySelectorAll('.adv').length || 1;
      var colonnes = Math.max(1, Math.min(nombre, Math.floor(zone.clientWidth / 150)));
      var entre = mesure(zone, 'columnGap') * (colonnes - 1);
      var colonne = (zone.clientWidth - entre) / colonnes;
      adv = Math.min(adv, carteTenantDans(colonne - cadre, gouttiere));
      adv = Math.max(ADV_MIN, adv);
      style.setProperty('--adv-larg', (adv * 4 + 3 * gouttiere + cadre) + 'px');
    }
    adv = Math.max(ADV_MIN, adv);
    style.setProperty('--carte-moi', taille + 'px');
    style.setProperty('--carte-adv', adv + 'px');
    style.setProperty('--carte-pile', Math.max(46, Math.min(86, Math.round(taille * 0.9))) + 'px');
  }

  /** Position, depuis le haut de la page, du bas de la dernière grille. */
  function basDesGrilles() {
    var grilles = app.querySelectorAll('.grille');
    var bas = 0;
    for (var i = 0; i < grilles.length; i++) {
      bas = Math.max(bas, grilles[i].getBoundingClientRect().bottom + window.pageYOffset);
    }
    return bas;
  }

  /** Hauteur des blocs qui rétrécissent avec les cartes : grilles et piles. */
  function hauteurAjustable() {
    var noeuds = app.querySelectorAll('.grille, .table');
    var total = 0;
    for (var i = 0; i < noeuds.length; i++) total += noeuds[i].offsetHeight;
    return total;
  }

  /**
   * Des cartes aussi grandes que la place le permet : on part du maximum que
   * la largeur autorise, puis on rétrécit tant qu'une grille dépasse du bas
   * de l'écran, pour que toutes les cartes restent visibles sans défiler.
   */
  function ajusterGrilles() {
    var maGrille = app.querySelector('.card > .grille');
    if (!app.querySelector('.grille')) return;
    var ratio = ratioAdversaire();
    var depart = maGrille
      ? Math.min(CARTE_MAX, carteTenantDans(maGrille.clientWidth, mesure(maGrille, 'columnGap')))
      : CARTE_MAX;
    if (depart < CARTE_MIN) depart = CARTE_MIN;
    var taille = depart;
    appliquerTailles(taille, ratio);
    for (var i = 0; i < 12 && taille > CARTE_MIN; i++) {
      var debord = basDesGrilles() + 6 - window.innerHeight;
      if (debord <= 0) break;
      var ajustable = hauteurAjustable();
      var suivant = ajustable > 0
        ? Math.floor(taille * (ajustable - debord) / ajustable)
        : taille - 3;
      taille = Math.max(CARTE_MIN, Math.min(suivant, taille - 2));
      appliquerTailles(taille, ratio);
    }
    if (taille <= CARTE_MIN && basDesGrilles() > window.innerHeight) {
      // Trop de joueurs pour la hauteur disponible : rapetisser encore ne
      // ferait pas tenir la table, autant garder des cartes lisibles.
      appliquerTailles(Math.min(depart, 66), ratio);
    }
  }

  function rendre() {
    if (!ETAT || !CODE) { ecranAccueil(); return; }
    if (ETAT.phase === 'attente') { ecranSalle(); return; }
    if (ETAT.phase === 'fin_manche' || ETAT.phase === 'fin_partie') { ecranScores(); ajusterGrilles(); return; }
    ecranJeu();
    ajusterGrilles();
  }

  // La barre du navigateur qui se replie ou l'écran qui pivote rend de la place.
  window.addEventListener('resize', function () { if (ETAT) ajusterGrilles(); });

  /* ------------------------------------------------------------ démarrage */

  var params = new URLSearchParams(location.search);
  var codeUrl = params.get('code') || params.get('salle');
  var codeMemoire = localStorage.getItem('skyjo:code');
  if (codeUrl) {
    CODE = codeUrl.trim().toUpperCase();
    localStorage.setItem('skyjo:code', CODE);
  } else if (codeMemoire) {
    CODE = codeMemoire;
  }

  if (CODE) {
    rafraichir(true).then(function () {
      if (CODE) demarrerBoucle();
      if (!ETAT) rendre();
    });
  } else {
    rendre();
  }
`;

const JS_APP = JS_APP_BASE + JS_TABLE;

/* ---------------------------------------------------------------- flip 7 */

/*
 * Compteur de points pour une partie de Flip 7 jouée avec les vraies cartes,
 * sur /flip7. Rien à voir avec les salles de Skyjo : une feuille de scores par
 * groupe de joueurs (même liste de noms = même partie), rangée dans la table
 * D1 `flip7`, créée au premier passage.
 */

const FLIP7_LIMITE_DEFAUT = 200;
const FLIP7_LIMITE_MIN = 50;
const FLIP7_LIMITE_MAX = 1000;
const FLIP7_MAX_JOUEURS = 12;
const FLIP7_NUMERO_MAX = 12;
const FLIP7_CARTES_FLIP = 7;
const FLIP7_PRIME = 15;
const FLIP7_BONUS = [2, 4, 6, 8, 10];
const FLIP7_PARTIES_LISTEES = 10;

let flip7TablePrete = false;

async function preparerFlip7(env) {
  if (flip7TablePrete) return;
  await bdd(env)
    .prepare('CREATE TABLE IF NOT EXISTS flip7 (cle TEXT PRIMARY KEY, etat TEXT NOT NULL, maj TEXT NOT NULL)')
    .run();
  flip7TablePrete = true;
}

/** Les noms de la partie, dans l'ordre du tour de table. */
function flip7Noms(valeur) {
  const brut = Array.isArray(valeur) ? valeur : String(valeur || '').split(',');
  const noms = brut.map(nomValide).filter(Boolean);
  if (noms.length < MIN_JOUEURS) refuser('Il faut au moins deux joueurs.');
  if (noms.length > FLIP7_MAX_JOUEURS) refuser(FLIP7_MAX_JOUEURS + ' joueurs au maximum.');
  const minuscules = noms.map((n) => n.toLowerCase());
  if (new Set(minuscules).size !== noms.length) refuser('Deux joueurs portent le même nom.');
  return noms;
}

function flip7Cle(noms) {
  return noms.map((n) => n.toLowerCase()).join('|');
}

function flip7Limite(valeur) {
  const limite = parseInt(valeur, 10);
  if (!Number.isFinite(limite)) return FLIP7_LIMITE_DEFAUT;
  return Math.min(FLIP7_LIMITE_MAX, Math.max(FLIP7_LIMITE_MIN, limite));
}

/**
 * Les points d'une main : somme des numéros, doublée par le x2, puis les
 * bonus +2 à +10, puis 15 de prime pour sept numéros différents (le x2 ne
 * touche ni les bonus ni la prime). Un joueur sauté marque zéro.
 */
function scoreFlip7(main) {
  const source = main && typeof main === 'object' ? main : {};
  const numeros = (Array.isArray(source.numeros) ? source.numeros : []).map((n) => parseInt(n, 10));
  if (numeros.some((n) => !Number.isInteger(n) || n < 0 || n > FLIP7_NUMERO_MAX)) {
    refuser('Numéro de carte inconnu.');
  }
  if (new Set(numeros).size !== numeros.length) {
    refuser('Un numéro en double fait sauter le joueur : coche « Sauté ».');
  }
  if (numeros.length > FLIP7_CARTES_FLIP) refuser('Sept numéros au plus : la manche s\'arrête au Flip 7.');

  const bonus = (Array.isArray(source.bonus) ? source.bonus : []).map((b) => parseInt(b, 10));
  if (bonus.some((b) => !FLIP7_BONUS.includes(b)) || new Set(bonus).size !== bonus.length) {
    refuser('Carte bonus inconnue.');
  }

  const detail = {
    numeros: numeros.sort((a, b) => a - b),
    x2: !!source.x2,
    bonus: bonus.sort((a, b) => a - b),
    saute: !!source.saute,
    flip7: numeros.length === FLIP7_CARTES_FLIP,
    score: 0,
  };
  if (detail.saute) {
    detail.flip7 = false;
    return detail;
  }

  let score = numeros.reduce((s, n) => s + n, 0);
  if (detail.x2) score *= 2;
  score += bonus.reduce((s, b) => s + b, 0);
  if (detail.flip7) score += FLIP7_PRIME;
  detail.score = score;
  return detail;
}

function nouvelleFeuille(noms, limite) {
  return { joueurs: noms, limite, manches: [], creee: new Date().toISOString() };
}

function totauxFlip7(feuille) {
  return feuille.joueurs.map((_, index) =>
    feuille.manches.reduce((somme, manche) => somme + manche[index].score, 0));
}

/**
 * La partie s'arrête à la fin de la manche où quelqu'un atteint la limite ;
 * le plus gros total gagne, et une égalité en tête se départage en rejouant.
 */
function vueFlip7(feuille, enregistree) {
  const totaux = totauxFlip7(feuille);
  const maxi = totaux.length ? Math.max(...totaux) : 0;
  const enTete = feuille.joueurs.filter((_, i) => feuille.manches.length > 0 && totaux[i] === maxi);
  const atteinte = feuille.manches.length > 0 && maxi >= feuille.limite;
  return {
    joueurs: feuille.joueurs,
    limite: feuille.limite,
    manches: feuille.manches,
    totaux,
    enTete,
    gagnant: atteinte && enTete.length === 1 ? enTete[0] : null,
    egalite: atteinte && enTete.length > 1,
    enregistree,
  };
}

async function lireFeuille(env, cle) {
  const ligne = await bdd(env).prepare('SELECT etat FROM flip7 WHERE cle = ?').bind(cle).first();
  if (!ligne) return null;
  try {
    return JSON.parse(ligne.etat);
  } catch (err) {
    return null;
  }
}

async function ecrireFeuille(env, feuille) {
  await bdd(env)
    .prepare('INSERT OR REPLACE INTO flip7 (cle, etat, maj) VALUES (?, ?, ?)')
    .bind(flip7Cle(feuille.joueurs), JSON.stringify(feuille), new Date().toISOString())
    .run();
}

async function partiesFlip7(env) {
  const res = await bdd(env)
    .prepare('SELECT etat, maj FROM flip7 ORDER BY maj DESC LIMIT ?')
    .bind(FLIP7_PARTIES_LISTEES)
    .all();
  const parties = [];
  for (const ligne of res.results || []) {
    try {
      const vue = vueFlip7(JSON.parse(ligne.etat), true);
      parties.push({
        joueurs: vue.joueurs,
        limite: vue.limite,
        manches: vue.manches.length,
        totaux: vue.totaux,
        gagnant: vue.gagnant,
        maj: ligne.maj,
      });
    } catch (err) {
      // Une ligne illisible ne doit pas priver la page des autres.
    }
  }
  return parties;
}

/**
 * Le client envoie le nombre de manches qu'il connaît : si un autre téléphone
 * a validé ou annulé une manche entre-temps, on refuse plutôt que de compter
 * deux fois la même.
 */
function verifierAJour(feuille, connues) {
  const n = parseInt(connues, 10);
  if (Number.isInteger(n) && n !== feuille.manches.length) {
    refuser('La feuille a changé sur un autre téléphone : elle vient d\'être rechargée.');
  }
}

async function routeFlip7(request, env, url, chemin) {
  await preparerFlip7(env);

  if (chemin === '/api/flip7/etat') {
    const noms = flip7Noms(url.searchParams.get('joueurs'));
    const feuille = await lireFeuille(env, flip7Cle(noms));
    if (feuille) return json(vueFlip7(feuille, true));
    return json(vueFlip7(nouvelleFeuille(noms, flip7Limite(url.searchParams.get('limite'))), false));
  }

  if (request.method !== 'POST') return erreur('Méthode non autorisée.', 405);
  const corps = await corpsJson(request);
  const noms = flip7Noms(corps.joueurs);
  const existante = await lireFeuille(env, flip7Cle(noms));

  if (chemin === '/api/flip7/manche') {
    const feuille = existante || nouvelleFeuille(noms, flip7Limite(corps.limite));
    verifierAJour(feuille, corps.n);
    const vue = vueFlip7(feuille, true);
    if (vue.gagnant) refuser('La partie est terminée : lance une nouvelle partie.');
    const mains = Array.isArray(corps.mains) ? corps.mains : [];
    if (mains.length !== noms.length) refuser('Il manque la main d\'un joueur.');
    // Les noms ont pu être saisis avec d'autres majuscules : on garde ceux du jour.
    feuille.joueurs = noms;
    feuille.manches.push(mains.map(scoreFlip7));
    await ajouterJoueursFlip7(env, noms);
    await ecrireFeuille(env, feuille);
    return json(vueFlip7(feuille, true));
  }

  if (chemin === '/api/flip7/annuler') {
    if (!existante || existante.manches.length === 0) refuser('Aucune manche à annuler.');
    verifierAJour(existante, corps.n);
    existante.manches.pop();
    await ecrireFeuille(env, existante);
    return json(vueFlip7(existante, true));
  }

  if (chemin === '/api/flip7/nouvelle') {
    const feuille = nouvelleFeuille(noms, flip7Limite(corps.limite));
    await ecrireFeuille(env, feuille);
    return json(vueFlip7(feuille, true));
  }

  return erreur('Route inconnue.', 404);
}

async function ajouterJoueursFlip7(env, noms) {
  await bdd(env).batch(noms.map((nom) =>
    bdd(env).prepare('INSERT OR IGNORE INTO joueurs (nom) VALUES (?)').bind(nom)));
}

const CSS_FLIP7 = `
  .f7-joueur .tete{display:flex; justify-content:space-between; align-items:baseline;
    gap:8px; margin-bottom:8px; font-weight:600;}
  .f7-joueur .tete .total{color:var(--muted); font-weight:400; font-size:0.8rem;}
  .f7-joueur .tete .score{color:var(--or); font-size:1.25rem; flex:0 0 auto;}
  .f7-numeros{display:grid; grid-template-columns:repeat(7, 1fr); gap:5px;}
  .f7-mods{display:grid; grid-template-columns:repeat(6, 1fr); gap:5px; margin-top:5px;}
  .f7-btn{padding:9px 0; font-size:1rem; background:rgba(255,255,255,0.1); color:var(--panel);
    border-radius:9px;}
  .f7-btn.on{background:var(--or); color:#14213D;}
  .f7-btn.mod{color:#FFB4A2;}
  .f7-btn.mod.on{background:#E76F51; color:#fff;}
  .f7-saute{margin-top:6px; width:100%; padding:8px;}
  .f7-saute.on{background:#E76F51; color:#fff; border-color:#E76F51;}
  .f7-joueur.saute .f7-numeros, .f7-joueur.saute .f7-mods{opacity:0.3;}
  .f7-detail{font-size:0.72rem; color:var(--muted); margin-top:6px; min-height:14px; text-align:center;}
  .defile{overflow-x:auto;}
  td.tete-course{color:var(--or);}
  .f7-partie{display:block; width:100%; text-align:left; background:rgba(255,255,255,0.06);
    color:var(--panel); margin-top:6px; font-weight:400; font-size:0.85rem;}
  .f7-partie .quand{color:var(--muted); font-size:0.72rem; display:block;}
  .ligne-joueur{display:flex; gap:6px; align-items:center; margin-top:6px;}
  .ligne-joueur > span{flex:0 0 22px; color:var(--muted); font-size:0.8rem; text-align:right;}
  .ligne-joueur > div{flex:1;}
`;

const JS_FLIP7 = `
  var app = document.getElementById('app');
  var params = new URLSearchParams(location.search);
  var NOMS = (params.get('joueurs') || '').split(',')
    .map(function (n) { return n.trim(); })
    .filter(Boolean);
  var LIMITE = parseInt(params.get('limite'), 10) || LIMITE_DEFAUT;
  var ETAT = null;
  var MAINS = [];
  var STATUT = '';
  var ERREUR = false;
  var enCours = false;

  function el(balise, classe, texte) {
    var noeud = document.createElement(balise);
    if (classe) noeud.className = classe;
    if (texte !== undefined && texte !== null) noeud.textContent = texte;
    return noeud;
  }

  function dire(texte, estErreur) {
    STATUT = texte || '';
    ERREUR = !!estErreur;
    var zone = document.getElementById('statut');
    if (zone) {
      zone.textContent = STATUT;
      zone.className = 'statut' + (ERREUR ? ' erreur' : '');
    }
  }

  function zoneStatut() {
    var statut = el('div', 'statut' + (ERREUR ? ' erreur' : ''), STATUT);
    statut.id = 'statut';
    return statut;
  }

  function lireJson(r) {
    return r.json().then(function (data) {
      if (!r.ok) throw new Error(data && data.erreur ? data.erreur : 'Erreur ' + r.status);
      return data;
    });
  }

  function poster(chemin, corps) {
    if (enCours) return Promise.resolve(null);
    enCours = true;
    corps.joueurs = NOMS;
    corps.limite = LIMITE;
    return fetch(chemin, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(corps)
    }).then(lireJson).then(function (data) {
      enCours = false;
      dire('');
      return data;
    }).catch(function (err) {
      enCours = false;
      dire(err.message, true);
      // La feuille a pu bouger ailleurs : on reprend la version du serveur.
      return charger().then(function () { return null; });
    });
  }

  function charger() {
    var url = '/api/flip7/etat?joueurs=' + encodeURIComponent(NOMS.join(','))
      + '&limite=' + LIMITE;
    return fetch(url).then(lireJson).then(function (data) {
      recevoir(data);
    }).catch(function (err) {
      dire(err.message, true);
      if (!ETAT) ecranAccueil();
    });
  }

  function mainVide() {
    return { numeros: [], x2: false, bonus: [], saute: false };
  }

  /** Une nouvelle manche sur le serveur vide les mains en cours de saisie. */
  function recevoir(data) {
    var nouvelleManche = !ETAT || ETAT.manches.length !== data.manches.length;
    ETAT = data;
    LIMITE = data.limite;
    if (nouvelleManche || MAINS.length !== data.joueurs.length) {
      MAINS = data.joueurs.map(mainVide);
    }
    rendre();
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && ETAT) charger();
  });

  /* ------------------------------------------------------------- calcul */

  function scoreMain(main) {
    if (main.saute) return 0;
    var score = main.numeros.reduce(function (s, n) { return s + n; }, 0);
    if (main.x2) score *= 2;
    score += main.bonus.reduce(function (s, b) { return s + b; }, 0);
    if (main.numeros.length === CARTES_FLIP) score += PRIME;
    return score;
  }

  function detailMain(main) {
    if (main.saute) return 'Sauté : 0 point cette manche';
    if (!main.numeros.length && !main.bonus.length) return 'Aucune carte';
    var morceaux = [];
    if (main.numeros.length) morceaux.push(main.x2 ? '(' + main.numeros.join('+') + ') × 2' : main.numeros.join(' + '));
    main.bonus.forEach(function (b) { morceaux.push('+' + b); });
    if (main.numeros.length === CARTES_FLIP) morceaux.push('Flip 7 +' + PRIME);
    return morceaux.join('  ');
  }

  function basculer(liste, valeur) {
    var i = liste.indexOf(valeur);
    if (i === -1) liste.push(valeur); else liste.splice(i, 1);
  }

  /* ------------------------------------------------------------ accueil */

  function choixJoueur(defaut) {
    var bloc = el('div');
    var select = el('select');
    var vide = el('option', null, '— choisir —');
    vide.value = '';
    select.appendChild(vide);
    JOUEURS.forEach(function (nom) {
      var o = el('option', null, nom);
      o.value = nom;
      select.appendChild(o);
    });
    var nouveau = el('option', null, '+ Nouveau joueur…');
    nouveau.value = '__nouveau__';
    select.appendChild(nouveau);

    var champ = el('input');
    champ.type = 'text';
    champ.maxLength = 20;
    champ.placeholder = 'Nom du joueur';
    champ.hidden = true;

    if (defaut && JOUEURS.indexOf(defaut) !== -1) {
      select.value = defaut;
    } else if (defaut) {
      select.value = '__nouveau__';
      champ.hidden = false;
      champ.value = defaut;
    }
    select.addEventListener('change', function () {
      champ.hidden = select.value !== '__nouveau__';
      if (!champ.hidden) champ.focus();
    });

    bloc.appendChild(select);
    bloc.appendChild(champ);
    bloc.lire = function () {
      return (select.value === '__nouveau__' ? champ.value : select.value).trim();
    };
    return bloc;
  }

  function lienPartie(noms, limite) {
    return '/flip7?joueurs=' + encodeURIComponent(noms.join(',')) + '&limite=' + limite;
  }

  function ecranAccueil() {
    var precedents = [];
    try { precedents = JSON.parse(localStorage.getItem('flip7:noms') || '[]'); } catch (e) {}
    if (NOMS.length) precedents = NOMS;
    var nombre = Math.max(MIN_JOUEURS, Math.min(MAX_JOUEURS, precedents.length || 3));

    var vue = document.createDocumentFragment();
    vue.appendChild(el('h1', null, 'Flip 7'));
    vue.appendChild(el('div', 'subtitle', 'Compteur de points, avec les vraies cartes'));
    vue.appendChild(zoneStatut());

    var bloc = el('div', 'card');
    bloc.appendChild(el('h2', null, 'Nouvelle partie'));
    bloc.appendChild(el('label', null, 'Nombre de joueurs'));
    var choixNombre = el('select');
    for (var n = MIN_JOUEURS; n <= MAX_JOUEURS; n++) {
      var o = el('option', null, String(n));
      o.value = String(n);
      choixNombre.appendChild(o);
    }
    choixNombre.value = String(nombre);
    bloc.appendChild(choixNombre);

    bloc.appendChild(el('label', null, 'Joueurs, dans l\\'ordre du tour'));
    var lignes = el('div');
    bloc.appendChild(lignes);
    var champs = [];
    function dessinerLignes() {
      var deja = champs.map(function (c) { return c.lire(); });
      lignes.textContent = '';
      champs = [];
      for (var i = 0; i < parseInt(choixNombre.value, 10); i++) {
        var ligne = el('div', 'ligne-joueur');
        ligne.appendChild(el('span', null, String(i + 1)));
        var champ = choixJoueur(deja[i] || precedents[i] || '');
        champs.push(champ);
        ligne.appendChild(champ);
        lignes.appendChild(ligne);
      }
    }
    choixNombre.addEventListener('change', dessinerLignes);
    dessinerLignes();

    bloc.appendChild(el('label', null, 'Partie terminée à'));
    var champLimite = el('input');
    champLimite.type = 'number';
    champLimite.min = String(LIMITE_MIN);
    champLimite.max = String(LIMITE_MAX);
    champLimite.value = String(LIMITE);
    bloc.appendChild(champLimite);

    var go = el('button', 'primary', 'Commencer');
    go.addEventListener('click', function () {
      var noms = champs.map(function (c) { return c.lire(); });
      if (noms.some(function (n) { return !n; })) { dire('Choisis le nom de chaque joueur.', true); return; }
      var minuscules = noms.map(function (n) { return n.toLowerCase(); });
      if (minuscules.some(function (n, i) { return minuscules.indexOf(n) !== i; })) {
        dire('Deux joueurs portent le même nom.', true);
        return;
      }
      var limite = parseInt(champLimite.value, 10) || LIMITE_DEFAUT;
      try { localStorage.setItem('flip7:noms', JSON.stringify(noms)); } catch (e) {}
      location.href = lienPartie(noms, limite);
    });
    bloc.appendChild(go);
    vue.appendChild(bloc);

    if (PARTIES.length) {
      var histo = el('div', 'card');
      histo.appendChild(el('h2', null, 'Dernières parties'));
      PARTIES.forEach(function (partie) {
        var bouton = el('button', 'f7-partie');
        bouton.type = 'button';
        var resume = partie.joueurs.map(function (nom, i) { return nom + ' ' + partie.totaux[i]; }).join(' · ');
        bouton.appendChild(el('span', null, resume));
        var quand = new Date(partie.maj).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
        bouton.appendChild(el('span', 'quand', quand + ' — ' + partie.manches + ' manche'
          + (partie.manches > 1 ? 's' : '')
          + (partie.gagnant ? ' — ' + partie.gagnant + ' a gagné' : ' — en cours')));
        bouton.addEventListener('click', function () {
          location.href = lienPartie(partie.joueurs, partie.limite);
        });
        histo.appendChild(bouton);
      });
      vue.appendChild(histo);
    }

    var retour = el('div', 'aide');
    var lien = el('a', null, 'Jouer à Skyjo en ligne');
    lien.href = '/';
    retour.appendChild(lien);
    vue.appendChild(retour);

    app.textContent = '';
    app.appendChild(vue);
  }

  /* ------------------------------------------------------------- partie */

  function tableauScores() {
    var table = el('table');
    var trh = el('tr');
    trh.appendChild(el('th', null, 'Joueur'));
    ETAT.manches.forEach(function (_, m) { trh.appendChild(el('th', null, 'M' + (m + 1))); });
    trh.appendChild(el('th', null, 'Total'));
    var thead = el('thead');
    thead.appendChild(trh);
    table.appendChild(thead);

    var tbody = el('tbody');
    ETAT.joueurs.forEach(function (nom, i) {
      var tr = el('tr');
      var cellule = el('td', null, nom);
      cellule.style.textAlign = 'left';
      tr.appendChild(cellule);
      ETAT.manches.forEach(function (manche) {
        var main = manche[i];
        var texte = main.saute ? '✕' : String(main.score) + (main.flip7 ? '★' : '');
        tr.appendChild(el('td', null, texte));
      });
      var total = el('td', ETAT.enTete.indexOf(nom) !== -1 ? 'tete-course' : null, String(ETAT.totaux[i]));
      total.style.fontWeight = '700';
      tr.appendChild(total);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    var defile = el('div', 'defile');
    defile.appendChild(table);
    return defile;
  }

  function blocJoueur(nom, i) {
    var main = MAINS[i];
    var bloc = el('div', 'card f7-joueur' + (main.saute ? ' saute' : ''));
    var tete = el('div', 'tete');
    var gauche = el('span', null, nom + ' ');
    gauche.appendChild(el('span', 'total', 'total ' + ETAT.totaux[i]));
    tete.appendChild(gauche);
    tete.appendChild(el('span', 'score', '+' + scoreMain(main)));
    bloc.appendChild(tete);

    var plein = main.numeros.length >= CARTES_FLIP;
    var numeros = el('div', 'f7-numeros');
    for (var n = 0; n <= NUMERO_MAX; n++) {
      (function (valeur) {
        var choisi = main.numeros.indexOf(valeur) !== -1;
        var bouton = el('button', 'f7-btn' + (choisi ? ' on' : ''), String(valeur));
        bouton.type = 'button';
        bouton.disabled = main.saute || (plein && !choisi);
        bouton.addEventListener('click', function () {
          basculer(main.numeros, valeur);
          main.numeros.sort(function (a, b) { return a - b; });
          rendre();
        });
        numeros.appendChild(bouton);
      })(n);
    }
    bloc.appendChild(numeros);

    var mods = el('div', 'f7-mods');
    var x2 = el('button', 'f7-btn mod' + (main.x2 ? ' on' : ''), '×2');
    x2.type = 'button';
    x2.disabled = main.saute;
    x2.addEventListener('click', function () { main.x2 = !main.x2; rendre(); });
    mods.appendChild(x2);
    BONUS.forEach(function (valeur) {
      var choisi = main.bonus.indexOf(valeur) !== -1;
      var bouton = el('button', 'f7-btn mod' + (choisi ? ' on' : ''), '+' + valeur);
      bouton.type = 'button';
      bouton.disabled = main.saute;
      bouton.addEventListener('click', function () {
        basculer(main.bonus, valeur);
        main.bonus.sort(function (a, b) { return a - b; });
        rendre();
      });
      mods.appendChild(bouton);
    });
    bloc.appendChild(mods);

    var saute = el('button', 'ghost f7-saute' + (main.saute ? ' on' : ''),
      main.saute ? 'Sauté (doublon) — 0 point' : 'Sauté sur un doublon ?');
    saute.type = 'button';
    saute.addEventListener('click', function () { main.saute = !main.saute; rendre(); });
    bloc.appendChild(saute);

    bloc.appendChild(el('div', 'f7-detail', detailMain(main)));
    return bloc;
  }

  function ecranPartie() {
    var vue = document.createDocumentFragment();
    var entete = el('div', 'entete');
    entete.appendChild(el('span', null, 'Flip 7'));
    entete.appendChild(el('span', null, 'Manche ' + (ETAT.manches.length + 1) + ' — fin à ' + ETAT.limite));
    vue.appendChild(entete);

    if (ETAT.gagnant) {
      vue.appendChild(el('div', 'bandeau fin', ETAT.gagnant + ' gagne la partie !'));
    } else if (ETAT.egalite) {
      vue.appendChild(el('div', 'bandeau moi',
        'Égalité entre ' + ETAT.enTete.join(' et ') + ' : on rejoue une manche'));
    }
    vue.appendChild(zoneStatut());

    if (ETAT.manches.length) {
      var scores = el('div', 'card');
      scores.appendChild(tableauScores());
      vue.appendChild(scores);
    }

    if (!ETAT.gagnant) {
      vue.appendChild(el('div', 'subtitle', 'Touche les cartes de chacun à la fin de la manche'));
      ETAT.joueurs.forEach(function (nom, i) { vue.appendChild(blocJoueur(nom, i)); });
      var valider = el('button', 'primary', 'Valider la manche ' + (ETAT.manches.length + 1));
      valider.addEventListener('click', function () {
        poster('/api/flip7/manche', { n: ETAT.manches.length, mains: MAINS }).then(function (data) {
          if (data) recevoir(data);
          window.scrollTo(0, 0);
        });
      });
      vue.appendChild(valider);
    }

    var actions = el('div', 'card');
    actions.style.marginTop = '12px';
    if (ETAT.manches.length) {
      var annuler = el('button', 'ghost', 'Annuler la dernière manche');
      annuler.style.width = '100%';
      annuler.addEventListener('click', function () {
        if (!confirm('Annuler la manche ' + ETAT.manches.length + ' ?')) return;
        poster('/api/flip7/annuler', { n: ETAT.manches.length }).then(function (data) {
          if (data) recevoir(data);
        });
      });
      actions.appendChild(annuler);
    }
    var nouvelle = el('button', ETAT.gagnant ? 'primary' : 'ghost', 'Nouvelle partie');
    nouvelle.style.width = '100%';
    nouvelle.style.marginTop = '8px';
    nouvelle.addEventListener('click', function () {
      if (!ETAT.gagnant && ETAT.manches.length && !confirm('Remettre les scores à zéro ?')) return;
      poster('/api/flip7/nouvelle', {}).then(function (data) {
        if (data) recevoir(data);
      });
    });
    actions.appendChild(nouvelle);
    var changer = el('button', 'ghost', 'Changer de joueurs');
    changer.style.width = '100%';
    changer.style.marginTop = '8px';
    changer.addEventListener('click', function () { location.href = '/flip7'; });
    actions.appendChild(changer);
    vue.appendChild(actions);

    var regle = el('div', 'aide',
      'Numéros additionnés, ×2 sur les numéros seulement, puis les bonus, puis +'
      + PRIME + ' pour sept numéros (★). Un doublon fait sauter : 0 point.');
    vue.appendChild(regle);

    app.textContent = '';
    app.appendChild(vue);
  }

  function rendre() {
    if (!ETAT) { ecranAccueil(); return; }
    ecranPartie();
  }

  if (NOMS.length >= MIN_JOUEURS) {
    try { localStorage.setItem('flip7:noms', JSON.stringify(NOMS)); } catch (e) {}
    charger();
  } else {
    ecranAccueil();
  }
`;

function pageFlip7Html(joueursConnus, parties) {
  const constantes = {
    JOUEURS: joueursConnus,
    PARTIES: parties,
    MIN_JOUEURS,
    MAX_JOUEURS: FLIP7_MAX_JOUEURS,
    LIMITE_DEFAUT: FLIP7_LIMITE_DEFAUT,
    LIMITE_MIN: FLIP7_LIMITE_MIN,
    LIMITE_MAX: FLIP7_LIMITE_MAX,
    NUMERO_MAX: FLIP7_NUMERO_MAX,
    CARTES_FLIP: FLIP7_CARTES_FLIP,
    PRIME: FLIP7_PRIME,
    BONUS: FLIP7_BONUS,
  };
  const declarations = Object.entries(constantes)
    .map(([nom, valeur]) => 'var ' + nom + ' = ' + toScriptJson(valeur) + ';')
    .join('');
  return '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + '<title>Flip 7 — points</title><style>' + CSS + CSS_FLIP7 + '</style></head>'
    + '<body><div class="wrap"><div id="app"></div></div>'
    + '<script>' + declarations + JS_FLIP7 + '</script>'
    + '</body></html>';
}

/* ------------------------------------------------------------------ routes */

async function corpsJson(request) {
  try {
    const corps = await request.json();
    return corps && typeof corps === 'object' ? corps : {};
  } catch (err) {
    return {};
  }
}

function jetonValide(valeur) {
  const jeton = String(valeur || '').trim();
  return /^[A-Za-z0-9._-]{8,64}$/.test(jeton) ? jeton : null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const chemin = url.pathname.replace(/\/+$/, '') || '/';

    if (chemin === '/favicon.svg') {
      return new Response(FAVICON, {
        headers: { 'content-type': 'image/svg+xml', 'cache-control': 'public, max-age=86400' },
      });
    }
    if (chemin === '/favicon.ico') return new Response(null, { status: 204 });

    const api = chemin.startsWith('/api/');
    if (api && !bdd(env)) {
      return erreur('Stockage non configuré (binding D1 « DB »).', 500);
    }

    try {
      if (chemin.startsWith('/api/flip7/')) return await routeFlip7(request, env, url, chemin);

      if (chemin === '/flip7') {
        if (!bdd(env)) return erreur('Stockage non configuré (binding D1 « DB »).', 500);
        await preparerFlip7(env);
        const [connus, parties] = await Promise.all([lireJoueurs(env), partiesFlip7(env)]);
        return new Response(pageFlip7Html(connus, parties), {
          headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
        });
      }

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

      if (chemin === '/api/joueurs' && request.method === 'GET') {
        return json({ joueurs: await lireJoueurs(env) });
      }

      if (request.method !== 'POST') {
        if (api) return erreur('Méthode non autorisée.', 405);
      } else {
        const corps = await corpsJson(request);

        if (chemin === '/api/joueurs') {
          const nom = nomValide(corps.nom);
          if (!nom) return erreur('Nom vide ou trop long.');
          return json({ joueurs: await ajouterJoueur(env, nom) });
        }

        if (chemin === '/api/joueurs/supprimer') {
          return json({ joueurs: await supprimerJoueurConnu(env, corps.nom) });
        }

        const jeton = jetonValide(corps.jeton);
        if (api && !jeton) return erreur('Session invalide, recharge la page.');

        if (chemin === '/api/salle') {
          const nom = nomValide(corps.nom);
          if (!nom) return erreur('Choisis ton nom.');
          let limite = parseInt(corps.limite, 10);
          if (!Number.isFinite(limite)) limite = LIMITE_DEFAUT;
          limite = Math.min(LIMITE_MAX, Math.max(LIMITE_MIN, limite));

          await purgerSalles(env);
          const code = await creerSalle(env, limite);
          await ajouterJoueur(env, nom);
          const apres = await modifierSalle(env, code, (salle) => {
            salle.joueurs.push(nouveauJoueur(jeton, nom));
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
            if (existant) {
              existant.nom = nom;
              existant.absent = false;
              return;
            }
            if (salle.phase !== 'attente') {
              refuser('La partie a déjà commencé dans cette salle.');
            }
            if (salle.joueurs.length >= MAX_JOUEURS) {
              refuser('La salle est complète (' + MAX_JOUEURS + ' joueurs).');
            }
            if (salle.joueurs.some((j) => j.nom.toLowerCase() === nom.toLowerCase())) {
              refuser('Ce nom est déjà pris dans la salle.');
            }
            salle.joueurs.push(nouveauJoueur(jeton, nom));
            noter(salle, nom + ' rejoint la salle.');
          });
          return json(vuePour(apres.salle, apres.version, jeton));
        }

        if (chemin === '/api/action') {
          const code = normaliserCode(corps.code);
          if (!code) return erreur('Code de salle invalide.');
          const index = corps.index === undefined || corps.index === null
            ? null
            : parseInt(corps.index, 10);

          const apres = await modifierSalle(env, code, (salle) => {
            appliquerAction(salle, jeton, String(corps.action || ''), index);
          });
          return json(vuePour(apres.salle, apres.version, jeton));
        }
      }

      if (api) return erreur('Route inconnue.', 404);

      if (chemin !== '/') {
        return new Response('Page introuvable', {
          status: 404,
          headers: { 'content-type': 'text/plain; charset=utf-8' },
        });
      }

      const connus = bdd(env) ? await lireJoueurs(env) : [];
      return new Response(pageHtml(connus), {
        headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
      });
    } catch (err) {
      if (err instanceof ErreurJeu) return erreur(err.message, 409);
      console.log('erreur inattendue: ' + (err && err.stack ? err.stack : err));
      return erreur('Erreur interne, réessaie.', 500);
    }
  },
};
