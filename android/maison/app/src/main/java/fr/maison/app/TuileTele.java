package fr.maison.app;

import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/**
 * Tuile « Télécommande » : active ou coupe la télécommande automatique
 * (notification affichée tant que la télé est allumée, voir ServiceTele).
 */
public class TuileTele extends TileService {

    @Override
    public void onStartListening() {
        afficher(ServiceTele.actif(this));
    }

    @Override
    public void onClick() {
        if (ServiceTele.actif(this)) {
            ServiceTele.desactiver(this);
            afficher(false);
            return;
        }
        if (!NotifTele.autorisee(this)) {
            // Android 13+ : l'autorisation des notifications se demande depuis une activité.
            Tuiles.ouvrir(this, new Intent(this, ConfigActivity.class).putExtra("auto", true), 20);
            return;
        }
        try {
            ServiceTele.activer(this);
            afficher(true);
        } catch (RuntimeException e) {
            // Démarrage refusé depuis le volet : on passe par l'écran de réglages.
            Tuiles.ouvrir(this, new Intent(this, ConfigActivity.class).putExtra("auto", true), 20);
        }
    }

    private void afficher(boolean actif) {
        Tile t = getQsTile();
        if (t == null) return;
        t.setLabel("Télécommande");
        t.setState(actif ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        if (Build.VERSION.SDK_INT >= 29) t.setSubtitle(actif ? "Automatique" : "Désactivée");
        t.updateTile();
    }
}
