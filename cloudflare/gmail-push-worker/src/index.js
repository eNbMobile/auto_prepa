/**
 * Worker "gmailpush" : lance aut_prep dès qu'un email arrive dans la boîte
 * Gmail, au lieu d'un run GitHub Actions toutes les minutes.
 *
 * Chaîne : Gmail (users.watch sur la boîte de réception) → Google Cloud
 * Pub/Sub (abonnement « push ») → POST /pubsub?token=… sur ce worker →
 * workflow_dispatch de auto_prepa.yml (force=true).
 *
 * Plusieurs notifications rapprochées (l'email reçu, puis son archivage par
 * aut_prep lui-même) ne posent pas de problème : le groupe de concurrence du
 * workflow garde un run en cours et un seul en attente, le reste est annulé.
 *
 * Déclencheurs planifiés (wrangler.toml) : filet de sécurité toutes les
 * 10 minutes (sans forcer : la fenêtre horaire du workflow s'applique) et
 * renouvellement quotidien de la surveillance Gmail (gmail_watch.yml).
 */
const REPO = 'eNbMobile/auto_prepa';
const REF = 'main';

async function lancer(env, fichier, inputs) {
  const reponse = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${fichier}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'enbmobile-gmailpush-worker',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: REF, inputs }),
    }
  );
  if (reponse.status === 204) return true;
  console.log(`dispatch ${fichier} : HTTP ${reponse.status} ${await reponse.text()}`);
  return false;
}

/** Comparaison à temps constant (le jeton est le seul contrôle d'accès). */
function memeJeton(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== '/pubsub') return new Response('Not found', { status: 404 });
    if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
    if (!memeJeton(url.searchParams.get('token') || '', env.PUBSUB_TOKEN || '')) {
      return new Response('Forbidden', { status: 403 });
    }
    let corps;
    try {
      corps = await request.json();
    } catch {
      return new Response('Bad request', { status: 400 });
    }
    if (!corps || !corps.message) return new Response('Bad request', { status: 400 });

    // Réponse non-2xx = Pub/Sub retentera plus tard : rien ne se perd si
    // GitHub est momentanément indisponible.
    const ok = await lancer(env, 'auto_prepa.yml', { force: 'true', source: 'gmail' });
    return new Response(null, { status: ok ? 204 : 502 });
  },

  async scheduled(event, env, ctx) {
    if (event.cron === '17 3 * * *') {
      ctx.waitUntil(lancer(env, 'gmail_watch.yml', {}));
    } else {
      ctx.waitUntil(lancer(env, 'auto_prepa.yml', { force: 'false', source: 'filet' }));
    }
  },
};
