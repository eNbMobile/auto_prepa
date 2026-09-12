const REPO_OWNER = 'eNbMobile';
const REPO_NAME = 'auto_prepa';
const REF = 'main';

const ACTIONS_URL = `https://github.com/${REPO_OWNER}/${REPO_NAME}/actions/workflows`;

/* ------------------------------------------------------------------ dates */

/** {y, m, d} de la date du jour à Paris, indépendamment du fuseau du serveur. */
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

function formatDDMMYYYY(y, m, d) {
  return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${y}`;
}

/** Valide un texte "JJ/MM/AAAA" et vérifie qu'il s'agit bien d'une date réelle. */
function parseDDMMYYYY(text) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(text || '').trim());
  if (!m) return null;
  const [, dd, mm, yyyy] = m;
  const check = new Date(Date.UTC(+yyyy, +mm - 1, +dd));
  if (
    check.getUTCFullYear() !== +yyyy ||
    check.getUTCMonth() !== +mm - 1 ||
    check.getUTCDate() !== +dd
  ) {
    return null;
  }
  return `${dd}/${mm}/${yyyy}`;
}

/** Date de Paris décalée de `offset` jours, au format JJ/MM/AAAA. */
function parisDateShifted(offset) {
  const { y, m, d } = parisYMD(new Date());
  const dateObj = new Date(Date.UTC(y, m - 1, d));
  dateObj.setUTCDate(dateObj.getUTCDate() + offset);
  return formatDDMMYYYY(dateObj.getUTCFullYear(), dateObj.getUTCMonth() + 1, dateObj.getUTCDate());
}

const DAY_OFFSETS = {
  avant_hier: -2,
  hier: -1,
  jour: 0,
  demain: 1,
};

/**
 * Traduit un choix de menu en date JJ/MM/AAAA.
 * Renvoie null pour "auto" (on laisse alors le workflow décider lui-même).
 */
function resolveDate(mode, customDate, allowedModes) {
  if (!allowedModes.includes(mode)) throw new Error('Choix de date invalide.');
  if (mode === 'auto') return null;
  if (mode === 'date') {
    const parsed = parseDDMMYYYY(customDate);
    if (!parsed) throw new Error('Date invalide (format attendu JJ/MM/AAAA).');
    return parsed;
  }
  return parisDateShifted(DAY_OFFSETS[mode]);
}

/* -------------------------------------------------------------- workflows */

const WORKFLOWS = {
  controle_stocks: {
    file: 'controle_stocks.yml',
    label: 'Contrôle Stocks',
    buildInputs(params) {
      const jours = /^[1-7]$/.test(String(params.jours || '')) ? String(params.jours) : '1';
      const date = resolveDate(params.mode || 'auto', params.date, [
        'auto',
        'jour',
        'hier',
        'avant_hier',
        'date',
      ]);
      const inputs = { jours };
      if (date) inputs.date = date;
      const detail = date
        ? `${jours} jour(s) cumulé(s), dernier jour de ventes le ${date}`
        : `${jours} jour(s) cumulé(s), dernier jour de ventes automatique`;
      return { inputs, detail };
    },
  },

  anticipation: {
    file: 'anticipation_commandes.yml',
    label: 'Anticipation Commandes',
    buildInputs(params) {
      const date = resolveDate(params.mode || 'jour', params.date, ['jour', 'demain', 'date']);
      return { inputs: { date }, detail: `commandes du ${date}` };
    },
  },

  generer_ventes: {
    file: 'generer_ventes.yml',
    label: 'Générer Ventes',
    buildInputs(params) {
      const date = resolveDate(params.mode || 'jour', params.date, [
        'jour',
        'hier',
        'avant_hier',
        'date',
      ]);
      return { inputs: { date }, detail: `ventes du ${date}` };
    },
  },
};

async function dispatchWorkflow(workflow, inputs, token) {
  const response = await fetch(
    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${workflow.file}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'enbmobile-trigger-worker',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: REF, inputs }),
    }
  );

  if (response.status === 204) return null;

  const errorBody = await response.text();
  console.log(`dispatch ${workflow.file} failed: HTTP ${response.status} - ${errorBody}`);
  return response.status;
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

/* ------------------------------------------------------------------- page */

const PAGE = `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tableau de bord auto_prepa</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f6f7f9;
    --card: #ffffff;
    --border: #d8dde3;
    --text: #1f2328;
    --muted: #5b6672;
    --accent: #1f6feb;
    --ok: #1a7f37;
    --ko: #cf222e;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14171c;
      --card: #1c2027;
      --border: #2c333c;
      --text: #e8eaed;
      --muted: #9aa4b0;
      --accent: #4c8dff;
      --ok: #3fb950;
      --ko: #f85149;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 24px 16px 48px;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  .wrap { max-width: 760px; margin: 0 auto; }
  header { text-align: center; margin-bottom: 28px; }
  h1 { font-size: 1.6rem; margin: 0 0 6px; }
  header p { margin: 0; color: var(--muted); font-size: 0.95rem; }
  .cards { display: grid; gap: 18px; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 18px 16px;
  }
  .card h2 { font-size: 1.15rem; margin: 0 0 4px; }
  .card .hint { margin: 0 0 14px; color: var(--muted); font-size: 0.88rem; }
  .fields { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  label { display: block; font-size: 0.82rem; color: var(--muted); margin-bottom: 4px; }
  select, input[type=text] {
    font: inherit;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    min-width: 190px;
  }
  .field.jours select { min-width: 90px; }
  .date-wrap[hidden] { display: none; }
  button {
    font: inherit;
    font-weight: 600;
    padding: 9px 18px;
    border-radius: 8px;
    border: 0;
    background: var(--accent);
    color: #fff;
    cursor: pointer;
  }
  button:disabled { opacity: 0.55; cursor: progress; }
  .status { margin: 12px 0 0; font-size: 0.9rem; min-height: 1.2em; }
  .status.ok { color: var(--ok); }
  .status.ko { color: var(--ko); }
  .status a { color: inherit; }
  footer { text-align: center; margin-top: 28px; font-size: 0.85rem; }
  footer a { color: var(--muted); }
  @media (max-width: 520px) {
    .fields { flex-direction: column; align-items: stretch; }
    select, input[type=text], button { width: 100%; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Tableau de bord auto_prepa</h1>
    <p>Lance les workflows GitHub Actions sans quitter cette page.</p>
  </header>

  <div class="cards">

    <section class="card">
      <h2>Contrôle Stocks</h2>
      <p class="hint">Télécharge les stocks et envoie le mail de contrôle.</p>
      <form data-workflow="controle_stocks">
        <div class="fields">
          <div class="field jours">
            <label for="cs-jours">Jours cumulés</label>
            <select id="cs-jours" name="jours">
              <option value="1" selected>1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
              <option value="6">6</option>
              <option value="7">7</option>
            </select>
          </div>
          <div class="field">
            <label for="cs-mode">Dernier jour de ventes</label>
            <select id="cs-mode" name="mode" data-date-toggle>
              <option value="auto" selected>Automatique (hier, samedi le lundi)</option>
              <option value="jour">Aujourd'hui</option>
              <option value="hier">Hier</option>
              <option value="avant_hier">Avant-hier</option>
              <option value="date">Saisir une date…</option>
            </select>
          </div>
          <div class="field date-wrap" hidden>
            <label for="cs-date">Date</label>
            <input type="text" id="cs-date" name="date" placeholder="JJ/MM/AAAA"
                   inputmode="numeric" autocomplete="off">
          </div>
          <button type="submit">Lancer le contrôle</button>
        </div>
        <p class="status" role="status"></p>
      </form>
    </section>

    <section class="card">
      <h2>Anticipation Commandes</h2>
      <p class="hint">Récupère, archive et envoie le PDF d'anticipation.</p>
      <form data-workflow="anticipation">
        <div class="fields">
          <div class="field">
            <label for="an-mode">Commandes</label>
            <select id="an-mode" name="mode" data-date-toggle>
              <option value="jour" selected>Du jour</option>
              <option value="demain">De demain</option>
              <option value="date">Saisir une date…</option>
            </select>
          </div>
          <div class="field date-wrap" hidden>
            <label for="an-date">Date</label>
            <input type="text" id="an-date" name="date" placeholder="JJ/MM/AAAA"
                   inputmode="numeric" autocomplete="off">
          </div>
          <button type="submit">Lancer l'anticipation</button>
        </div>
        <p class="status" role="status"></p>
      </form>
    </section>

    <section class="card">
      <h2>Générer Ventes</h2>
      <p class="hint">Génère le fichier des ventes de la journée choisie.</p>
      <form data-workflow="generer_ventes">
        <div class="fields">
          <div class="field">
            <label for="gv-mode">Jour</label>
            <select id="gv-mode" name="mode" data-date-toggle>
              <option value="jour" selected>Aujourd'hui</option>
              <option value="hier">Hier</option>
              <option value="avant_hier">Avant-hier</option>
              <option value="date">Saisir une date…</option>
            </select>
          </div>
          <div class="field date-wrap" hidden>
            <label for="gv-date">Date</label>
            <input type="text" id="gv-date" name="date" placeholder="JJ/MM/AAAA"
                   inputmode="numeric" autocomplete="off">
          </div>
          <button type="submit">Générer les ventes</button>
        </div>
        <p class="status" role="status"></p>
      </form>
    </section>

  </div>

  <footer>
    <a href="https://github.com/${REPO_OWNER}/${REPO_NAME}/actions" target="_blank" rel="noopener">
      Voir tous les runs sur GitHub Actions
    </a>
  </footer>
</div>

<script>
document.querySelectorAll('select[data-date-toggle]').forEach((select) => {
  const wrap = select.closest('form').querySelector('.date-wrap');
  const sync = () => { wrap.hidden = select.value !== 'date'; };
  select.addEventListener('change', sync);
  sync();
});

document.querySelectorAll('form[data-workflow]').forEach((form) => {
  const button = form.querySelector('button');
  const status = form.querySelector('.status');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const params = Object.fromEntries(new FormData(form).entries());
    button.disabled = true;
    status.className = 'status';
    status.textContent = 'Lancement en cours…';

    try {
      const response = await fetch('/dispatch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ workflow: form.dataset.workflow, params }),
      });
      const data = await response.json();
      status.className = 'status ' + (data.ok ? 'ok' : 'ko');
      status.textContent = data.message;
      if (data.ok && data.runsUrl) {
        status.insertAdjacentHTML(
          'beforeend',
          ' <a href="' + data.runsUrl + '" target="_blank" rel="noopener">Voir le run</a>'
        );
      }
    } catch (err) {
      status.className = 'status ko';
      status.textContent = 'Impossible de contacter le serveur. Réessaie.';
    } finally {
      button.disabled = false;
    }
  });
});
</script>
</body>
</html>`;

/* ------------------------------------------------------------------ fetch */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/dispatch') {
      let body;
      try {
        body = await request.json();
      } catch (err) {
        return json({ ok: false, message: 'Requête invalide.' }, 400);
      }

      const workflow = WORKFLOWS[body && body.workflow];
      if (!workflow) {
        return json({ ok: false, message: 'Workflow inconnu.' }, 400);
      }

      let built;
      try {
        built = workflow.buildInputs((body && body.params) || {});
      } catch (err) {
        return json({ ok: false, message: err.message }, 400);
      }

      const failureStatus = await dispatchWorkflow(workflow, built.inputs, env.GH_TOKEN);
      if (failureStatus) {
        return json(
          {
            ok: false,
            message: `Le déclenchement a échoué (code ${failureStatus}). Contacte l'administrateur.`,
          },
          502
        );
      }

      return json({
        ok: true,
        message: `${workflow.label} lancé ✅ — ${built.detail}.`,
        runsUrl: `${ACTIONS_URL}/${workflow.file}`,
      });
    }

    if (url.pathname !== '/') {
      return new Response('Not found', { status: 404 });
    }

    return new Response(PAGE, {
      headers: {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-store',
      },
    });
  },
};
