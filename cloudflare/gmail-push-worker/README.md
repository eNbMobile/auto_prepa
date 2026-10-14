# Worker « gmailpush » : un run aut_prep par email reçu

Avant : cron-job.org lançait `aut_prep` **toutes les minutes** (≈ 820 runs par
jour, dont l'immense majorité ne trouvaient rien à faire).

Maintenant :

```
Email reçu dans Gmail
   └─▶ Gmail (users.watch, boîte de réception)
         └─▶ Google Cloud Pub/Sub (topic + abonnement « push »)
               └─▶ POST https://gmailpush.<compte>.workers.dev/pubsub?token=…
                     └─▶ workflow_dispatch auto_prepa.yml (force=true, source=gmail)
```

- **Délai** : quelques secondes entre la réception de l'email et le lancement du run.
- **Filet de sécurité** : le worker relance aussi `aut_prep` toutes les 10 minutes
  (cron Cloudflare, `source=filet`). Ça couvre
  les bons déposés à la main dans « Traitement manuel », les km Shopopop à retenter,
  le rattrapage 15h « EN ATTENTE », les alertes d'anticipation en attente, et une
  notification qui se perdrait.
- **Renouvellement** : Gmail coupe les notifications au bout de 7 jours. Le worker
  lance chaque nuit (03h17 UTC) le workflow `gmail_watch.yml`, qui les réactive
  (un schedule GitHub sert de secours).
- **Rafales** : un email génère plusieurs notifications (réception, puis archivage par
  aut_prep). Ce n'est pas un problème : le groupe de concurrence du workflow garde un
  run en cours et un seul en attente.

## Mise en place (une seule fois, environ 15 min)

### 1. Google Cloud : topic Pub/Sub

Utilise **le projet Google Cloud du client OAuth** d'auto_prepa (celui dont le
`client_id` figure dans `GOOGLE_TOKEN_JSON`).

1. <https://console.cloud.google.com/apis/library/pubsub.googleapis.com> → **Activer**.
2. Pub/Sub → **Sujets** → **Créer un sujet** : ID `gmail-auto-prepa`, décocher
   « Ajouter un abonnement par défaut ».
3. Ouvrir le sujet → onglet **Autorisations** → **Ajouter un compte principal** :
   `gmail-api-push@system.gserviceaccount.com`, rôle **Diffuseur Pub/Sub**
   (Pub/Sub Publisher).

Le volume (quelques centaines de messages par jour) reste très loin de la limite gratuite.

### 2. GitHub : jeton secret

1. Génère un jeton aléatoire (par exemple les 40 caractères d'un mot de passe généré).
2. Dépôt → Settings → Secrets and variables → Actions → **New repository secret** :
   `GMAIL_PUSH_TOKEN` = ce jeton.
3. Actions → **Deployer tableau de bord Cloudflare** → **Run workflow** : le job
   `gmailpush` déploie le worker et installe ses secrets (`GH_TOKEN` depuis
   `WF_GH_TOKEN`, `PUBSUB_TOKEN` depuis `GMAIL_PUSH_TOKEN`).
   URL du worker : `https://gmailpush.<compte>.workers.dev` (même sous-domaine que `wf`).

### 3. Google Cloud : abonnement « push »

Pub/Sub → **Abonnements** → **Créer un abonnement** :

- ID : `gmail-auto-prepa-push` ; sujet : `gmail-auto-prepa`
- Type de distribution : **Push**
- Point de terminaison : `https://gmailpush.<compte>.workers.dev/pubsub?token=<GMAIL_PUSH_TOKEN>`
- Conservation des messages : 1 jour ; règle de nouvelle tentative : **intervalle exponentiel**.

### 4. config.json (Drive)

Ajoute la clé :

```json
"gmail_pubsub_topic": "projects/<ID_DU_PROJET>/topics/gmail-auto-prepa"
```

### 5. Activer et vérifier

1. Actions → **Gmail watch** → **Run workflow**. Le log doit afficher
   « Notification Gmail active jusqu'au … ».
2. À la commande suivante, un run `aut_prep` doit apparaître dans la minute, avec
   « Déclenchement : gmail » dans l'étape « Déterminer la fenêtre d'exécution ».
3. **Une fois que c'est vérifié, désactive le job aut_prep sur cron-job.org** : le
   filet de 10 minutes du worker le remplace.

## Retour en arrière

Réactiver le job cron-job.org suffit : aut_prep refonctionne comme avant. Le worker
et la notification Gmail peuvent rester en place, ils ne gênent pas.
