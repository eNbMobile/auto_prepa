package fr.maison.app;

import android.content.Intent;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** Tuile « Maison » : ouvre l'app sur les favoris. */
public class TuileMaison extends TileService {

    @Override
    public void onStartListening() {
        Tile t = getQsTile();
        if (t == null) return;
        t.setState(Tile.STATE_INACTIVE);
        t.updateTile();
    }

    @Override
    public void onClick() {
        Tuiles.ouvrir(this, new Intent(this, MainActivity.class).putExtra("vue", "favoris"), 2);
    }
}
