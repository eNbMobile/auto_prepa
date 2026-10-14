package fr.maison.app;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Accès au worker « maison » et réglages locaux.
 *
 * Les tuiles parlent au même worker que la PWA, avec le cookie de session
 * récupéré dans la WebView après connexion (voir MainActivity).
 */
final class Maison {

    static final String BASE = "https://maison.coopu.workers.dev";
    static final int NB_TUILES = 4;

    /** Un seul fil pour le réseau : les tuiles n'envoient jamais grand-chose. */
    static final ExecutorService RESEAU = Executors.newSingleThreadExecutor();

    private Maison() {}

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("maison", Context.MODE_PRIVATE);
    }

    static String cookie(Context c) {
        return prefs(c).getString("cookie", "");
    }

    static void sauverCookie(Context c, String cookie) {
        if (cookie != null && cookie.contains("maison=")) prefs(c).edit().putString("cookie", cookie).apply();
    }

    /* ----------------------------------------------- appareils des tuiles */

    static String appareil(Context c, int n) {
        return prefs(c).getString("tuile" + n + ".id", null);
    }

    static String nom(Context c, int n) {
        return prefs(c).getString("tuile" + n + ".nom", "Appareil " + n);
    }

    static boolean allume(Context c, int n) {
        return prefs(c).getBoolean("tuile" + n + ".on", false);
    }

    static void lier(Context c, int n, String id, String nom) {
        SharedPreferences.Editor e = prefs(c).edit();
        if (id == null) e.remove("tuile" + n + ".id").remove("tuile" + n + ".nom");
        else e.putString("tuile" + n + ".id", id).putString("tuile" + n + ".nom", nom);
        e.remove("tuile" + n + ".on").apply();
    }

    static void memoriserEtat(Context c, int n, boolean on) {
        prefs(c).edit().putBoolean("tuile" + n + ".on", on).apply();
    }

    /* ----------------------------------------------------------- réseau */

    static class ErreurHttp extends IOException {
        final int code;
        ErreurHttp(int code, String msg) { super(msg); this.code = code; }
    }

    /** Appel au relais SmartThings du worker : chemin relatif à /api/st/. */
    static String st(Context c, String chemin, String corpsJson) throws IOException {
        HttpURLConnection cx = (HttpURLConnection) new URL(BASE + "/api/st/" + chemin).openConnection();
        try {
            cx.setConnectTimeout(5000);
            cx.setReadTimeout(8000);
            cx.setRequestProperty("Cookie", cookie(c));
            cx.setRequestProperty("Accept", "application/json");
            if (corpsJson != null) {
                cx.setRequestMethod("POST");
                cx.setDoOutput(true);
                cx.setRequestProperty("Content-Type", "application/json");
                try (OutputStream os = cx.getOutputStream()) {
                    os.write(corpsJson.getBytes(StandardCharsets.UTF_8));
                }
            }
            int code = cx.getResponseCode();
            InputStream is = code < 400 ? cx.getInputStream() : cx.getErrorStream();
            String texte = lire(is);
            if (code >= 400) {
                String msg = code == 401 ? "Connecte-toi dans l'app Maison" : "Erreur " + code;
                throw new ErreurHttp(code, msg);
            }
            return texte;
        } finally {
            cx.disconnect();
        }
    }

    private static String lire(InputStream is) throws IOException {
        if (is == null) return "";
        try (InputStream in = is) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] tampon = new byte[8192];
            int n;
            while ((n = in.read(tampon)) > 0) out.write(tampon, 0, n);
            return out.toString("UTF-8");
        }
    }
}
