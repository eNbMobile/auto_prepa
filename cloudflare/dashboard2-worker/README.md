# Worker "wf2" — tableau de bord sans « Générer Ventes »

Même page que le worker [`wf`](../dashboard-worker/README.md) (Contrôle
Stocks, Anticipation Commandes, Déplacer commandes), **sans la carte
« Générer Ventes »**. Le workflow `generer_ventes.yml` est aussi refusé côté
worker : il ne peut pas être lancé depuis cette URL, même en appelant
`/dispatch` directement.

Il n'y a pas de code propre à `wf2` : `wrangler.toml` pointe sur
`../dashboard-worker/src/index.js` et définit `MASQUER = "generer_ventes"`.
Toute évolution de `wf` (nouvelle carte, correction) profite donc à `wf2` au
prochain déploiement.

## Déploiement

```bash
cd cloudflare/dashboard2-worker
npx wrangler login               # une seule fois
npx wrangler secret put GH_TOKEN # même token que pour "wf"
npx wrangler deploy
```

URL obtenue : `https://wf2.controle-stocks.workers.dev` (même sous-domaine de
compte que `wf`).

Après une modification de `dashboard-worker/src/index.js`, redéployer **les
deux** workers (`wf` et `wf2`).

Attention : comme `wf`, la page n'est pas protégée par mot de passe.
