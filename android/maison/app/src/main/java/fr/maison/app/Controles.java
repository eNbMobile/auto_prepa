package fr.maison.app;

import android.annotation.TargetApi;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.service.controls.Control;
import android.service.controls.ControlsProviderService;
import android.service.controls.DeviceTypes;
import android.service.controls.actions.BooleanAction;
import android.service.controls.actions.ControlAction;
import android.service.controls.actions.FloatAction;
import android.service.controls.templates.ControlButton;
import android.service.controls.templates.ControlTemplate;
import android.service.controls.templates.RangeTemplate;
import android.service.controls.templates.StatelessTemplate;
import android.service.controls.templates.ToggleRangeTemplate;
import android.service.controls.templates.ToggleTemplate;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;
import java.util.concurrent.Flow;
import java.util.function.Consumer;

/**
 * Fournisseur de « Contrôle appareil » (commandes d'appareils Android).
 *
 * Dans le panneau Contrôle appareil, choisir l'app « Maison » : ses appareils
 * (lumières, prises, télé) et ses scènes y apparaissent, et sur Android 14+
 * l'app entière peut s'y afficher (PanneauActivity, déclarée dans le manifeste).
 *
 * Identifiants des commandes : « d:<deviceId> », « s:<sceneId> », « app ».
 */
@TargetApi(30)
public class Controles extends ControlsProviderService {

    private static final String APP = "app";

    /** Touches de télécommande : {code, libellé, capacité requise (drapeau du cache)}. */
    private static final String[][] TOUCHES = {
        { "VOL+", "Volume +", "volume" }, { "VOL-", "Volume −", "volume" }, { "MUTE", "Muet", "muet" },
        { "CH+", "Chaîne +", "chaines" }, { "CH-", "Chaîne −", "chaines" },
        { "UP", "Haut ▲", "fleches" }, { "DOWN", "Bas ▼", "fleches" }, { "LEFT", "Gauche ◀", "fleches" },
        { "RIGHT", "Droite ▶", "fleches" }, { "OK", "OK", "fleches" }, { "BACK", "Retour", "fleches" },
        { "HOME", "Accueil", "fleches" }, { "PLAY", "Lecture / pause", "lecture" },
    };
    private static final Set<Editeur> ACTIFS = new CopyOnWriteArraySet<>();

    /* ----------------------------------------------------------- éditeurs */

    /** Publisher minimal : la source pousse les commandes quand on la démarre. */
    private static final class Editeur implements Flow.Publisher<Control> {
        interface Source { void lancer(Editeur e); }

        final List<String> ids;
        private final Source source;
        private Flow.Subscriber<? super Control> abonne;
        private volatile boolean annule;
        private boolean demarre;

        Editeur(List<String> ids, Source source) { this.ids = ids; this.source = source; }

        @Override
        public void subscribe(Flow.Subscriber<? super Control> s) {
            abonne = s;
            s.onSubscribe(new Flow.Subscription() {
                @Override public void request(long n) {
                    synchronized (Editeur.this) {
                        if (demarre) return;
                        demarre = true;
                    }
                    Maison.RESEAU.execute(() -> source.lancer(Editeur.this));
                }
                @Override public void cancel() { annule = true; ACTIFS.remove(Editeur.this); }
            });
        }

        void publier(Control c) { if (!annule) abonne.onNext(c); }
        void finir() { if (!annule) abonne.onComplete(); }
    }

    /* ------------------------------------------------------ liste complète */

    @Override
    public Flow.Publisher<Control> createPublisherForAllAvailable() {
        return new Editeur(null, e -> {
            e.publier(controleApp(this, false));
            try {
                for (JSONObject a : chargerAppareils(this)) {
                    e.publier(sansEtat(this, a));
                    for (String[] t : touches(a)) e.publier(toucheSansEtat(this, a, t));
                }
                JSONArray scenes = new JSONObject(Maison.st(this, "scenes", null)).optJSONArray("items");
                for (int i = 0; scenes != null && i < scenes.length(); i++) {
                    JSONObject s = scenes.getJSONObject(i);
                    Maison.prefs(this).edit().putString("scene.s:" + s.getString("sceneId"),
                            s.optString("sceneName", "Scène")).apply();
                    e.publier(new Control.StatelessBuilder("s:" + s.getString("sceneId"), intention(this, "scenes", 3))
                            .setTitle(s.optString("sceneName", "Scène"))
                            .setSubtitle("Scène")
                            .setStructure("Maison")
                            .setZone("Scènes")
                            .setDeviceType(DeviceTypes.TYPE_ROUTINE)
                            .build());
                }
            } catch (Exception ignore) {
                // Pas connecté ou hors ligne : seule la commande « Maison » est proposée.
            }
            e.finir();
        });
    }

    /* ------------------------------------------------ commandes affichées */

    @Override
    public Flow.Publisher<Control> createPublisherFor(List<String> ids) {
        Editeur ed = new Editeur(new ArrayList<>(ids), this::rafraichir);
        ACTIFS.add(ed);
        return ed;
    }

    private void rafraichir(Editeur e) {
        rafraichir(e, e.ids);
    }

    private void rafraichir(Editeur e, List<String> ids) {
        Map<String, JSONObject> appareils = new HashMap<>();
        try {
            for (JSONObject a : appareilsEnCache(this)) appareils.put(a.optString("id"), a);
        } catch (Exception ignore) { }
        for (String id : ids) {
            if (APP.equals(id)) { e.publier(controleApp(this, true)); continue; }
            if (id.startsWith("s:")) { e.publier(controleScene(id)); continue; }
            if (id.startsWith("t:")) {
                String[] p = id.split(":", 3);
                JSONObject tv = p.length == 3 ? appareils.get(p[1]) : null;
                String[] t = tv == null ? null : touche(p[2]);
                if (t != null) e.publier(toucheAvecEtat(this, tv, t));
                continue;
            }
            JSONObject a = appareils.get(id.substring(2));
            if (a == null) continue;
            try {
                JSONObject main = new JSONObject(Maison.st(this, "devices/" + a.getString("id") + "/status", null))
                        .getJSONObject("components").getJSONObject("main");
                e.publier(avecEtat(this, a, main, null));
            } catch (Exception ex) {
                e.publier(avecEtat(this, a, null,
                        ex instanceof Maison.ErreurHttp ? ex.getMessage() : "Hors ligne"));
            }
        }
    }

    /** Relit un appareil après une action et le republie chez ceux qui l'affichent. */
    private void republier(String controlId) {
        for (Editeur e : ACTIFS) {
            if (e.ids.contains(controlId)) rafraichir(e, List.of(controlId));
        }
    }

    /* -------------------------------------------------------------- actions */

    @Override
    public void performControlAction(String id, ControlAction action, Consumer<Integer> reponse) {
        Maison.RESEAU.execute(() -> {
            try {
                if (id.startsWith("t:")) {
                    String[] p = id.split(":", 3);
                    Tele.envoyer(this, p[1], p[2]);
                } else if (id.startsWith("s:")) {
                    Maison.st(this, "scenes/" + id.substring(2) + "/execute", "{}");
                } else if (id.startsWith("d:")) {
                    String dev = id.substring(2);
                    if (action instanceof BooleanAction) {
                        boolean on = ((BooleanAction) action).getNewState();
                        commande(dev, "switch", on ? "on" : "off", "");
                    } else if (action instanceof FloatAction) {
                        int niveau = Math.round(((FloatAction) action).getNewValue());
                        commande(dev, "switchLevel", "setLevel", String.valueOf(niveau));
                    }
                }
                reponse.accept(ControlAction.RESPONSE_OK);
            } catch (Exception e) {
                reponse.accept(ControlAction.RESPONSE_FAIL);
            }
            if (id.startsWith("d:")) {
                try { Thread.sleep(800); } catch (InterruptedException ignore) { }
                republier(id);
            }
        });
    }

    private void commande(String dev, String cap, String cmd, String args) throws Exception {
        Maison.st(this, "devices/" + dev + "/commands", "{\"commands\":[{\"component\":\"main\",\"capability\":\""
                + cap + "\",\"command\":\"" + cmd + "\",\"arguments\":[" + args + "]}]}");
    }

    /* ------------------------------------------------------ construction */

    static PendingIntent intention(Context c, String vue, int code) {
        Intent i = new Intent(c, PanneauActivity.class).putExtra("vue", vue)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return PendingIntent.getActivity(c, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    /** Commande « Maison » : un appui ouvre l'app (la télécommande, les favoris…). */
    static Control controleApp(Context c, boolean avecEtat) {
        PendingIntent pi = intention(c, "favoris", 2);
        if (!avecEtat) {
            return new Control.StatelessBuilder(APP, pi).setTitle("Maison").setSubtitle("Ouvrir l'app")
                    .setStructure("Maison").setZone("App").setDeviceType(DeviceTypes.TYPE_GENERIC_VIEWSTREAM).build();
        }
        return new Control.StatefulBuilder(APP, pi).setTitle("Maison").setSubtitle("Ouvrir l'app")
                .setStructure("Maison").setZone("App").setDeviceType(DeviceTypes.TYPE_GENERIC_VIEWSTREAM)
                .setStatus(Control.STATUS_OK).setControlTemplate(ControlTemplate.getNoTemplateObject())
                .setStatusText("").build();
    }

    private Control controleScene(String id) {
        String nom = Maison.prefs(this).getString("scene." + id, "Scène");
        return new Control.StatefulBuilder(id, intention(this, "scenes", 3))
                .setTitle(nom).setSubtitle("Scène").setStructure("Maison").setZone("Scènes")
                .setDeviceType(DeviceTypes.TYPE_ROUTINE).setStatus(Control.STATUS_OK)
                .setControlTemplate(new StatelessTemplate("lancer")).setStatusText("Lancer").build();
    }

    private static String[] touche(String cle) {
        for (String[] t : TOUCHES) if (t[0].equals(cle)) return t;
        return null;
    }

    private static List<String[]> touches(JSONObject a) {
        List<String[]> l = new ArrayList<>();
        if (!a.optBoolean("tele")) return l;
        for (String[] t : TOUCHES) if (a.optBoolean(t[2])) l.add(t);
        return l;
    }

    // Type « télécommande » et non « TV » : un appui envoie la touche au lieu
    // d'ouvrir l'app dans une fenêtre.
    private static Control toucheSansEtat(Context c, JSONObject tv, String[] t) {
        return new Control.StatelessBuilder("t:" + tv.optString("id") + ":" + t[0], intention(c, "tele", 1))
                .setTitle(t[1]).setSubtitle(tv.optString("nom"))
                .setStructure("Maison").setZone("Télécommande " + tv.optString("nom"))
                .setDeviceType(DeviceTypes.TYPE_REMOTE_CONTROL).build();
    }

    private static Control toucheAvecEtat(Context c, JSONObject tv, String[] t) {
        return new Control.StatefulBuilder("t:" + tv.optString("id") + ":" + t[0], intention(c, "tele", 1))
                .setTitle(t[1]).setSubtitle(tv.optString("nom"))
                .setStructure("Maison").setZone("Télécommande " + tv.optString("nom"))
                .setDeviceType(DeviceTypes.TYPE_REMOTE_CONTROL)
                .setStatus(Control.STATUS_OK).setControlTemplate(new StatelessTemplate(t[0]))
                .setStatusText("").build();
    }

    private static int type(JSONObject a) {
        if (a.optBoolean("tele")) return DeviceTypes.TYPE_TV;
        if (a.optBoolean("lumiere")) return DeviceTypes.TYPE_LIGHT;
        if (a.optBoolean("prise")) return DeviceTypes.TYPE_OUTLET;
        return DeviceTypes.TYPE_SWITCH;
    }

    static Control sansEtat(Context c, JSONObject a) {
        boolean tele = a.optBoolean("tele");
        return new Control.StatelessBuilder("d:" + a.optString("id"), intention(c, tele ? "tele" : "favoris", 100 + a.optString("id").hashCode() % 1000))
                .setTitle(a.optString("nom")).setSubtitle(a.optString("piece"))
                .setStructure("Maison").setZone(a.optString("piece", "Maison"))
                .setDeviceType(type(a)).build();
    }

    private static Control avecEtat(Context c, JSONObject a, JSONObject main, String erreur) {
        String id = a.optString("id");
        boolean tele = a.optBoolean("tele");
        Control.StatefulBuilder b = new Control.StatefulBuilder("d:" + id,
                intention(c, tele ? "tele" : "favoris", 100 + id.hashCode() % 1000))
                .setTitle(a.optString("nom")).setSubtitle(a.optString("piece"))
                .setStructure("Maison").setZone(a.optString("piece", "Maison"))
                .setDeviceType(type(a));
        if (main == null) {
            return b.setStatus(Control.STATUS_ERROR).setStatusText(erreur == null ? "Erreur" : erreur).build();
        }
        boolean on = "on".equals(Tele.valeur(main, "switch", "switch"));
        ControlButton bouton = new ControlButton(on, on ? "Éteindre" : "Allumer");
        String texte = on ? "Allumé" : "Éteint";
        ControlTemplate t;
        String niveau = Tele.valeur(main, "switchLevel", "level");
        if (a.optBoolean("variateur") && niveau != null) {
            float n = Math.max(0, Math.min(100, Float.parseFloat(niveau)));
            t = new ToggleRangeTemplate("niveau", bouton, new RangeTemplate("plage", 0, 100, n, 1, "%.0f %%"));
            if (on) texte = Math.round(n) + " %";
        } else {
            t = new ToggleTemplate("bascule", bouton);
        }
        return b.setStatus(Control.STATUS_OK).setControlTemplate(t).setStatusText(texte).build();
    }


    /* --------------------------------------------- liste des appareils */

    /** Appareils pilotables (interrupteur), avec leur pièce ; mis en cache. */
    static List<JSONObject> chargerAppareils(Context c) throws Exception {
        Map<String, String> pieces = new HashMap<>();
        JSONArray locs = new JSONObject(Maison.st(c, "locations", null)).optJSONArray("items");
        for (int i = 0; locs != null && i < locs.length(); i++) {
            String loc = locs.getJSONObject(i).getString("locationId");
            JSONArray rooms = new JSONObject(Maison.st(c, "locations/" + loc + "/rooms", null)).optJSONArray("items");
            for (int j = 0; rooms != null && j < rooms.length(); j++) {
                JSONObject r = rooms.getJSONObject(j);
                pieces.put(r.optString("roomId"), r.optString("name"));
            }
        }
        JSONArray items = new JSONObject(Maison.st(c, "devices", null)).getJSONArray("items");
        JSONArray cache = new JSONArray();
        List<JSONObject> l = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject d = items.getJSONObject(i);
            List<String> caps = capacites(d);
            if (!caps.contains("switch")) continue;
            String nom = d.optString("label");
            if (nom.isEmpty()) nom = d.optString("name", "Appareil");
            String bas = nom.toLowerCase();
            JSONObject a = new JSONObject()
                    .put("id", d.getString("deviceId"))
                    .put("nom", nom)
                    .put("piece", pieces.containsKey(d.optString("roomId")) ? pieces.get(d.optString("roomId")) : "Maison")
                    .put("tele", caps.contains("samsungvd.remoteControl") || caps.contains("tvChannel"))
                    .put("variateur", caps.contains("switchLevel"))
                    .put("volume", caps.contains("audioVolume"))
                    .put("muet", caps.contains("audioMute"))
                    .put("chaines", caps.contains("tvChannel"))
                    .put("fleches", caps.contains("samsungvd.remoteControl"))
                    .put("lecture", caps.contains("mediaPlayback"))
                    .put("lumiere", caps.contains("switchLevel") || caps.contains("colorControl")
                            || bas.matches(".*(lampe|lumi|light|ampoule|led|plafonnier|spot).*"))
                    .put("prise", bas.matches(".*(prise|plug|outlet).*"));
            cache.put(a);
            l.add(a);
        }
        Maison.prefs(c).edit().putString("appareils", cache.toString()).apply();
        return l;
    }

    static List<JSONObject> appareilsEnCache(Context c) throws Exception {
        String brut = Maison.prefs(c).getString("appareils", null);
        if (brut == null) return chargerAppareils(c);
        JSONArray a = new JSONArray(brut);
        List<JSONObject> l = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) l.add(a.getJSONObject(i));
        return l;
    }

    private static List<String> capacites(JSONObject d) {
        List<String> l = new ArrayList<>();
        JSONArray comps = d.optJSONArray("components");
        for (int i = 0; comps != null && i < comps.length(); i++) {
            JSONObject c = comps.optJSONObject(i);
            if (c == null || !"main".equals(c.optString("id"))) continue;
            JSONArray caps = c.optJSONArray("capabilities");
            for (int j = 0; caps != null && j < caps.length(); j++) {
                JSONObject cap = caps.optJSONObject(j);
                if (cap != null) l.add(cap.optString("id"));
            }
        }
        return l;
    }
}
