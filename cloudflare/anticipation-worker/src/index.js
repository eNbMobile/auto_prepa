/**
 * Worker Cloudflare : déclenche le workflow GitHub Actions "Anticipation Commandes"
 * (anticipation_commandes.yml) sans passer par l'interface GitHub ni par un cron.
 *
 * Page HTML avec un menu déroulant : commandes du jour / de demain / date au choix.
 */

function htmlPage() {
  return `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anticipation commandes</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 480px;
    margin: 3rem auto;
    padding: 0 1.25rem;
    background: #f6f7f9;
    color: #1a1a1a;
  }
  h1 { font-size: 1.35rem; margin-bottom: .25rem; }
  p.sub { color: #666; margin-top: 0; margin-bottom: 1.75rem; font-size: .9rem; }
  form {
    background: #fff;
    border: 1px solid #e2e4e8;
    border-radius: 10px;
    padding: 1.5rem;
  }
  label { display: block; font-weight: 600; margin-bottom: .4rem; font-size: .9rem; }
  select, input[type="date"], input[type="password"] {
    width: 100%;
    padding: .6rem .7rem;
    font-size: 1rem;
    border: 1px solid #ccc;
    border-radius: 6px;
    margin-bottom: 1.1rem;
    box-sizing: border-box;
  }
  #date-wrap, #code-wrap { display: none; }
  button {
    width: 100%;
    padding: .75rem;
    font-size: 1rem;
    font-weight: 600;
    color: #fff;
    background: #2563eb;
    border: none;
    border-radius: 6px;
    cursor: pointer;
  }
  button:disabled { opacity: .6; cursor: not-allowed; }
  #status {
    margin-top: 1.1rem;
    padding: .75rem;
    border-radius: 6px;
    font-size: .9rem;
    display: none;
  }
  #status.ok { display: block; background: #ecfdf3; color: #036b26; border: 1px solid #b7ecc8; }
  #status.err { display: block; background: #fef2f2; color: #9f1c1c; border: 1px solid #f5c2c2; }
  #status a { color: inherit; font-weight: 600; }
  @media (prefers-color-scheme: dark) {
    body { background: #111318; color: #e7e7e7; }
    form { background: #1a1d24; border-color: #2a2e37; }
    p.sub { color: #9aa0aa; }
    select, input[type="date"], input[type="password"] { background: #0f1115; color: #e7e7e7; border-color: #3a3f4a; }
  }
</style>
</head>
<body>
  <h1>Anticipation des commandes</h1>
  <p class="sub">Déclenche le workflow GitHub Actions « Anticipation Commandes » à la demande.</p>

  <form id="f">
    <label for="mode">Commandes à anticiper</label>
    <select id="mode" name="mode">
      <option value="jour">Commandes du jour</option>
      <option value="demain">Commandes de demain</option>
      <option value="custom">Saisir une date…</option>
    </select>

    <div id="date-wrap">
      <label for="date">Date</label>
      <input type="date" id="date" name="date">
    </div>

    <div id="code-wrap">
      <label for="code">Code d'accès</label>
      <input type="password" id="code" name="code" autocomplete="off">
    </div>

    <button type="submit" id="submit-btn">Lancer l'anticipation</button>
  </form>

  <div id="status"></div>

<script>
  const modeSelect = document.getElementById('mode');
  const dateWrap = document.getElementById('date-wrap');
  const dateInput = document.getElementById('date');
  const codeWrap = document.getElementById('code-wrap');
  const form = document.getElementById('f');
  const statusEl = document.getElementById('status');
  const submitBtn = document.getElementById('submit-btn');

  // Affiche le champ code d'accès seulement si le serveur en réclame un.
  fetch('/declencher', { method: 'OPTIONS' })
    .then(r => r.json())
    .then(info => { if (info.codeRequired) codeWrap.style.display = 'block'; })
    .catch(() => {});

  modeSelect.addEventListener('change', () => {
    dateWrap.style.display = modeSelect.value === 'custom' ? 'block' : 'none';
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    statusEl.className = '';
    statusEl.textContent = '';

    if (modeSelect.value === 'custom' && !dateInput.value) {
      statusEl.className = 'err';
      statusEl.textContent = 'Merci de choisir une date.';
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Lancement…';

    try {
      const res = await fetch('/declencher', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: modeSelect.value,
          date: dateInput.value,
          code: document.getElementById('code').value,
        }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        statusEl.className = 'ok';
        statusEl.innerHTML = 'Anticipation lancée pour le <strong>' + data.date +
          '</strong>. <a href="' + data.runsUrl + '" target="_blank" rel="noopener">Voir l\\'avancement sur GitHub</a>';
      } else {
        statusEl.className = 'err';
        statusEl.textContent = data.error || 'Erreur inconnue.';
      }
    } catch (err) {
      statusEl.className = 'err';
      statusEl.textContent = 'Erreur réseau : ' + err.message;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Lancer l'anticipation";
    }
  });
</script>
</body>
</html>`;
}

/** Renvoie {y, m, d} de la date du jour à Paris (indépendant du fuseau du serveur). */
function parisYMD(date) {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Paris',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
  const parts = fmt.formatToParts(date);
  const get = (type) => +parts.find((p) => p.type === type).value;
  return { y: get('year'), m: get('month'), d: get('day') };
}

/** Construit la date "JJ/MM/AAAA" attendue par anticipation_commandes.py, selon le mode choisi. */
function computeDateStr(mode, customDate) {
  if (mode === 'custom') {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(customDate || '');
    if (!m) throw new Error('Date invalide.');
    const [, y, mo, d] = m;
    const check = new Date(Date.UTC(+y, +mo - 1, +d));
    if (
      check.getUTCFullYear() !== +y ||
      check.getUTCMonth() !== +mo - 1 ||
      check.getUTCDate() !== +d
    ) {
      throw new Error('Date invalide.');
    }
    return `${d}/${mo}/${y}`;
  }

  if (mode !== 'jour' && mode !== 'demain') {
    throw new Error('Mode invalide.');
  }

  const { y, m, d } = parisYMD(new Date());
  const dateObj = new Date(Date.UTC(y, m - 1, d));
  if (mode === 'demain') dateObj.setUTCDate(dateObj.getUTCDate() + 1);

  const dd = String(dateObj.getUTCDate()).padStart(2, '0');
  const mm = String(dateObj.getUTCMonth() + 1).padStart(2, '0');
  const yyyy = dateObj.getUTCFullYear();
  return `${dd}/${mm}/${yyyy}`;
}

async function dispatchWorkflow(env, dateStr) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'anticipation-worker',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify({
      ref: env.GITHUB_REF,
      inputs: { date: dateStr },
    }),
  });

  if (res.status !== 204) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.message || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`GitHub a refusé le déclenchement (${res.status}) : ${detail}`);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/' && request.method === 'GET') {
      return new Response(htmlPage(), {
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    if (url.pathname === '/declencher' && request.method === 'OPTIONS') {
      return new Response(JSON.stringify({ codeRequired: !!env.ACCESS_CODE }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname === '/declencher' && request.method === 'POST') {
      try {
        const body = await request.json();

        if (env.ACCESS_CODE && body.code !== env.ACCESS_CODE) {
          return new Response(JSON.stringify({ ok: false, error: "Code d'accès incorrect." }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        const dateStr = computeDateStr(body.mode, body.date);
        await dispatchWorkflow(env, dateStr);

        const runsUrl = `https://github.com/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}`;
        return new Response(JSON.stringify({ ok: true, date: dateStr, runsUrl }), {
          headers: { 'Content-Type': 'application/json' },
        });
      } catch (err) {
        return new Response(JSON.stringify({ ok: false, error: err.message }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    }

    return new Response('Not found', { status: 404 });
  },
};
