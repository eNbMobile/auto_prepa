const REPO_OWNER = 'eNbMobile';
const REPO_NAME = 'auto_prepa';
const WORKFLOW_FILE = 'anticipation_commandes.yml';
const REF = 'main';

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
}

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

function computeDateStr(mode, customDate) {
  if (mode === 'date') {
    const parsed = parseDDMMYYYY(customDate);
    if (!parsed) throw new Error('Date invalide (format attendu JJ/MM/AAAA).');
    return parsed;
  }

  const { y, m, d } = parisYMD(new Date());
  const dateObj = new Date(Date.UTC(y, m - 1, d));
  if (mode === 'demain') dateObj.setUTCDate(dateObj.getUTCDate() + 1);
  else if (mode !== 'jour') throw new Error('Choix invalide.');

  return formatDDMMYYYY(dateObj.getUTCFullYear(), dateObj.getUTCMonth() + 1, dateObj.getUTCDate());
}

function renderPage(title, message, status = 'info') {
  const color = status === 'success' ? '#1a7f37' : status === 'error' ? '#cf222e' : '#1f2328';
  const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<title>${escapeHtml(title)}</title></head>`
    + `<body style="font-family: system-ui, sans-serif; max-width: 480px; margin: 10vh auto; text-align:center; color:${color}">`
    + `<h1>${escapeHtml(title)}</h1><p>${message}</p>`
    + `</body></html>`;
  return new Response(html, {
    status: status === 'error' ? 400 : 200,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

function renderFormPage(mode, dateValue, error) {
  const opt = (value, label) =>
    `<option value="${value}"${mode === value ? ' selected' : ''}>${label}</option>`;
  const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<title>Anticipation Commandes</title></head>`
    + `<body style="font-family: system-ui, sans-serif; max-width: 480px; margin: 10vh auto; text-align:center">`
    + `<h1>Anticipation Commandes</h1>`
    + (error ? `<p style="color:#cf222e">${escapeHtml(error)}</p>` : '')
    + `<form method="post">`
    + `<p><select name="mode" id="mode" style="font-size:1.1em; padding:0.4em" `
    + `onchange="document.getElementById('date-wrap').style.display = this.value === 'date' ? 'block' : 'none'">`
    + opt('jour', 'Commandes du jour')
    + opt('demain', 'Commandes de demain')
    + opt('date', 'Saisir une date…')
    + `</select></p>`
    + `<p id="date-wrap" style="display:${mode === 'date' ? 'block' : 'none'}">`
    + `<input type="text" name="date" placeholder="JJ/MM/AAAA" pattern="\\d{2}/\\d{2}/\\d{4}" `
    + `value="${escapeHtml(dateValue || '')}" style="font-size:1.1em; padding:0.4em">`
    + `</p>`
    + `<button type="submit" style="font-size:1.2em; padding: 0.6em 1.4em; cursor:pointer">Lancer l'anticipation</button>`
    + `</form></body></html>`;
  return new Response(html, {
    status: error ? 400 : 200,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === 'POST') {
      const form = await request.formData();
      const mode = form.get('mode') || 'jour';
      const dateValue = form.get('date') || '';

      let dateStr;
      try {
        dateStr = computeDateStr(mode, dateValue);
      } catch (err) {
        return renderFormPage(mode, dateValue, err.message);
      }

      const ghResponse = await fetch(
        `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${env.GH_TOKEN}`,
            Accept: 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'enbmobile-trigger-worker',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ ref: REF, inputs: { date: dateStr } }),
        }
      );

      if (ghResponse.status === 204) {
        return renderPage(
          'Anticipation lancée ✅',
          `L'anticipation a bien été lancée pour le <strong>${escapeHtml(dateStr)}</strong>.`,
          'success'
        );
      }

      const errorBody = await ghResponse.text();
      console.log(`dispatch failed: HTTP ${ghResponse.status} - ${errorBody}`);
      return renderPage(
        'Erreur',
        `Le déclenchement a échoué (code ${ghResponse.status}). Contacte l'administrateur.`,
        'error'
      );
    }

    return renderFormPage('jour', '', null);
  },
};
