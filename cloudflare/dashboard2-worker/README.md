# Worker "wf2" — tableau de bord sans « Générer Ventes » ni lien vers les runs

Même page que le worker [`wf`](../dashboard-worker/README.md) (Contrôle
Stocks, Anticipation Commandes, Déplacer commandes), **sans la carte
« Générer Ventes »**. Le workflow `generer_ventes.yml` est aussi refusé côté
worker : il ne peut pas être lancé depuis cette URL, même en appelant
`/dispatch` directement.

Le lien « Voir tous les runs sur GitHub Actions » du bas de page est aussi
retiré (le lien « Voir le run » affiché après un lancement reste).

Il n'y a pas de code propre à `wf2` : `wrangler.toml` pointe sur
`../dashboard-worker/src/index.js` et définit `MASQUER = "generer_ventes"` et
`SANS_LIEN_RUNS = "1"`.
Toute évolution de `wf` (nouvelle carte, correction) profite donc à `wf2` au
prochain déploiement.

## Déploiement

Automatique : le workflow `deploy_tableau_de_bord.yml` déploie `wf` et `wf2`
à chaque modification poussée sur `main` (voir le README de `wf` pour les
secrets). Déploiement à la main si besoin :

```bash
cd cloudflare/dashboard2-worker
npx wrangler login               # une seule fois
npx wrangler secret put GH_TOKEN # même token que pour "wf"
npx wrangler deploy
```

URL obtenue : `https://wf2.controle-stocks.workers.dev` (même sous-domaine de
compte que `wf`).


Attention : comme `wf`, la page n'est pas protégée par mot de passe.
