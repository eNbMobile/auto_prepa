<?php

declare(strict_types=1);

/**
 * Page à héberger sur enbmobile.nl pour lancer le workflow GitHub Actions
 * "Contrôle Stocks" depuis un simple lien, sans connexion GitHub.
 *
 * Le jeton GitHub reste côté serveur (config.php) : la personne qui clique
 * le lien n'a besoin que du secret dans l'URL, jamais d'un accès GitHub.
 *
 * Un simple GET (ouverture du lien) affiche seulement une page de
 * confirmation ; le déclenchement réel se fait sur le POST du formulaire.
 * Ça évite qu'un aperçu de lien automatique (mail, messagerie) déclenche le
 * workflow tout seul en préchargeant l'URL.
 */

require __DIR__ . '/config.php'; // définit GH_TOKEN et LINK_SECRET

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

$key = (string) ($_GET['key'] ?? $_POST['key'] ?? '');
if ($key === '' || !hash_equals(LINK_SECRET, $key)) {
    render_page('Accès refusé', 'Lien invalide.', 'error');
    exit;
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
        . '<input type="hidden" name="key" value="' . htmlspecialchars($key) . '">'
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

$ch = curl_init(sprintf(
    'https://api.github.com/repos/%s/%s/actions/workflows/%s/dispatches',
    REPO_OWNER,
    REPO_NAME,
    WORKFLOW_FILE
));
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CUSTOMREQUEST => 'POST',
    CURLOPT_POSTFIELDS => json_encode($payload),
    CURLOPT_HTTPHEADER => [
        'Authorization: Bearer ' . GH_TOKEN,
        'Accept: application/vnd.github+json',
        'X-GitHub-Api-Version: 2022-11-28',
        'User-Agent: enbmobile-trigger',
        'Content-Type: application/json',
    ],
    CURLOPT_TIMEOUT => 15,
]);
$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curlError = curl_error($ch);
curl_close($ch);

if ($httpCode === 204) {
    render_page(
        'Contrôle Stocks lancé ✅',
        'Le workflow a été déclenché sur GitHub Actions. Suis son avancement dans l\'onglet Actions du dépôt.',
        'success'
    );
} else {
    error_log("trigger.php controle_stocks: HTTP $httpCode - $response - $curlError");
    render_page('Erreur', 'Le déclenchement a échoué (code ' . $httpCode . '). Contacte l\'administrateur.', 'error');
}
