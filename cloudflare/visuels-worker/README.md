# Visuels produits

Servis en fichiers statiques sur `https://visuels-<n>.coopu.workers.dev/<gencod>.png`,
avec n = gencod % 2 (limite gratuite : 20 000 fichiers par worker).

Déploiement : workflow `deploy_visuels.yml` (manuel). Il récupère les images en FTP
sur Plesk (`/httpdocs/mobUDrive/visuels`), les répartit sur les 2 workers et les
déploie. Les dossiers `public/` et `workers/` sont générés et non versionnés.
