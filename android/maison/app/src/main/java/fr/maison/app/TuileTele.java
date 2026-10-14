package fr.maison.app;

import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/**
 * Tuile « Télécommande » : affiche ou masque la télécommande du volet
 * (notification avec tous les boutons, voir NotifTele).
 */
public class TuileTele extends TileService {

    @Override
    public void onStartListening() {
        afficher(NotifTele.affichee(this));
    }

    @Override
    public void onClick() {
        if (!NotifTele.autorisee(this)) {
            // Android 13+ : l'autorisation des notifications se demande depuis une activité.
            Tuiles.ouvrir(this, new Intent(this, ConfigActivity.class).putExtra("notif", true), 20);
            return;
        }
        if (NotifTele.affichee(this)) {
            NotifTele.masquer(this);
            afficher(false);
            return;
        }
        afficher(true);
        Maison.RESEAU.execute(() -> {
            NotifTele.afficherDepuisReseau(getApplicationContext());
            new Handler(Looper.getMainLooper()).postDelayed(
                    () -> afficher(NotifTele.affichee(this)), 300);
        });
    }

    private void afficher(boolean active) {
        Tile t = getQsTile();
        if (t == null) return;
        t.setLabel("Télécommande");
        t.setState(active ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        if (Build.VERSION.SDK_INT >= 29) t.setSubtitle(active ? "Dans le volet" : "Masquée");
        t.updateTile();
    }
}
