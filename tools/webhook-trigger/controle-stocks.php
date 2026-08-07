<?php

declare(strict_types=1);

/**
 * Page à héberger sur enbmobile.nl pour lancer le workflow GitHub Actions
 * "Contrôle Stocks" depuis un simple lien, sans cron et sans connexion
 * GitHub côté utilisateur. Pas de secret dans l'URL : le lien est public.
 *
 * Un simple GET (ouverture du lien) affiche seulement une page de
 * confirmation ; le déclenchement réel se fait sur le POST du formulaire,
 * pour éviter qu'un aperçu automatique de lien (mail, messagerie) ne
 * déclenche le workflow tout seul en préchargeant l'URL.
 */

require __DIR__ . '/config.php'; // définit GH_TOKEN

const REPO_OWNER = 'eNbMobile';
const REPO_NAME = 'auto_prepa';
const WORKFLOW_FILE = 'controle_stocks.yml';
const REF = 'main';

function render_page(string $title, string $message, string $status = 'info'): void
{
    http_response_code($status === 'error' ? 400 : 200);
    header('Content-Type: text/html; charset=utf-8');
    $color = $status === 'success' ? '#1a7f37' : ($status === 'error' ? '#cf222e' : '#1f2328');
    echo '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        . '<meta name="viewport" content="width=device-width, initial-scale=1">'
        . '<title>' . htmlspecialchars($title) . '</title></head>'
        . '<body style="font-family: system-ui, sans-serif; max-width: 480px; margin: 10vh auto; text-align:center; color:' . $color . '">'
        . '<h1>' . htmlspecialchars($title) . '</h1><p>' . $message . '</p>'
        . '</body></html>';
}

$joursRaw = (string) ($_GET['jours'] ?? $_POST['jours'] ?? '1');
$jours = preg_match('/^[1-7]$/', $joursRaw) ? $joursRaw : '1';
$date = '';
$rawDate = (string) ($_GET['date'] ?? $_POST['date'] ?? '');
if ($rawDate !== '' && preg_match('/^\d{2}\/\d{2}\/\d{4}$/', $rawDate)) {
    $date = $rawDate;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    echo '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        . '<meta name="viewport" content="width=device-width, initial-scale=1">'
        . '<title>Lancer Contrôle Stocks</title></head>'
        . '<body style="font-family: system-ui, sans-serif; max-width: 480px; margin: 10vh auto; text-align:center">'
        . '<h1>Contrôle Stocks</h1>'
        . '<p>Jours cumulés : <strong>' . htmlspecialchars($jours) . '</strong>'
        . ($date !== '' ? ' — Date : <strong>' . htmlspecialchars($date) . '</strong>' : '')
        . '</p>'
        . '<form method="post">'
        . '<input type="hidden" name="jours" value="' . htmlspecialchars($jours) . '">'
        . '<input type="hidden" name="date" value="' . htmlspecialchars($date) . '">'
        . '<button type="submit" style="font-size:1.2em; padding: 0.6em 1.4em; cursor:pointer">Lancer le contrôle</button>'
        . '</form></body></html>';
    exit;
}

$payload = [
    'ref' => REF,
    'inputs' => array_filter(
        ['jours' => $jours, 'date' => $date],
        static fn (string $v): bool => $v !== ''
    ),
];

$url = sprintf(
    'https://api.github.com/repos/%s/%s/actions/workflows/%s/dispatches',
    REPO_OWNER,
    REPO_NAME,
    WORKFLOW_FILE
);

// Pas de dépendance à l'extension cURL (souvent désactivée sur les hébergements
// mutualisés) : on passe par les flux HTTP natifs de PHP.
$context = stream_context_create([
    'http' => [
        'method' => 'POST',
        'header' => implode("\r\n", [
            'Authorization: Bearer ' . GH_TOKEN,
            'Accept: application/vnd.github+json',
            'X-GitHub-Api-Version: 2022-11-28',
            'User-Agent: enbmobile-trigger',
            'Content-Type: application/json',
        ]),
        'content' => json_encode($payload),
        'timeout' => 15,
        'ignore_errors' => true, // pour récupérer le corps/statut même sur 4xx/5xx
    ],
]);

$body = @file_get_contents($url, false, $context);
$httpCode = 0;
if (isset($http_response_header[0]) && preg_match('#HTTP/\S+\s(\d{3})#', $http_response_header[0], $m)) {
    $httpCode = (int) $m[1];
}

if ($httpCode === 204) {
    render_page(
        'Contrôle Stocks lancé ✅',
        'Le contrôle a bien été lancé. Le mail avec le résultat arrivera dans quelques minutes.',
        'success'
    );
} else {
    error_log("controle-stocks.php: HTTP $httpCode - " . ($body === false ? '(échec file_get_contents, allow_url_fopen désactivé ?)' : $body));
    render_page('Erreur', 'Le déclenchement a échoué (code ' . $httpCode . '). Contacte l\'administrateur.', 'error');
}
