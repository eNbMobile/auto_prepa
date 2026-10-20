package fr.maison.app;

import android.content.Context;

import org.json.JSONObject;

/** Envoi des touches de télécommande, partagé par Contrôle appareil et la notification. */
final class Tele {

    private Tele() {}

    /** Même logique que la télécommande de la PWA (page.html, toucheTele). */
    static void envoyer(Context c, String tv, String cle) throws Exception {
        switch (cle) {
            case "VOL+": commande(c, tv, "audioVolume", "volumeUp", ""); break;
            case "VOL-": commande(c, tv, "audioVolume", "volumeDown", ""); break;
            case "CH+": commande(c, tv, "tvChannel", "channelUp", ""); break;
            case "CH-": commande(c, tv, "tvChannel", "channelDown", ""); break;
            case "MUTE": {
                boolean muet = "muted".equals(valeur(statut(c, tv), "audioMute", "mute"));
                commande(c, tv, "audioMute", muet ? "unmute" : "mute", "");
                break;
            }
            case "PLAY": {
                boolean lecture = "playing".equals(valeur(statut(c, tv), "mediaPlayback", "playbackStatus"));
                commande(c, tv, "mediaPlayback", lecture ? "pause" : "play", "");
                break;
            }
            // Applis : identifiant Tizen connu pour Netflix ; celui de M6+ n'est pas
            // public, il se règle dans la PWA (config.appM6), voir README.
            case "NETFLIX": commande(c, tv, "custom.launchapp", "launchApp", "\"org.tizen.netflix-app\",\"Netflix\""); break;
            case "M6PLUS": {
                String app = new JSONObject(Maison.config(c)).optString("appM6").trim();
                if (app.isEmpty()) throw new Maison.ErreurHttp(0, "identifiant M6+ à régler dans Maison → Réglages");
                commande(c, tv, "custom.launchapp", "launchApp", JSONObject.quote(app) + ",\"M6+\"");
                break;
            }
            case "POWER": {
                boolean on = "on".equals(valeur(statut(c, tv), "switch", "switch"));
                commande(c, tv, "switch", on ? "off" : "on", "");
                break;
            }
            default: commande(c, tv, "samsungvd.remoteControl", "send", "\"" + cle + "\"");
        }
    }

    static void commande(Context c, String dev, String cap, String cmd, String args) throws Exception {
        Maison.st(c, "devices/" + dev + "/commands", "{\"commands\":[{\"component\":\"main\",\"capability\":\""
                + cap + "\",\"command\":\"" + cmd + "\",\"arguments\":[" + args + "]}]}");
    }

    static JSONObject statut(Context c, String dev) throws Exception {
        return new JSONObject(Maison.st(c, "devices/" + dev + "/status", null))
                .getJSONObject("components").getJSONObject("main");
    }

    static String valeur(JSONObject main, String cap, String attr) {
        JSONObject o = main.optJSONObject(cap);
        JSONObject v = o == null ? null : o.optJSONObject(attr);
        return v == null || v.isNull("value") ? null : v.opt("value").toString();
    }

    /** Première télé du compte (liste en cache, chargée si besoin : appel réseau). */
    static JSONObject premiere(Context c) throws Exception {
        for (JSONObject a : Controles.appareilsEnCache(c)) if (a.optBoolean("tele")) return a;
        for (JSONObject a : Controles.chargerAppareils(c)) if (a.optBoolean("tele")) return a;
        return null;
    }
}
