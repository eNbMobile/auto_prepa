package fr.maison.app;

import android.content.Context;
import android.os.Build;

import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Date;
import java.util.Deque;
import java.util.Locale;

/**
 * Journal de diagnostic de « Contrôle appareil » : ce que le système demande
 * à l'app et ce qu'elle lui renvoie. Gardé en mémoire et dans les préférences
 * (400 dernières lignes), partageable depuis l'écran Tuiles rapides.
 */
final class Journal {

    private static final int MAX = 400;
    private static final Deque<String> LIGNES = new ArrayDeque<>();
    private static final SimpleDateFormat HEURE = new SimpleDateFormat("dd/MM HH:mm:ss.SSS", Locale.FRANCE);
    private static Context appli;
    private static boolean charge;

    private Journal() {}

    static synchronized void note(Context c, String message) {
        init(c);
        String ligne = HEURE.format(new Date()) + " [" + Thread.currentThread().getName() + "] " + message;
        LIGNES.addLast(ligne);
        while (LIGNES.size() > MAX) LIGNES.removeFirst();
        if (appli != null) Maison.prefs(appli).edit().putString("journal", String.join("\n", LIGNES)).apply();
    }

    static synchronized String texte(Context c) {
        init(c);
        return "Maison " + version(c) + " — Android " + Build.VERSION.RELEASE + " (SDK " + Build.VERSION.SDK_INT
                + "), " + Build.MANUFACTURER + " " + Build.MODEL + "\n\n" + String.join("\n", LIGNES);
    }

    static synchronized void effacer(Context c) {
        init(c);
        LIGNES.clear();
        Maison.prefs(appli).edit().remove("journal").apply();
    }

    private static void init(Context c) {
        if (charge || c == null) return;
        appli = c.getApplicationContext();
        String brut = Maison.prefs(appli).getString("journal", "");
        if (!brut.isEmpty()) for (String l : brut.split("\n")) LIGNES.addLast(l);
        charge = true;
    }

    private static String version(Context c) {
        try {
            return c.getPackageManager().getPackageInfo(c.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }
}
