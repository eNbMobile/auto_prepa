package fr.maison.app;

import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

import org.json.JSONObject;

/**
 * Tuile interrupteur liée à un appareil SmartThings (choisi dans
 * ConfigActivity, ouverte par appui long sur la tuile).
 *
 * Un appui allume ou éteint directement, sans ouvrir l'app ; l'état réel est
 * relu à chaque ouverture du volet.
 */
public abstract class TuileAppareil extends TileService {

    public static class Un extends TuileAppareil { @Override int numero() { return 1; } }
    public static class Deux extends TuileAppareil { @Override int numero() { return 2; } }
    public static class Trois extends TuileAppareil { @Override int numero() { return 3; } }
    public static class Quatre extends TuileAppareil { @Override int numero() { return 4; } }

    static final Class<?>[] CLASSES = { Un.class, Deux.class, Trois.class, Quatre.class };

    private final Handler principal = new Handler(Looper.getMainLooper());

    abstract int numero();

    @Override
    public void onStartListening() {
        afficher(Maison.allume(this, numero()), null);
        String id = Maison.appareil(this, numero());
        if (id == null) return;
        Maison.RESEAU.execute(() -> {
            try {
                JSONObject s = new JSONObject(Maison.st(this, "devices/" + id + "/status", null));
                String v = s.getJSONObject("components").getJSONObject("main")
                        .getJSONObject("switch").getJSONObject("switch").optString("value");
                boolean on = "on".equals(v);
                Maison.memoriserEtat(this, numero(), on);
                principal.post(() -> afficher(on, null));
            } catch (Exception e) {
                principal.post(() -> afficher(Maison.allume(this, numero()), message(e)));
            }
        });
    }

    @Override
    public void onClick() {
        String id = Maison.appareil(this, numero());
        if (id == null) {
            Tuiles.ouvrir(this, new Intent(this, ConfigActivity.class).putExtra("tuile", numero()), 10 + numero());
            return;
        }
        boolean avant = Maison.allume(this, numero());
        boolean apres = !avant;
        // Affichage immédiat, corrigé si la commande échoue.
        Maison.memoriserEtat(this, numero(), apres);
        afficher(apres, null);
        String corps = "{\"commands\":[{\"component\":\"main\",\"capability\":\"switch\",\"command\":\""
                + (apres ? "on" : "off") + "\",\"arguments\":[]}]}";
        Maison.RESEAU.execute(() -> {
            try {
                Maison.st(this, "devices/" + id + "/commands", corps);
            } catch (Exception e) {
                Maison.memoriserEtat(this, numero(), avant);
                principal.post(() -> afficher(avant, message(e)));
            }
        });
    }

    private void afficher(boolean on, String erreur) {
        Tile t = getQsTile();
        if (t == null) return;
        boolean lie = Maison.appareil(this, numero()) != null;
        t.setLabel(Maison.nom(this, numero()));
        t.setState(!lie ? Tile.STATE_INACTIVE : on ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        if (Build.VERSION.SDK_INT >= 29) {
            t.setSubtitle(!lie ? "À configurer" : erreur != null ? erreur : on ? "Allumé" : "Éteint");
        }
        t.updateTile();
    }

    private static String message(Exception e) {
        return e instanceof Maison.ErreurHttp ? e.getMessage() : "Hors ligne";
    }
}
