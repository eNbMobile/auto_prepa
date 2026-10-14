package fr.maison.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import org.json.JSONObject;

/**
 * Télécommande automatique : la notification télécommande (NotifTele)
 * apparaît quand la télé est allumée et disparaît quand elle est éteinte.
 *
 * Android exige un service au premier plan pour surveiller en continu ; sa
 * propre notification est dans un canal minimal (repliée, sans icône dans la
 * barre d'état) que l'on peut masquer dans les réglages de notification.
 * L'état de la télé n'est relu que quand l'écran est allumé : toutes les
 * 30 s, et aussitôt à l'allumage ou au déverrouillage.
 */
public class ServiceTele extends Service {

    private static final int ID = 41;
    private static final String CANAL = "surveillance";
    private static final long INTERVALLE_MS = 30_000;

    private final Handler principal = new Handler(Looper.getMainLooper());
    private final Runnable boucle = new Runnable() {
        @Override public void run() {
            verifier();
            if (ecranAllume()) principal.postDelayed(this, INTERVALLE_MS);
        }
    };
    private final BroadcastReceiver ecran = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            principal.removeCallbacks(boucle);
            if (!Intent.ACTION_SCREEN_OFF.equals(i.getAction())) principal.post(boucle);
        }
    };
    private volatile boolean verificationEnCours;

    /* ------------------------------------------------------- activation */

    static boolean actif(Context c) {
        return Maison.prefs(c).getBoolean("tele.auto", false);
    }

    /** Active et démarre la surveillance (lève une exception si Android refuse le démarrage). */
    static void activer(Context c) {
        Maison.prefs(c).edit().putBoolean("tele.auto", true).apply();
        c.startForegroundService(new Intent(c, ServiceTele.class));
    }

    static void desactiver(Context c) {
        Maison.prefs(c).edit().putBoolean("tele.auto", false).apply();
        c.stopService(new Intent(c, ServiceTele.class));
        NotifTele.masquer(c);
    }

    /** Relance le service s'il est activé (ouverture de l'app, redémarrage du téléphone). */
    static void relancerSiActif(Context c) {
        if (!actif(c) || !NotifTele.autorisee(c)) return;
        try {
            c.startForegroundService(new Intent(c, ServiceTele.class));
        } catch (RuntimeException ignore) {
            // Démarrage refusé en arrière-plan : il repartira à la prochaine ouverture de l'app.
        }
    }

    /* ------------------------------------------------------- cycle de vie */

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        NotificationChannel canal = new NotificationChannel(CANAL, "Surveillance de la télé",
                NotificationManager.IMPORTANCE_MIN);
        canal.setDescription("Nécessaire pour afficher la télécommande quand la télé s'allume. "
                + "Ce canal peut être masqué sans arrêter la surveillance.");
        nm.createNotificationChannel(canal);
        Notification n = new Notification.Builder(this, CANAL)
                .setSmallIcon(R.drawable.ic_tele)
                .setContentTitle("Télécommande automatique")
                .setContentText("S'affiche quand la télé est allumée")
                .setContentIntent(PendingIntent.getActivity(this, 5, new Intent(this, ConfigActivity.class),
                        PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
                .setOngoing(true)
                .setShowWhen(false)
                .build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(ID, n);
        }
        IntentFilter f = new IntentFilter();
        f.addAction(Intent.ACTION_SCREEN_ON);
        f.addAction(Intent.ACTION_SCREEN_OFF);
        f.addAction(Intent.ACTION_USER_PRESENT);
        registerReceiver(ecran, f);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        principal.removeCallbacks(boucle);
        principal.post(boucle);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        principal.removeCallbacks(boucle);
        unregisterReceiver(ecran);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /* ------------------------------------------------------- vérification */

    private boolean ecranAllume() {
        return getSystemService(PowerManager.class).isInteractive();
    }

    /** Lit l'état de la télé et affiche ou retire la télécommande en conséquence. */
    private void verifier() {
        if (verificationEnCours) return;
        verificationEnCours = true;
        Context app = getApplicationContext();
        Maison.RESEAU.execute(() -> {
            try {
                String tv = Maison.prefs(app).getString("tele.id", null);
                if (tv == null) {
                    JSONObject t = Tele.premiere(app);
                    if (t == null) return;
                    tv = t.optString("id");
                    Maison.prefs(app).edit().putString("tele.id", tv).putString("tele.nom", t.optString("nom")).apply();
                }
                boolean allumee = "on".equals(Tele.valeur(Tele.statut(app, tv), "switch", "switch"));
                principal.post(() -> {
                    boolean affichee = NotifTele.affichee(app);
                    if (allumee && !affichee) NotifTele.afficher(app);
                    else if (!allumee && affichee) NotifTele.masquer(app);
                });
            } catch (Exception ignore) {
                // Hors ligne ou session expirée : on garde l'affichage actuel.
            } finally {
                verificationEnCours = false;
            }
        });
    }

    /** Relance la surveillance après un redémarrage du téléphone. */
    public static class Demarrage extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent i) {
            if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())
                    || Intent.ACTION_MY_PACKAGE_REPLACED.equals(i.getAction())) {
                relancerSiActif(c);
            }
        }
    }
}
