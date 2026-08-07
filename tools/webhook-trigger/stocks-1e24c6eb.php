<?php

declare(strict_types=1);

/**
 * Raccourci court vers la page de déclenchement du Contrôle Stocks, pour ne
 * pas exposer l'URL complète (avec le secret en clair) dans un lien partagé.
 *
 * Ce fichier doit être déployé à la racine du site (httpdocs/), à côté du
 * dossier prepa/, pas dedans.
 *
 * Le nom du fichier lui-même fait office de secret (chemin non devinable) :
 * garde-le aussi confidentiel que l'ancien lien complet. Quiconque visite
 * cette URL est redirigé directement vers la page de confirmation du
 * contrôle stocks.
 */

require __DIR__ . '/prepa/config.php'; // définit LINK_SECRET (et GH_TOKEN, inutilisé ici)

$jours = preg_match('/^[1-7]$/', (string) ($_GET['jours'] ?? '')) ? $_GET['jours'] : '1';

header('Location: /prepa/trigger.php?' . http_build_query([
    'key' => LINK_SECRET,
    'jours' => $jours,
]), true, 302);
exit;
