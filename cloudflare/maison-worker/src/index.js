/**
 * Worker "maison" — télécommande SmartThings perso, en PWA.
 *
 * Remplace l'accès rapide de l'app SmartThings : grosses tuiles pour les
 * appareils favoris, télécommande télé aux boutons redimensionnables, scènes.
 *
 * Le worker sert la page (src/page.html) et fait le relais vers l'API
 * SmartThings : les jetons OAuth restent côté serveur (KV, binding MAISON),
 * le navigateur ne voit jamais ni le client secret ni l'access token.
 *
 * Secrets (wrangler secret put …) :
 *   CLE_ACCES         mot de passe demandé à la première ouverture
 *   ST_CLIENT_ID      identifiants de l'app OAuth SmartThings
 *   ST_CLIENT_SECRET  (créée avec le SmartThings CLI, voir README)
 *
 * Clés KV :
 *   jetons        { access_token, refresh_token, expire_a }
 *   config        réglages de la PWA (favoris, télé, tailles…)
 *   etat:<hex>    state OAuth en cours (expire après 10 min)
 */

import PAGE from './page.html';
import { ICONE_192, ICONE_512, ICONE_MASQUABLE } from './icones.js';

const API = 'https://api.smartthings.com/v1/';
const AUTORISATION = 'https://api.smartthings.com/oauth/authorize';
const JETON = 'https://auth-global.api.smartthings.com/oauth/token';
const SCOPES = 'r:devices:* x:devices:* r:locations:* r:scenes:* x:scenes:*';
const COOKIE = 'maison';
const UN_AN = 365 * 24 * 3600;
// Rafraîchit l'access token un peu avant son expiration réelle.
const MARGE_MS = 10 * 60 * 1000;

/* ---------------------------------------------------------------- helpers */

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

function htmlResponse(body, status = 200, extra = {}) {
  return new Response(body, {
    status,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store',
      ...extra,
    },
  });
}

function hex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function base64VersOctets(b64) {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

/** Valeur du cookie de session : HMAC de la clé d'accès, donc invalidé si on la change. */
async function jetonSession(env) {
  const cle = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(env.CLE_ACCES),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  return hex(await crypto.subtle.sign('HMAC', cle, new TextEncoder().encode('maison-v1')));
}

/** Comparaison à temps constant (évite de deviner le cookie octet par octet). */
function egal(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function lireCookie(request, nom) {
  const brut = request.headers.get('cookie') || '';
  for (const morceau of brut.split(';')) {
    const [k, ...v] = morceau.trim().split('=');
    if (k === nom) return v.join('=');
  }
  return '';
}

async function estConnecte(request, env) {
  if (!env.CLE_ACCES) return false;
  return egal(lireCookie(request, COOKIE), await jetonSession(env));
}

/* ------------------------------------------------------- page de connexion */

function pageConnexion(erreur = '') {
  return `<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#111827">
<link rel="manifest" href="/manifest.webmanifest">
<title>Maison</title>
<style>
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#111827;color:#f3f4f6;
       font:18px system-ui,sans-serif}
  form{width:min(90vw,360px);display:grid;gap:14px}
  h1{margin:0 0 6px;font-size:28px}
  input,button{font:inherit;padding:16px;border-radius:14px;border:1px solid #374151}
  input{background:#1f2937;color:inherit}
  button{background:#38bdf8;color:#0b1220;border:0;font-weight:700}
  p{color:#fca5a5;margin:0}
</style></head><body>
<form method="post" action="/connexion">
  <h1>🏠 Maison</h1>
  <input type="password" name="cle" placeholder="Clé d'accès" autocomplete="current-password" autofocus required>
  ${erreur ? `<p>${erreur}</p>` : ''}
  <button>Entrer</button>
</form></body></html>`;
}

async function connexion(request, env) {
  if (!env.CLE_ACCES) {
    return htmlResponse(pageConnexion('Secret CLE_ACCES non défini sur le worker.'), 500);
  }
  const form = await request.formData();
  const saisie = String(form.get('cle') || '');
  // Petit délai fixe : rend le bourrinage du mot de passe pénible.
  await new Promise((r) => setTimeout(r, 400));
  if (!egal(saisie, env.CLE_ACCES)) return htmlResponse(pageConnexion('Clé incorrecte.'), 401);
  return new Response(null, {
    status: 303,
    headers: {
      location: '/',
      'set-cookie': `${COOKIE}=${await jetonSession(env)}; Path=/; Max-Age=${UN_AN}; HttpOnly; Secure; SameSite=Lax`,
    },
  });
}

/* ------------------------------------------------------------------ OAuth */

function redirectUri(url) {
  return `${url.origin}/oauth/retour`;
}

async function debutOAuth(url, env) {
  if (!env.ST_CLIENT_ID || !env.ST_CLIENT_SECRET) {
    return htmlResponse('<p>Secrets ST_CLIENT_ID / ST_CLIENT_SECRET absents : voir le README.</p>', 500);
  }
  const etat = hex(crypto.getRandomValues(new Uint8Array(16)));
  await env.MAISON.put(`etat:${etat}`, '1', { expirationTtl: 600 });
  const cible = new URL(AUTORISATION);
  cible.searchParams.set('client_id', env.ST_CLIENT_ID);
  cible.searchParams.set('response_type', 'code');
  cible.searchParams.set('redirect_uri', redirectUri(url));
  cible.searchParams.set('scope', SCOPES);
  cible.searchParams.set('state', etat);
  return Response.redirect(cible.toString(), 302);
}

async function appelJeton(env, params) {
  const reponse = await fetch(JETON, {
    method: 'POST',
    headers: {
      authorization: `Basic ${btoa(`${env.ST_CLIENT_ID}:${env.ST_CLIENT_SECRET}`)}`,
      'content-type': 'application/x-www-form-urlencoded',
      accept: 'application/json',
    },
    body: new URLSearchParams({ client_id: env.ST_CLIENT_ID, ...params }),
  });
  const texte = await reponse.text();
  if (!reponse.ok) throw new Error(`SmartThings OAuth ${reponse.status} : ${texte.slice(0, 300)}`);
  const data = JSON.parse(texte);
  const jetons = {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expire_a: Date.now() + (Number(data.expires_in) || 86400) * 1000,
  };
  await env.MAISON.put('jetons', JSON.stringify(jetons));
  return jetons;
}

async function retourOAuth(url, env) {
  const etat = url.searchParams.get('state') || '';
  const code = url.searchParams.get('code') || '';
  if (!etat || !(await env.MAISON.get(`etat:${etat}`))) {
    return htmlResponse('<p>Lien de connexion expiré, <a href="/oauth/debut">recommencer</a>.</p>', 400);
  }
  await env.MAISON.delete(`etat:${etat}`);
  if (!code) {
    return htmlResponse(`<p>Autorisation refusée (${url.searchParams.get('error') || 'sans code'}).
      <a href="/">Retour</a></p>`, 400);
  }
  try {
    await appelJeton(env, { grant_type: 'authorization_code', code, redirect_uri: redirectUri(url) });
  } catch (e) {
    return htmlResponse(`<p>Échec de l'échange du code : ${String(e.message).replace(/</g, '&lt;')}</p>`, 502);
  }
  return Response.redirect(`${url.origin}/`, 302);
}

async function rafraichir(env, jetons) {
  return appelJeton(env, { grant_type: 'refresh_token', refresh_token: jetons.refresh_token });
}

/** Jetons valides, rafraîchis si besoin ; null si SmartThings n'a jamais été relié. */
async function jetonsValides(env, forcer = false) {
  const jetons = await env.MAISON.get('jetons', 'json');
  if (!jetons) return null;
  if (!forcer && jetons.expire_a - MARGE_MS > Date.now()) return jetons;
  return rafraichir(env, jetons);
}

/* ------------------------------------------------------- relais SmartThings */

async function relais(request, env, chemin) {
  if (!['GET', 'POST'].includes(request.method)) return json({ erreur: 'Méthode non autorisée' }, 405);
  if (!/^[A-Za-z0-9/_\-.]+$/.test(chemin) || chemin.includes('..')) {
    return json({ erreur: 'Chemin invalide' }, 400);
  }
  let jetons;
  try {
    jetons = await jetonsValides(env);
  } catch (e) {
    return json({ erreur: 'reconnexion', detail: e.message }, 401);
  }
  if (!jetons) return json({ erreur: 'non_relie' }, 401);

  const corps = request.method === 'POST' ? await request.text() : undefined;
  const cible = API + chemin + new URL(request.url).search;
  const envoyer = (j) => fetch(cible, {
    method: request.method,
    headers: {
      authorization: `Bearer ${j.access_token}`,
      accept: 'application/json',
      ...(corps ? { 'content-type': 'application/json' } : {}),
    },
    body: corps,
  });

  let reponse = await envoyer(jetons);
  if (reponse.status === 401) {
    // Jeton révoqué ou expiré plus tôt que prévu : un seul nouvel essai.
    try {
      reponse = await envoyer(await jetonsValides(env, true));
    } catch (e) {
      return json({ erreur: 'reconnexion', detail: e.message }, 401);
    }
  }
  return new Response(reponse.body, {
    status: reponse.status,
    headers: {
      'content-type': reponse.headers.get('content-type') || 'application/json',
      'cache-control': 'no-store',
    },
  });
}

/* --------------------------------------------------------------- PWA */

const MANIFESTE = {
  name: 'Maison',
  short_name: 'Maison',
  description: 'Accès rapide SmartThings à ma sauce',
  lang: 'fr',
  start_url: '/',
  scope: '/',
  display: 'standalone',
  orientation: 'portrait',
  background_color: '#111827',
  theme_color: '#111827',
  icons: [
    { src: '/icone-192.png', sizes: '192x192', type: 'image/png' },
    { src: '/icone-512.png', sizes: '512x512', type: 'image/png' },
    { src: '/icone-masquable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
  ],
  // Appui long sur l'icône de l'écran d'accueil.
  shortcuts: [
    { name: 'Télécommande', short_name: 'Télé', url: '/#tele', icons: [{ src: '/icone-192.png', sizes: '192x192' }] },
    { name: 'Scènes', url: '/#scenes', icons: [{ src: '/icone-192.png', sizes: '192x192' }] },
  ],
};

// Réseau d'abord, cache en secours : l'app s'ouvre même hors connexion
// (les commandes, elles, ont forcément besoin du réseau).
const SERVICE_WORKER = `
const CACHE = 'maison-v1';
self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/', '/manifest.webmanifest', '/icone-192.png'])).catch(() => {}));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')
      || url.pathname.startsWith('/oauth/')) return;
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && !r.redirected) { const copie = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copie)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then((r) => r || caches.match('/'))));
});
`;

function png(b64) {
  return new Response(base64VersOctets(b64), {
    headers: { 'content-type': 'image/png', 'cache-control': 'public, max-age=604800' },
  });
}

/* ------------------------------------------------------------------ routes */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;

    // Ressources publiques (nécessaires à l'installation de la PWA).
    if (p === '/manifest.webmanifest') {
      return new Response(JSON.stringify(MANIFESTE), {
        headers: { 'content-type': 'application/manifest+json', 'cache-control': 'no-cache' },
      });
    }
    if (p === '/sw.js') {
      return new Response(SERVICE_WORKER, {
        headers: { 'content-type': 'text/javascript; charset=utf-8', 'cache-control': 'no-cache' },
      });
    }
    if (p === '/icone-192.png') return png(ICONE_192);
    if (p === '/icone-512.png') return png(ICONE_512);
    if (p === '/icone-masquable.png') return png(ICONE_MASQUABLE);
    if (p === '/connexion' && request.method === 'POST') return connexion(request, env);

    // Tout le reste exige le cookie de session.
    if (!(await estConnecte(request, env))) {
      if (p.startsWith('/api/')) return json({ erreur: 'session' }, 401);
      return htmlResponse(pageConnexion(), 200);
    }

    if (p === '/' || p === '/index.html') return htmlResponse(PAGE);
    if (p === '/oauth/debut') return debutOAuth(url, env);
    if (p === '/oauth/retour') return retourOAuth(url, env);

    if (p === '/api/etat') {
      const jetons = await env.MAISON.get('jetons', 'json');
      return json({ relie: Boolean(jetons) });
    }
    if (p === '/api/deconnecter' && request.method === 'POST') {
      await env.MAISON.delete('jetons');
      return json({ ok: true });
    }
    if (p === '/api/config') {
      if (request.method === 'GET') return json((await env.MAISON.get('config', 'json')) || {});
      if (request.method === 'PUT') {
        const texte = await request.text();
        if (texte.length > 50000) return json({ erreur: 'Config trop grosse' }, 413);
        try { JSON.parse(texte); } catch { return json({ erreur: 'JSON invalide' }, 400); }
        await env.MAISON.put('config', texte);
        return json({ ok: true });
      }
      return json({ erreur: 'Méthode non autorisée' }, 405);
    }
    if (p.startsWith('/api/st/')) return relais(request, env, p.slice('/api/st/'.length));

    return json({ erreur: 'Introuvable' }, 404);
  },

  // Rafraîchit le jeton chaque nuit : le refresh token SmartThings expire
  // après 30 jours sans usage, ça évite de devoir se reconnecter.
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(jetonsValides(env, true).catch((e) => console.error('Rafraîchissement :', e.message)));
  },
};
