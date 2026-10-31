/**
 * Worker "gmailpush" : lance aut_prep dès qu'un email arrive dans la boîte
 * Gmail, au lieu d'un run GitHub Actions toutes les minutes.
 *
 * Chaîne : Gmail (users.watch sur la boîte de réception) → Google Cloud
 * Pub/Sub (abonnement « push ») → POST /pubsub?token=… sur ce worker →
 * workflow_dispatch de auto_prepa.yml (force=true).
 *
 * Anti-doublon (Durable Object « Debounce », une seule instance partagée) :
 * traiter une commande fait lui-même bouger la boîte Gmail (archivage de
 * l'email, pose de labels…), ce qui génère de nouvelles notifications
 * Pub/Sub. Sans garde-fou, chacune déclenchait un run GitHub séparé — jusqu'à
 * 4 runs pour une seule commande, le groupe de concurrence du workflow se
 * contentant de les mettre en file (cancel-in-progress: false) sans les
 * annuler. Le Debounce :
 *  - ignore une notification dont le historyId est déjà couvert par le
 *    dernier historyId connu (écho d'une mutation faite par aut_prep
 *    lui-même, ou redistribution Pub/Sub d'un message déjà traité) ;
 *  - si un run est déjà en cours, mémorise seulement qu'il en faudra un
 *    autre une fois celui-ci terminé (« pending »), au lieu d'en dispatcher
 *    un par notification reçue pendant son exécution ;
 *  - à la fin du run (étape finale de auto_prepa.yml, POST
 *    /termine?token=…), dispatche le run « pending » s'il y en a un et
 *    avance le historyId connu.
 *
 * Garde-fou anti-blocage, à DEUX niveaux (un run qui ne signale jamais sa
 * fin — job planté, annulé — ne doit jamais laisser une commande bloquée
 * indéfiniment) :
 *  - passif : une notification reçue alors que l'état "en cours" a plus de
 *    DELAI_BLOCAGE_MS redémarre un cycle au lieu d'attendre ;
 *  - actif (alarme du Durable Object, posée à chaque démarrage de cycle) :
 *    se déclenche d'elle-même après DELAI_BLOCAGE_MS SANS dépendre de
 *    l'arrivée d'une notification suivante. Sans elle, une commande tombée
 *    pendant un cycle bloqué et mise "pending" restait bloquée pour de bon
 *    si aucun autre email n'arrivait derrière pour forcer une réévaluation
 *    (c'est ce qui s'est produit le 30/10/2026 : plus aucun run automatique
 *    entre 19h21 et 19h47 malgré des commandes tombées).
 *
 * Résultat : un seul run par commande dans le cas général, deux au plus
 * (le run utile + un run de vérification rapide qui ne trouve plus rien à
 * faire) si des échos arrivent pendant que le premier tourne encore.
 *
 * Déclencheurs planifiés (wrangler.toml) : renouvellement quotidien de la
 * surveillance Gmail (gmail_watch.yml). Le filet de sécurité toutes les
 * 10 minutes est désactivé (cron retiré de wrangler.toml) mais reste géré
 * ici s'il est réactivé.
 */
const REPO = 'eNbMobile/auto_prepa';
const REF = 'main';

// Au-delà de ce délai sans /termine, un cycle "en cours" est considéré
// perdu (job planté, annulé...) : on ne reste pas bloqué indéfiniment. Le
// job GitHub a un timeout de 15 min ; on laisse une marge confortable.
const DELAI_BLOCAGE_MS = 20 * 60 * 1000;

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

/**
 * Durable Object : une seule instance (id fixe "unique"), état partagé entre
 * toutes les requêtes /pubsub et /termine, et son alarme. L'exécution d'un
 * Durable Object est sérialisée (une requête/alarme à la fois), ce qui
 * évite toute course entre deux notifications Pub/Sub reçues en même temps.
 */
export class Debounce {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async etat() {
    const [lastHistoryId, inFlight, pending, startedAt] = await Promise.all([
      this.ctx.storage.get('lastHistoryId'),
      this.ctx.storage.get('inFlight'),
      this.ctx.storage.get('pending'),
      this.ctx.storage.get('startedAt'),
    ]);
    return {
      lastHistoryId: lastHistoryId ?? null,
      inFlight: inFlight ?? false,
      pending: pending ?? false,
      startedAt: startedAt ?? 0,
    };
  }

  /** Démarre (ou relance) un cycle "run en cours" et arme le garde-fou actif. */
  async demarrer(now) {
    await this.ctx.storage.put({ inFlight: true, pending: false, startedAt: now });
    await this.ctx.storage.setAlarm(now + DELAI_BLOCAGE_MS);
  }

  /** Termine le cycle courant (plus rien en attente) et désarme le garde-fou. */
  async arreter() {
    await this.ctx.storage.put('inFlight', false);
    await this.ctx.storage.deleteAlarm();
  }

  async fetch(request) {
    const url = new URL(request.url);
    const now = Date.now();
    const e = await this.etat();

    if (url.pathname === '/pubsub') {
      const { historyId } = await request.json();

      if (historyId != null && e.lastHistoryId != null && historyId <= e.lastHistoryId) {
        return Response.json({ action: 'ignore', lastHistoryId: e.lastHistoryId });
      }

      const bloque = e.inFlight && (now - e.startedAt) < DELAI_BLOCAGE_MS;
      if (bloque) {
        await this.ctx.storage.put('pending', true);
        return Response.json({ action: 'attente' });
      }

      await this.demarrer(now);
      return Response.json({ action: 'lancer' });
    }

    if (url.pathname === '/termine') {
      const { historyId } = await request.json().catch(() => ({}));
      if (historyId != null && (e.lastHistoryId == null || historyId > e.lastHistoryId)) {
        await this.ctx.storage.put('lastHistoryId', historyId);
      }
      if (e.pending) {
        await this.demarrer(now);
        return Response.json({ action: 'relancer' });
      }
      await this.arreter();
      return Response.json({ action: 'rien' });
    }

    return new Response('Not found', { status: 404 });
  }

  /**
   * Garde-fou actif : posé par demarrer() pour DELAI_BLOCAGE_MS plus tard.
   * Se déclenche tout seul, sans dépendre d'une notification Pub/Sub
   * suivante — sinon une commande mise "pending" pendant un cycle resté
   * bloqué (job planté, annulé) n'était jamais relancée s'il n'arrivait
   * plus d'email derrière pour forcer une réévaluation de l'état.
   */
  async alarm() {
    const now = Date.now();
    const e = await this.etat();
    if (e.pending) {
      console.log('garde-fou (alarme) : notification en attente jamais traitée → relance automatique');
      await this.demarrer(now);
      await lancer(this.env, 'auto_prepa.yml', {
        force: 'true', source: 'gmail-alarme',
        trace: 'garde-fou anti-blocage (20 min) : relance automatique sans notification',
      });
    } else if (e.inFlight) {
      console.log('garde-fou (alarme) : cycle périmé sans rien en attente → état remis à zéro');
      await this.arreter();
    }
  }
}

function debounce(env) {
  const id = env.DEBOUNCE.idFromName('unique');
  return env.DEBOUNCE.get(id);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!memeJeton(url.searchParams.get('token') || '', env.PUBSUB_TOKEN || '')) {
      return new Response('Forbidden', { status: 403 });
    }

    if (url.pathname === '/pubsub') {
      if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
      let corps;
      try {
        corps = await request.json();
      } catch {
        return new Response('Bad request', { status: 400 });
      }
      if (!corps || !corps.message) return new Response('Bad request', { status: 400 });

      // Trace de chaque notification (logs Cloudflare, privés) : publishTime
      // très antérieur à l'heure de réception = message redistribué par
      // Pub/Sub, pas un nouvel événement Gmail — le historyId (ci-dessous)
      // s'en charge de toute façon via le Debounce.
      let historyId = null;
      try {
        const brut = JSON.parse(atob(corps.message.data || '')).historyId;
        if (brut != null) historyId = Number(brut);
      } catch {}
      const trace = `notification ${corps.message.messageId || corps.message.message_id || '?'} ` +
        `publiée ${corps.message.publishTime || corps.message.publish_time || '?'} ` +
        `historyId ${historyId ?? '?'} tentative ${corps.deliveryAttempt || '?'}`;

      const decision = await (await debounce(env).fetch('https://debounce/pubsub', {
        method: 'POST',
        body: JSON.stringify({ historyId }),
      })).json();

      if (decision.action !== 'lancer') {
        console.log(`${trace} → ${decision.action}`);
        return new Response(null, { status: 204 });
      }

      // trace : heures de publication Pub/Sub et de réception par le worker,
      // affichées par le run pour découper le délai de notification.
      const publie = corps.message.publishTime || corps.message.publish_time || '?';
      const recu = new Date().toISOString();
      const ok = await lancer(env, 'auto_prepa.yml', {
        force: 'true', source: 'gmail',
        trace: `publiée ${publie.slice(11, 23)} | reçue par le worker ${recu.slice(11, 23)}`,
      });
      console.log(`${trace} → ${ok ? 'run lancé' : 'échec du lancement'}`);
      return new Response(null, { status: ok ? 204 : 502 });
    }

    // Appelé par la dernière étape de auto_prepa.yml (if: always()) : libère
    // le cycle "en cours" côté Debounce, et relance immédiatement un run si
    // des notifications sont arrivées pendant celui qui vient de se terminer.
    if (url.pathname === '/termine') {
      if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
      let corps = {};
      try { corps = await request.json(); } catch {}
      const historyId = corps && corps.historyId != null ? Number(corps.historyId) : null;

      const decision = await (await debounce(env).fetch('https://debounce/termine', {
        method: 'POST',
        body: JSON.stringify({ historyId }),
      })).json();

      if (decision.action === 'relancer') {
        const ok = await lancer(env, 'auto_prepa.yml', {
          force: 'true', source: 'gmail-relance',
          trace: 'notification(s) reçue(s) pendant le run précédent',
        });
        console.log(`fin de run (historyId ${historyId ?? '?'}) → relance : ${ok ? 'ok' : 'échec'}`);
        return new Response(null, { status: ok ? 204 : 502 });
      }
      console.log(`fin de run (historyId ${historyId ?? '?'}) → ${decision.action}`);
      return new Response(null, { status: 204 });
    }

    return new Response('Not found', { status: 404 });
  },

  async scheduled(event, env, ctx) {
    if (event.cron === '17 3 * * *') {
      ctx.waitUntil(lancer(env, 'gmail_watch.yml', {}));
    } else {
      // force=true : la fenêtre horaire du workflow suppose un démarrage à la
      // minute près (minute % 5, minute < 3) ; un run du filet démarré avec une
      // minute de retard serait sauté. Un run sans rien à traiter s'arrête de
      // toute façon en quelques secondes.
      ctx.waitUntil(lancer(env, 'auto_prepa.yml', { force: 'true', source: 'filet' }));
    }
  },
};
