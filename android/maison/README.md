# App Android « Maison »

La PWA Maison (`cloudflare/maison-worker`) dans une app Android, avec des
**tuiles pour le volet des raccourcis rapides** (ce qu'une PWA ne permet pas).

## Tuiles

| Tuile | Effet |
|---|---|
| Télécommande | ouvre directement la télécommande |
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
