# App Android « Maison »

La PWA Maison (`cloudflare/maison-worker`) dans une app Android, avec des
**tuiles pour le volet des raccourcis rapides** (ce qu'une PWA ne permet pas).

## Télécommande dans le volet (automatique)

La télécommande s'affiche dans les notifications **dès que la télé est
allumée** et disparaît quand elle s'éteint : alimentation, son, accueil,
retour, lecture/pause, volume ±, flèches + OK, Netflix et M6+. Chaque appui
envoie la touche sans ouvrir l'app.

- La tuile **Télécommande** active ou coupe ce mode (sur Android 13+, le
  premier appui demande l'autorisation des notifications).
- Fonctionnement : `ServiceTele`, service au premier plan, relit l'état de la
  télé toutes les 30 s **quand l'écran est allumé** (et aussitôt à
  l'allumage ou au déverrouillage). Il est relancé au démarrage du téléphone
  et à chaque ouverture de l'app.
- Android impose une notification « Télécommande automatique » pendant la
  surveillance (canal minimal) : appui long dessus → désactiver ce canal pour
  la masquer, la surveillance continue.

## Contrôle appareil (volet One UI)

Le bouton **Contrôle appareil** du volet affiche les commandes d'une app au
choix (SmartThings par défaut). Maison en fournit aussi :

- Volet → **Contrôle appareil** → **⋮** → choisir **Maison**.
- Les appareils avec interrupteur (lumières, prises, télé) et les scènes sont
  proposés ; un appui allume/éteint, glisser règle la luminosité.
- Carte **Télécommande** (dans le groupe de la pièce de la télé, à cocher dans
  la sélection) : la toucher ouvre la **grande télécommande flottante** par-dessus
  le volet ; toucher à côté la referme. Toucher la carte télé fait de même.
  One UI n'affiche pas d'écran d'app dans ce panneau, seulement des cartes : la
  télécommande ne peut donc pas y être intégrée directement.
- Le dernier état connu de chaque appareil s'affiche immédiatement à la
  réouverture du panneau, puis il est relu en arrière-plan.
- Pour chaque télé, des **touches de télécommande** à ajouter au panneau :
  volume ±, muet, chaînes ±, flèches, OK, retour, accueil, lecture/pause.
  Un appui envoie la touche directement (seules les touches que la télé
  accepte sont proposées).
- Sur Android 14+, le panneau peut afficher **l'écran Maison** à la place des
  commandes (PanneauActivity, déclarée comme `META_DATA_PANEL_ACTIVITY`) : la
  carte télé avec la **télécommande en grand** (vue `#panneau` de la PWA, « ✎ Modifier » pour les réglages).

## Tuiles

| Tuile | Effet |
|---|---|
| Télécommande | affiche ou masque la télécommande du volet |
| Maison | ouvre l'app sur les favoris |
| Appareil 1 à 4 | allume ou éteint l'appareil choisi, **sans ouvrir l'app** ; l'état est relu à chaque ouverture du volet |

Pour choisir l'appareil d'une tuile, fais un appui long dessus dans le volet,
ou utilise le raccourci « Tuiles rapides » (appui long sur l'icône de l'app).
Seuls les appareils qui ont un interrupteur (capacité `switch`) sont proposés.

## Installation

1. Sur le téléphone, télécharge
   https://github.com/eNbMobile/auto_prepa/releases/download/maison-android/Maison.apk
2. Ouvre le fichier et autorise l'installation depuis le navigateur.
3. Lance **Maison** et saisis le mot de passe (la même clé que la PWA). Les
   tuiles réutilisent cette session.
4. Ajoute les tuiles : *Tuiles rapides* → boutons « ＋ », ou volet → ✎ →
   glisser les tuiles Maison.

Les nouvelles versions s'installent par-dessus, sans perdre les réglages.

## Build

Le workflow `.github/workflows/android_maison.yml` construit l'APK à chaque
push sur `main` qui touche ce dossier et le publie dans la Release
`maison-android`. La clé de signature est générée au premier build et rangée
dans le KV Cloudflare `maison-smartthings` (clés `android:keystore` et
`android:mdp`), car le dépôt est public.

Code : Java sans dépendance (WebView, `TileService`), minSdk 26, targetSdk 35.

## Raccourcis Netflix et M6+

Lancés avec la capacité SmartThings `custom.launchapp` (commande `launchApp`) :

- Netflix : identifiant Tizen `org.tizen.netflix-app`.
- M6+ : aucun identifiant public fiable n'a été trouvé, l'appli est lancée par
  son nom (`M6+`). Si le bouton ne fait rien, il faudra relever son
  identifiant sur la télé (Tizen Studio → Device Manager → liste des applis
  installées) et le mettre dans `Tele.java` et `page.html` (`M6PLUS`).
