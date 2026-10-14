package fr.maison.app;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.service.notification.StatusBarNotification;
import android.widget.RemoteViews;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * Télécommande affichée en notification épinglée : tous les boutons sont
 * visibles directement dans le volet, et chaque appui envoie la touche à la
 * télé sans ouvrir l'app (via Recepteur).
 */
public final class NotifTele {

    static final int ID = 42;
    private static final String CANAL = "telecommande";

    /** Bouton de la mise en page → touche envoyée. */
    private static final Object[][] BOUTONS = {
        { R.id.t_power, "POWER" }, { R.id.t_mute, "MUTE" }, { R.id.t_home, "HOME" }, { R.id.t_back, "BACK" },
        { R.id.t_play, "PLAY" }, { R.id.t_volm, "VOL-" }, { R.id.t_up, "UP" }, { R.id.t_volp, "VOL+" },
        { R.id.t_left, "LEFT" }, { R.id.t_ok, "OK" }, { R.id.t_right, "RIGHT" },
        { R.id.t_down, "DOWN" }, { R.id.t_netflix, "NETFLIX" }, { R.id.t_m6, "M6PLUS" },
    };

    private NotifTele() {}

    static boolean autorisee(Context c) {
        return Build.VERSION.SDK_INT < 33
                || c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    static boolean affichee(Context c) {
        for (StatusBarNotification n : c.getSystemService(NotificationManager.class).getActiveNotifications()) {
            if (n.getId() == ID) return true;
        }
        return false;
    }

    static void masquer(Context c) {
        c.getSystemService(NotificationManager.class).cancel(ID);
    }

    /** Cherche la télé (réseau si besoin) puis affiche la notification. À appeler hors du fil principal. */
    static void afficherDepuisReseau(Context c) {
        try {
            JSONObject tv = Tele.premiere(c);
            if (tv == null) { message(c, "Aucune télé trouvée sur le compte SmartThings"); return; }
            Maison.prefs(c).edit().putString("tele.id", tv.optString("id"))
                    .putString("tele.nom", tv.optString("nom")).apply();
            new Handler(Looper.getMainLooper()).post(() -> afficher(c));
        } catch (Exception e) {
            message(c, e instanceof Maison.ErreurHttp ? e.getMessage() : "Hors ligne");
        }
    }

    static void afficher(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CANAL, "Télécommande", NotificationManager.IMPORTANCE_LOW));

        RemoteViews grande = new RemoteViews(c.getPackageName(), R.layout.notif_tele);
        RemoteViews petite = new RemoteViews(c.getPackageName(), R.layout.notif_tele_petite);
        for (Object[] b : BOUTONS) {
            int vue = (Integer) b[0];
            PendingIntent pi = PendingIntent.getBroadcast(c, vue,
                    new Intent(c, Recepteur.class).putExtra("cle", (String) b[1]),
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            grande.setOnClickPendingIntent(vue, pi);
            petite.setOnClickPendingIntent(vue, pi);
        }
        PendingIntent ouvrir = PendingIntent.getActivity(c, 1,
                new Intent(c, MainActivity.class).putExtra("vue", "tele"),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        Notification n = new Notification.Builder(c, CANAL)
                .setSmallIcon(R.drawable.ic_tele)
                .setContentTitle(Maison.prefs(c).getString("tele.nom", "Télé"))
                .setStyle(new Notification.DecoratedCustomViewStyle())
                .setCustomContentView(petite)
                .setCustomBigContentView(grande)
                .setContentIntent(ouvrir)
                .setOngoing(true)
                .setShowWhen(false)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_TRANSPORT)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .build();
        nm.notify(ID, n);
    }

    private static void message(Context c, String texte) {
        new Handler(Looper.getMainLooper()).post(() -> Toast.makeText(c, texte, Toast.LENGTH_SHORT).show());
    }

    /** Reçoit les appuis sur les boutons de la notification. */
    public static class Recepteur extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent intent) {
            String cle = intent.getStringExtra("cle");
            String tv = Maison.prefs(c).getString("tele.id", null);
            if (cle == null || tv == null) return;
            PendingResult fin = goAsync();
            Context app = c.getApplicationContext();
            Maison.RESEAU.execute(() -> {
                try {
                    Tele.envoyer(app, tv, cle);
                } catch (Exception e) {
                    message(app, "Télécommande : " + (e instanceof Maison.ErreurHttp ? e.getMessage() : "hors ligne"));
                } finally {
                    fin.finish();
                }
            });
        }
    }
}
