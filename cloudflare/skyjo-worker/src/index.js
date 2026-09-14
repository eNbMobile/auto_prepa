/**
 * Worker "skyjo" — compteur de points Skyjo.
 *
 * Le nombre de joueurs et leurs noms se passent dans l'URL :
 *   /?joueurs=Dylan,Erwan
 *   /?nb=4                      (Joueur 1 … Joueur 4)
 *   /?joueurs=Dylan,Erwan&nb=4  (les noms manquants sont complétés)
 *   /?joueurs=Dylan,Erwan&limite=150
 *
 * Chaque manche saisie est enregistrée automatiquement dans le KV
 * (binding PARTIES) : la partie en cours sous `encours:<slug des joueurs>`
 * et l'archive consultable sous `partie:<date de création>:<id>`.
 */

const LIMITE_DEFAUT = 100;
const MIN_JOUEURS = 2;
const MAX_JOUEURS = 8;
const LIMITE_MIN = 10;
const LIMITE_MAX = 1000;

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

function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

/** Retire les accents et la ponctuation pour construire une clé KV stable. */
function slugify(text) {
  const base = String(text)
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return base || 'joueur';
}

/** Injection sûre d'un objet dans une balise <script>. */
function toScriptJson(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

function formatDateFr(iso) {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      timeZone: 'Europe/Paris',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(iso));
  } catch (err) {
    return String(iso || '');
  }
}

/* ----------------------------------------------------------- paramètres */

/**
 * Lit les paramètres de l'URL.
 * Renvoie null si aucun paramètre de partie n'est fourni (page d'accueil).
 */
function lireParams(url) {
  const p = url.searchParams;
  const brutNoms = p.get('joueurs') || p.get('noms') || p.get('j') || '';
  const brutNb = p.get('nb') || p.get('n') || p.get('nombre') || '';

  if (!brutNoms.trim() && !brutNb.trim()) return null;

  let joueurs = brutNoms
    .split(',')
    .map((s) => s.trim().slice(0, 20))
    .filter(Boolean);

  let nb = parseInt(brutNb, 10);
  if (!Number.isFinite(nb)) nb = joueurs.length;
  nb = Math.min(MAX_JOUEURS, Math.max(MIN_JOUEURS, nb));

  while (joueurs.length < nb) joueurs.push('Joueur ' + (joueurs.length + 1));
  joueurs = joueurs.slice(0, nb);

  // Deux joueurs ne peuvent pas porter exactement le même nom (colonnes illisibles).
  const vus = new Map();
  joueurs = joueurs.map((nom) => {
    const cle = nom.toLowerCase();
    const n = (vus.get(cle) || 0) + 1;
    vus.set(cle, n);
    return n > 1 ? nom + ' (' + n + ')' : nom;
  });

  let limite = parseInt(p.get('limite') || p.get('fin') || p.get('max') || '', 10);
  if (!Number.isFinite(limite)) limite = LIMITE_DEFAUT;
  limite = Math.min(LIMITE_MAX, Math.max(LIMITE_MIN, limite));

  return { joueurs, limite };
}

function cleEnCours(joueurs) {
  return ('encours:' + joueurs.map(slugify).join('_')).slice(0, 400);
}

function cleArchive(partie) {
  return 'partie:' + partie.creee + ':' + partie.id;
}

/* ------------------------------------------------------------ état partie */

function nouvellePartie(joueurs, limite) {
  const maintenant = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    joueurs,
    limite,
    manches: [],
    creee: maintenant,
    maj: maintenant,
  };
}

function totaux(partie) {
  return partie.joueurs.map((_, i) =>
    partie.manches.reduce((s, m) => s + (Number(m[i]) || 0), 0));
}

function resultat(partie) {
  const t = totaux(partie);
  const terminee = partie.manches.length > 0 && t.some((v) => v >= partie.limite);
  let gagnants = [];
  if (terminee) {
    const mini = Math.min(...t);
    gagnants = partie.joueurs.filter((_, i) => t[i] === mini);
  }
  return { totaux: t, terminee, gagnants };
}

function etatPublic(partie) {
  const r = resultat(partie);
  return {
    id: partie.id,
    joueurs: partie.joueurs,
    limite: partie.limite,
    manches: partie.manches,
    creee: partie.creee,
    maj: partie.maj,
    totaux: r.totaux,
    terminee: r.terminee,
    gagnants: r.gagnants,
  };
}

function kv(env) {
  return env && env.PARTIES ? env.PARTIES : null;
}

/** Partie en cours pour ces joueurs, créée à la volée si besoin. */
async function chargerPartie(env, params) {
  const store = kv(env);
  const cle = cleEnCours(params.joueurs);
  let partie = null;

  if (store) {
    const brut = await store.get(cle);
    if (brut) {
      try {
        partie = JSON.parse(brut);
      } catch (err) {
        partie = null;
      }
    }
  }

  if (!partie || !Array.isArray(partie.manches) || !Array.isArray(partie.joueurs)) {
    partie = nouvellePartie(params.joueurs, params.limite);
  } else {
    // Les noms et la limite de l'URL font foi (renommage en cours de partie).
    partie.joueurs = params.joueurs;
    partie.limite = params.limite;
  }
  return partie;
}

/** Sauvegarde la partie en cours + son archive (historique). */
async function sauverPartie(env, params, partie) {
  const store = kv(env);
  if (!store) throw new Error('Stockage KV indisponible (binding PARTIES manquant).');

  partie.maj = new Date().toISOString();
  const brut = JSON.stringify(partie);
  await store.put(cleEnCours(params.joueurs), brut);
  if (partie.manches.length > 0) {
    await store.put(cleArchive(partie), brut);
  }
}

async function listerParties(env, limit = 30) {
  const store = kv(env);
  if (!store) return [];
  const res = await store.list({ prefix: 'partie:', limit: 1000 });
  const cles = res.keys.map((k) => k.name).sort().reverse().slice(0, limit);
  const parties = [];
  for (const nom of cles) {
    const brut = await store.get(nom);
    if (!brut) continue;
    try {
      const partie = JSON.parse(brut);
      parties.push(etatPublic(partie));
    } catch (err) {
      /* entrée illisible : on l'ignore */
    }
  }
  return parties;
}

/* ------------------------------------------------------------------ styles */

const CSS = `
  :root{
    --bg:#14213D; --panel:#FFF8EC; --ink:#14213D; --muted:#9AA5C4;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; min-height:100vh; background:var(--bg);
    background-image: radial-gradient(circle at 20% 10%, rgba(255,255,255,0.05), transparent 40%);
    font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color:var(--panel); padding:24px 16px 60px;
  }
  .wrap{max-width:640px; margin:0 auto;}
  h1{text-align:center; font-size:1.6rem; letter-spacing:0.5px; margin:0 0 4px;}
  .subtitle{text-align:center; color:var(--muted); font-size:0.9rem; margin-bottom:18px;}
  .status{text-align:center; color:var(--muted); font-size:0.75rem; margin-bottom:14px; min-height:14px;}
  .players{display:grid; grid-template-columns:repeat(var(--cols,2), minmax(0,1fr)); gap:12px; margin-bottom:16px;}
  .player{
    background:var(--panel); color:var(--ink); border-radius:16px; padding:14px 10px;
    text-align:center; border-top:6px solid var(--accent);
  }
  .player h2{margin:0 0 6px; font-size:1rem; overflow-wrap:anywhere;}
  .total{font-size:clamp(1.5rem, 8vw, 2.2rem); font-weight:700; line-height:1; margin-bottom:10px; color:var(--accent);}
  input[type=number], input[type=text], select{
    width:100%; padding:8px 6px; border-radius:10px; border:1px solid #ddd;
    font-size:1rem; text-align:center; color:var(--ink); background:#fff;
  }
  button{
    border:none; border-radius:10px; padding:10px 14px; font-size:0.95rem;
    font-weight:600; cursor:pointer;
  }
  button:disabled{opacity:0.5; cursor:default;}
  .primary{background:#FFD166; color:#14213D; width:100%; font-size:1.05rem; margin-bottom:16px;}
  .ghost{background:transparent; border:1px solid var(--muted); color:var(--panel);}
  .history{background:rgba(255,255,255,0.05); border-radius:14px; padding:4px 12px; margin-bottom:18px; overflow-x:auto;}
  table{width:100%; border-collapse:collapse; font-size:0.9rem;}
  th, td{padding:8px 6px; text-align:center; border-bottom:1px solid rgba(255,255,255,0.08); white-space:nowrap;}
  tr:last-child td{border-bottom:none;}
  th{color:var(--muted); font-weight:600;}
  td.round-num, th.round-num{color:var(--muted); text-align:left;}
  .empty{text-align:center; color:var(--muted); padding:16px 0; font-size:0.85rem;}
  .actions{display:flex; justify-content:center; gap:10px; flex-wrap:wrap;}
  .banner{
    text-align:center; background:#FFD166; color:#14213D; padding:12px;
    border-radius:14px; font-weight:700; margin-bottom:16px; display:none;
  }
  .card{background:rgba(255,255,255,0.06); border-radius:14px; padding:16px; margin-bottom:16px;}
  .card label{display:block; font-size:0.8rem; color:var(--muted); margin:10px 0 4px;}
  .links{text-align:center; margin-top:18px; font-size:0.85rem;}
  a{color:#FFD166;}
  .game-row{display:flex; justify-content:space-between; gap:10px; padding:10px 0;
    border-bottom:1px solid rgba(255,255,255,0.08); font-size:0.9rem; align-items:center;}
  .game-row:last-child{border-bottom:none;}
  .tag{font-size:0.7rem; color:var(--muted);}
`;

function page(titre, corps) {
  return '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + '<title>' + escapeHtml(titre) + '</title><style>' + CSS + '</style></head>'
    + '<body><div class="wrap">' + corps + '</div></body></html>';
}

/* ------------------------------------------------------------ page d'accueil */

function pageAccueil(parties) {
  const listeParties = parties.length === 0
    ? '<div class="empty">Aucune partie enregistrée pour l\'instant</div>'
    : parties.slice(0, 8).map((p) => {
      const lien = '/?joueurs=' + encodeURIComponent(p.joueurs.join(',')) + '&limite=' + p.limite;
      const scores = p.joueurs.map((n, i) => escapeHtml(n) + ' ' + p.totaux[i]).join(' · ');
      const etat = p.terminee ? 'terminée' : p.manches.length + ' manche(s)';
      return '<div class="game-row"><span>' + scores + '<br><span class="tag">'
        + escapeHtml(formatDateFr(p.maj)) + ' — ' + etat + '</span></span>'
        + '<a href="' + lien + '">ouvrir</a></div>';
    }).join('');

  const corps = '<h1>Skyjo</h1>'
    + '<div class="subtitle">Compteur de points — une partie par lien</div>'
    + '<div class="card">'
    + '<label for="nb">Nombre de joueurs</label>'
    + '<select id="nb"></select>'
    + '<div id="noms"></div>'
    + '<label for="limite">Partie terminée à</label>'
    + '<input type="number" id="limite" value="100" min="10" max="1000">'
    + '<p></p><button class="primary" id="go">Commencer la partie</button>'
    + '<p class="tag" id="apercu"></p>'
    + '</div>'
    + '<h2 style="font-size:1rem; text-align:center">Parties enregistrées</h2>'
    + '<div class="history">' + listeParties + '</div>'
    + '<div class="links"><a href="/historique">Voir tout l\'historique</a></div>'
    + '<script>' + JS_ACCUEIL + '</script>';

  return page('Skyjo', corps);
}

const JS_ACCUEIL = `
  var MIN = ${MIN_JOUEURS}, MAX = ${MAX_JOUEURS};
  var selNb = document.getElementById('nb');
  var zoneNoms = document.getElementById('noms');
  var champLimite = document.getElementById('limite');
  var apercu = document.getElementById('apercu');

  for (var i = MIN; i <= MAX; i++) {
    var o = document.createElement('option');
    o.value = String(i);
    o.textContent = i + ' joueurs';
    if (i === 2) o.selected = true;
    selNb.appendChild(o);
  }

  function construireChamps() {
    var anciens = [];
    var inputs = zoneNoms.querySelectorAll('input');
    for (var k = 0; k < inputs.length; k++) anciens.push(inputs[k].value);
    zoneNoms.textContent = '';
    var n = parseInt(selNb.value, 10);
    for (var i = 0; i < n; i++) {
      var lab = document.createElement('label');
      lab.textContent = 'Joueur ' + (i + 1);
      var inp = document.createElement('input');
      inp.type = 'text';
      inp.maxLength = 20;
      inp.placeholder = 'Joueur ' + (i + 1);
      inp.value = anciens[i] || '';
      inp.addEventListener('input', majApercu);
      zoneNoms.appendChild(lab);
      zoneNoms.appendChild(inp);
    }
    majApercu();
  }

  function lireNoms() {
    var noms = [];
    var inputs = zoneNoms.querySelectorAll('input');
    for (var k = 0; k < inputs.length; k++) {
      noms.push((inputs[k].value || inputs[k].placeholder).trim());
    }
    return noms;
  }

  function lienPartie() {
    var limite = parseInt(champLimite.value, 10);
    if (!isFinite(limite)) limite = 100;
    return '/?joueurs=' + encodeURIComponent(lireNoms().join(',')) + '&limite=' + limite;
  }

  function majApercu() {
    apercu.textContent = 'Lien de la partie : ' + location.origin + lienPartie();
  }

  selNb.addEventListener('change', construireChamps);
  champLimite.addEventListener('input', majApercu);
  document.getElementById('go').addEventListener('click', function () {
    location.href = lienPartie();
  });
  construireChamps();
`;

/* ---------------------------------------------------------------- page jeu */

function pageJeu(partie) {
  const etat = etatPublic(partie);
  const cartes = partie.joueurs.map((nom, i) =>
    '<div class="player" style="--accent:' + COULEURS[i % COULEURS.length] + '">'
    + '<h2>' + escapeHtml(nom) + '</h2>'
    + '<div class="total" id="tot' + i + '">0</div>'
    + '<input type="number" inputmode="numeric" id="sc' + i + '" placeholder="Pts">'
    + '</div>').join('');

  const n = partie.joueurs.length;
  const colonnes = n <= 3 ? n : (n === 4 ? 2 : (n <= 6 ? 3 : 4));

  const corps = '<h1>Skyjo</h1>'
    + '<div class="subtitle">' + escapeHtml(partie.joueurs.join(' · '))
    + ' — fin à ' + partie.limite + ' points</div>'
    + '<div class="status" id="status"></div>'
    + '<div class="banner" id="banner"></div>'
    + '<div class="players" style="--cols:' + colonnes + '">' + cartes + '</div>'
    + '<button class="primary" id="valider">Valider la manche</button>'
    + '<div class="history" id="history"></div>'
    + '<div class="actions">'
    + '<button class="ghost" id="annuler">Annuler la dernière manche</button>'
    + '<button class="ghost" id="nouvelle">Nouvelle partie</button>'
    + '</div>'
    + '<div class="links"><a href="/historique">Historique des parties</a> · <a href="/">Changer de joueurs</a></div>'
    + '<script>var ETAT = ' + toScriptJson(etat) + ';' + JS_JEU + '</script>';

  return page('Skyjo — ' + partie.joueurs.join(' & '), corps);
}

const JS_JEU = `
  var statusEl = document.getElementById('status');

  function setStatus(texte) { statusEl.textContent = texte || ''; }

  function appeler(chemin, corps) {
    setStatus('Enregistrement…');
    return fetch(chemin + location.search, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(corps || {})
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data && data.erreur ? data.erreur : 'Erreur ' + r.status);
        return data;
      });
    }).then(function (data) {
      ETAT = data;
      render();
      setStatus('Enregistré ✓');
      return data;
    }).catch(function (err) {
      setStatus('Échec de l\\'enregistrement : ' + err.message);
    });
  }

  function render() {
    for (var i = 0; i < ETAT.joueurs.length; i++) {
      document.getElementById('tot' + i).textContent = ETAT.totaux[i];
    }

    var zone = document.getElementById('history');
    zone.textContent = '';
    if (ETAT.manches.length === 0) {
      var vide = document.createElement('div');
      vide.className = 'empty';
      vide.textContent = 'Aucune manche jouée pour l\\'instant';
      zone.appendChild(vide);
    } else {
      var table = document.createElement('table');
      var thead = document.createElement('thead');
      var trh = document.createElement('tr');
      var th0 = document.createElement('th');
      th0.className = 'round-num';
      th0.textContent = 'Manche';
      trh.appendChild(th0);
      for (var j = 0; j < ETAT.joueurs.length; j++) {
        var th = document.createElement('th');
        th.textContent = ETAT.joueurs[j];
        trh.appendChild(th);
      }
      thead.appendChild(trh);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');
      for (var m = 0; m < ETAT.manches.length; m++) {
        var tr = document.createElement('tr');
        var td0 = document.createElement('td');
        td0.className = 'round-num';
        td0.textContent = 'Manche ' + (m + 1);
        tr.appendChild(td0);
        for (var c = 0; c < ETAT.joueurs.length; c++) {
          var td = document.createElement('td');
          td.textContent = ETAT.manches[m][c];
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      zone.appendChild(table);
    }

    var banner = document.getElementById('banner');
    if (ETAT.terminee) {
      banner.style.display = 'block';
      banner.textContent = ETAT.gagnants.length > 1
        ? 'Partie terminée à ' + ETAT.limite + ' points — égalité entre ' + ETAT.gagnants.join(' et ')
        : 'Partie terminée à ' + ETAT.limite + ' points — ' + ETAT.gagnants[0] + ' gagne !';
    } else {
      banner.style.display = 'none';
    }

    document.getElementById('annuler').disabled = ETAT.manches.length === 0;
  }

  function valider() {
    var scores = [];
    for (var i = 0; i < ETAT.joueurs.length; i++) {
      var champ = document.getElementById('sc' + i);
      var valeur = champ.value.trim();
      if (valeur === '' || isNaN(parseInt(valeur, 10))) {
        alert('Entre un score pour ' + ETAT.joueurs[i] + ' avant de valider la manche.');
        champ.focus();
        return;
      }
      scores.push(parseInt(valeur, 10));
    }
    appeler('/api/manche', { scores: scores }).then(function () {
      for (var i = 0; i < ETAT.joueurs.length; i++) {
        document.getElementById('sc' + i).value = '';
      }
      document.getElementById('sc0').focus();
    });
  }

  document.getElementById('valider').addEventListener('click', valider);
  document.getElementById('annuler').addEventListener('click', function () {
    if (ETAT.manches.length === 0) return;
    if (!confirm('Annuler la dernière manche ?')) return;
    appeler('/api/annuler', {});
  });
  document.getElementById('nouvelle').addEventListener('click', function () {
    if (ETAT.manches.length > 0 && !confirm('Commencer une nouvelle partie ? La partie en cours reste dans l\\'historique.')) return;
    appeler('/api/nouvelle', {});
  });

  for (var i = 0; i < ETAT.joueurs.length; i++) {
    document.getElementById('sc' + i).addEventListener('keydown', function (e) {
      if (e.key === 'Enter') valider();
    });
  }

  render();
`;

/* -------------------------------------------------------- page historique */

function pageHistorique(parties) {
  const contenu = parties.length === 0
    ? '<div class="empty">Aucune partie enregistrée</div>'
    : parties.map((p) => {
      const lien = '/?joueurs=' + encodeURIComponent(p.joueurs.join(',')) + '&limite=' + p.limite;
      const lignes = p.joueurs
        .map((n, i) => escapeHtml(n) + ' : <strong>' + p.totaux[i] + '</strong>')
        .join(' · ');
      const verdict = p.terminee
        ? (p.gagnants.length > 1
          ? 'égalité entre ' + escapeHtml(p.gagnants.join(' et '))
          : escapeHtml(p.gagnants[0]) + ' gagne')
        : 'en cours';
      return '<div class="game-row"><span>' + lignes
        + '<br><span class="tag">' + escapeHtml(formatDateFr(p.creee)) + ' — '
        + p.manches.length + ' manche(s) — ' + verdict + '</span></span>'
        + '<a href="' + lien + '">ouvrir</a></div>';
    }).join('');

  const corps = '<h1>Historique</h1>'
    + '<div class="subtitle">Toutes les parties enregistrées</div>'
    + '<div class="history">' + contenu + '</div>'
    + '<div class="links"><a href="/">Retour</a></div>';

  return page('Skyjo — historique', corps);
}

/* ------------------------------------------------------------------ routes */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const chemin = url.pathname.replace(/\/+$/, '') || '/';

    if (chemin === '/favicon.svg') {
      const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        + '<rect width="64" height="64" rx="14" fill="#14213D"/>'
        + '<text x="32" y="45" font-size="38" font-family="system-ui, sans-serif" '
        + 'font-weight="700" text-anchor="middle" fill="#FFD166">S</text></svg>';
      return new Response(svg, {
        headers: { 'content-type': 'image/svg+xml', 'cache-control': 'public, max-age=86400' },
      });
    }

    if (chemin === '/favicon.ico') return new Response(null, { status: 204 });

    if (chemin === '/historique') {
      return htmlResponse(pageHistorique(await listerParties(env, 100)));
    }

    if (chemin === '/api/parties') {
      return json({ parties: await listerParties(env, 100) });
    }

    const apiEcriture = ['/api/manche', '/api/annuler', '/api/nouvelle'];
    if (apiEcriture.includes(chemin)) {
      if (request.method !== 'POST') return json({ erreur: 'Méthode non autorisée.' }, 405);

      const params = lireParams(url);
      if (!params) return json({ erreur: 'Joueurs manquants dans l\'URL.' }, 400);
      if (!kv(env)) {
        return json({ erreur: 'Stockage non configuré (binding KV « PARTIES »).' }, 500);
      }

      let corps = {};
      try {
        corps = await request.json();
      } catch (err) {
        corps = {};
      }

      const partie = await chargerPartie(env, params);

      if (chemin === '/api/manche') {
        const scores = Array.isArray(corps.scores) ? corps.scores : null;
        if (!scores || scores.length !== params.joueurs.length) {
          return json({ erreur: 'Il faut un score par joueur.' }, 400);
        }
        const propres = scores.map((v) => parseInt(v, 10));
        if (propres.some((v) => !Number.isFinite(v))) {
          return json({ erreur: 'Scores invalides.' }, 400);
        }
        partie.manches.push(propres);
        await sauverPartie(env, params, partie);
        return json(etatPublic(partie));
      }

      if (chemin === '/api/annuler') {
        partie.manches.pop();
        if (partie.manches.length === 0) {
          await kv(env).delete(cleArchive(partie));
        }
        await sauverPartie(env, params, partie);
        return json(etatPublic(partie));
      }

      // /api/nouvelle : la partie en cours reste archivée, on repart de zéro.
      const fraiche = nouvellePartie(params.joueurs, params.limite);
      await sauverPartie(env, params, fraiche);
      return json(etatPublic(fraiche));
    }

    if (chemin === '/api/etat') {
      const params = lireParams(url);
      if (!params) return json({ erreur: 'Joueurs manquants dans l\'URL.' }, 400);
      return json(etatPublic(await chargerPartie(env, params)));
    }

    if (chemin !== '/') {
      return htmlResponse(page('Introuvable',
        '<h1>Page introuvable</h1><div class="links"><a href="/">Retour</a></div>'), 404);
    }

    const params = lireParams(url);
    if (!params) {
      return htmlResponse(pageAccueil(await listerParties(env, 8)));
    }
    return htmlResponse(pageJeu(await chargerPartie(env, params)));
  },
};
