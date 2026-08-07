// Worker Cloudflare qui lance le workflow GitHub Actions "Contrôle Stocks"
// depuis un lien nu, sur une URL du type xxx.workers.dev — donc sans
// référence à enbmobile.nl, même une fois la page chargée (ce n'est pas une
// redirection : le worker sert directement la page et fait l'appel GitHub
// lui-même, il n'y a jamais de "Location:" vers un autre domaine).
//
// Le jeton GitHub est fourni via la variable d'environnement/secret GH_TOKEN
// (à configurer dans Cloudflare, jamais dans ce fichier).
//
// Un simple GET (ouverture du lien) affiche une page de confirmation ; le
// déclenchement réel se fait sur le POST du formulaire, pour éviter qu'un
// aperçu automatique de lien (mail, messagerie) ne déclenche le workflow
// tout seul en préchargeant l'URL.

const REPO_OWNER = 'eNbMobile';
const REPO_NAME = 'auto_prepa';
const WORKFLOW_FILE = 'controle_stocks.yml';
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

function validJours(value) {
  return /^[1-7]$/.test(value) ? value : '1';
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

function renderConfirmPage(jours) {
  const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<title>Lancer Contrôle Stocks</title></head>`
    + `<body style="font-family: system-ui, sans-serif; max-width: 480px; margin: 10vh auto; text-align:center">`
    + `<h1>Contrôle Stocks</h1>`
    + `<p>Jours cumulés : <strong>${escapeHtml(jours)}</strong></p>`
    + `<form method="post">`
    + `<input type="hidden" name="jours" value="${escapeHtml(jours)}">`
    + `<button type="submit" style="font-size:1.2em; padding: 0.6em 1.4em; cursor:pointer">Lancer le contrôle</button>`
    + `</form></body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'POST') {
      const form = await request.formData();
      const jours = validJours(form.get('jours') || '1');

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
          body: JSON.stringify({ ref: REF, inputs: { jours } }),
        }
      );

      if (ghResponse.status === 204) {
        return renderPage(
          'Contrôle Stocks lancé ✅',
          'Le contrôle a bien été lancé. Le mail avec le résultat arrivera dans quelques minutes.',
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

    const jours = validJours(url.searchParams.get('jours') || '1');
    return renderConfirmPage(jours);
  },
};
