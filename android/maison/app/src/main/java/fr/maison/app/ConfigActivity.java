package fr.maison.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.StatusBarManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.Bundle;
import android.service.quicksettings.TileService;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Choix de l'appareil piloté par chaque tuile « interrupteur », et ajout des
 * tuiles au volet rapide (Android 13+).
 */
public class ConfigActivity extends Activity {

    private LinearLayout liste;
    private final List<String[]> appareils = new ArrayList<>(); // {id, nom}

    @Override
    protected void onCreate(Bundle etat) {
        super.onCreate(etat);
        ScrollView defil = new ScrollView(this);
        liste = new LinearLayout(this);
        liste.setOrientation(LinearLayout.VERTICAL);
        int m = dp(16);
        liste.setPadding(m, m, m, m);
        defil.addView(liste);
        setContentView(defil);
        construire();

        // Appui long sur une tuile du volet : on va droit au choix de son appareil.
        int n = getIntent().getIntExtra("tuile", 0);
        ComponentName c = getIntent().getParcelableExtra(Intent.EXTRA_COMPONENT_NAME);
        if (c != null) {
            for (int i = 0; i < TuileAppareil.CLASSES.length; i++) {
                if (TuileAppareil.CLASSES[i].getName().equals(c.getClassName())) n = i + 1;
            }
        }
        if (n > 0) choisir(n);
        if (getIntent().getBooleanExtra("notif", false)) basculerNotif();
    }

    /** Affiche ou masque la télécommande du volet (demande l'autorisation si besoin). */
    private void basculerNotif() {
        if (!NotifTele.autorisee(this)) {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 1);
            return;
        }
        if (NotifTele.affichee(this)) {
            NotifTele.masquer(this);
            construire();
            return;
        }
        Context app = getApplicationContext();
        Maison.RESEAU.execute(() -> {
            NotifTele.afficherDepuisReseau(app);
            runOnUiThread(() -> liste.postDelayed(this::construire, 300));
        });
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] resultats) {
        if (NotifTele.autorisee(this)) basculerNotif();
        else Toast.makeText(this, "Sans notifications, la télécommande du volet ne peut pas s'afficher.",
                Toast.LENGTH_LONG).show();
    }

    private void construire() {
        liste.removeAllViews();
        if (Maison.cookie(this).isEmpty()) {
            texte("Ouvre d'abord l'app Maison et connecte-toi : les tuiles utilisent la même session.", 16);
            bouton("Ouvrir Maison", () -> startActivity(new Intent(this, MainActivity.class)));
            return;
        }
        titre("Télécommande dans le volet");
        texte("Toute la télécommande dans une notification épinglée : chaque bouton envoie "
                + "la touche sans ouvrir l'app. La tuile « Télécommande » l'affiche ou la masque.", 14);
        bouton(NotifTele.affichee(this) ? "Masquer la télécommande" : "Afficher la télécommande", this::basculerNotif);
        titre("Contrôle appareil");
        texte("Volet → Contrôle appareil → ⋮ (en haut à droite) → choisis l'app « Maison » "
                + "à la place de SmartThings. Tes appareils et scènes y apparaissent, "
                + "et sur Android 14+ l'app Maison entière peut s'y afficher.", 14);
        titre("Tuiles interrupteur");
        texte("Chaque tuile allume ou éteint un appareil d'un seul appui, sans ouvrir l'app. "
                + "Appui long sur la tuile dans le volet pour revenir ici.", 14);
        for (int i = 1; i <= Maison.NB_TUILES; i++) {
            final int n = i;
            String id = Maison.appareil(this, n);
            bouton("Tuile " + n + " : " + (id == null ? "—" : Maison.nom(this, n)), () -> choisir(n));
        }
        if (Build.VERSION.SDK_INT >= 33) {
            titre("Ajouter au volet");
            texte("Sinon : déroule le volet, crayon ✎ (Modifier), puis glisse les tuiles Maison.", 14);
            ajout(TuileTele.class, "Télécommande", R.drawable.ic_tele);
            ajout(TuileMaison.class, "Maison", R.drawable.ic_maison);
            for (int i = 0; i < Maison.NB_TUILES; i++) {
                ajout(TuileAppareil.CLASSES[i], Maison.nom(this, i + 1), R.drawable.ic_ampoule);
            }
        } else {
            titre("Ajouter au volet");
            texte("Déroule le volet, touche ✎ (Modifier) puis glisse les tuiles Maison à l'endroit voulu.", 14);
        }
    }

    @android.annotation.TargetApi(33)
    private void ajout(Class<?> classe, String nom, int icone) {
        bouton("＋ " + nom, () -> {
            StatusBarManager sbm = getSystemService(StatusBarManager.class);
            sbm.requestAddTileService(new ComponentName(this, classe), nom,
                    Icon.createWithResource(this, icone), getMainExecutor(), r -> { });
        });
    }

    /** Liste des appareils pilotables (capacité switch), puis affectation à la tuile n. */
    private void choisir(int n) {
        if (Maison.cookie(this).isEmpty()) return;
        if (!appareils.isEmpty()) { dialogue(n); return; }
        Toast.makeText(this, "Chargement des appareils…", Toast.LENGTH_SHORT).show();
        Maison.RESEAU.execute(() -> {
            try {
                JSONArray items = new JSONObject(Maison.st(this, "devices", null)).getJSONArray("items");
                List<String[]> l = new ArrayList<>();
                for (int i = 0; i < items.length(); i++) {
                    JSONObject d = items.getJSONObject(i);
                    if (!aSwitch(d)) continue;
                    String nom = d.optString("label", d.optString("name", "Appareil"));
                    l.add(new String[] { d.getString("deviceId"), nom.isEmpty() ? d.optString("name") : nom });
                }
                l.sort((a, b) -> a[1].compareToIgnoreCase(b[1]));
                runOnUiThread(() -> { appareils.clear(); appareils.addAll(l); dialogue(n); });
            } catch (Exception e) {
                runOnUiThread(() -> Toast.makeText(this, "Impossible de charger les appareils : "
                        + e.getMessage(), Toast.LENGTH_LONG).show());
            }
        });
    }

    private static boolean aSwitch(JSONObject d) {
        JSONArray comps = d.optJSONArray("components");
        if (comps == null) return false;
        for (int i = 0; i < comps.length(); i++) {
            JSONObject c = comps.optJSONObject(i);
            if (c == null || !"main".equals(c.optString("id"))) continue;
            JSONArray caps = c.optJSONArray("capabilities");
            for (int j = 0; caps != null && j < caps.length(); j++) {
                JSONObject cap = caps.optJSONObject(j);
                if (cap != null && "switch".equals(cap.optString("id"))) return true;
            }
        }
        return false;
    }

    private void dialogue(int n) {
        String[] noms = new String[appareils.size() + 1];
        noms[0] = "— Aucun —";
        for (int i = 0; i < appareils.size(); i++) noms[i + 1] = appareils.get(i)[1];
        new AlertDialog.Builder(this)
                .setTitle("Tuile " + n)
                .setItems(noms, (d, which) -> {
                    if (which == 0) Maison.lier(this, n, null, null);
                    else Maison.lier(this, n, appareils.get(which - 1)[0], appareils.get(which - 1)[1]);
                    TileService.requestListeningState(this, new ComponentName(this, TuileAppareil.CLASSES[n - 1]));
                    construire();
                })
                .show();
    }

    /* ------------------------------------------------------- petits widgets */

    private void titre(String t) {
        TextView v = texte(t, 20);
        v.setPadding(0, dp(20), 0, dp(4));
        v.setTextColor(0xFF38BDF8);
    }

    private TextView texte(String t, int sp) {
        TextView v = new TextView(this);
        v.setText(t);
        v.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        v.setTextColor(0xFFE5E7EB);
        v.setPadding(0, dp(6), 0, dp(6));
        liste.addView(v);
        return v;
    }

    private void bouton(String t, Runnable action) {
        Button b = new Button(this);
        b.setText(t);
        b.setAllCaps(false);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        b.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        b.setMinHeight(dp(56));
        b.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(6);
        liste.addView(b, lp);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
