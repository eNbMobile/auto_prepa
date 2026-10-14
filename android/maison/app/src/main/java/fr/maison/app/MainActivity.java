package fr.maison.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * La PWA Maison dans une WebView.
 *
 * Après chaque page chargée, le cookie de session est recopié pour que les
 * tuiles du volet rapide puissent appeler le worker sans ouvrir l'app.
 * L'extra « vue » (favoris, tele, scenes…) choisit l'écran affiché.
 */
public class MainActivity extends Activity {

    private WebView web;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle etat) {
        super.onCreate(etat);
        web = new WebView(this);
        web.setBackgroundColor(0xFF111827);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView v, String url) {
                CookieManager cm = CookieManager.getInstance();
                cm.flush();
                Maison.sauverCookie(MainActivity.this, cm.getCookie(Maison.BASE));
            }
        });
        setContentView(web);
        // Télécommande automatique : relancée à chaque ouverture si elle est activée.
        ServiceTele.relancerSiActif(this);
        if (etat != null) web.restoreState(etat);
        else web.loadUrl(Maison.BASE + "/" + fragment(getIntent()));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String f = fragment(intent);
        if (!f.isEmpty()) web.evaluateJavascript("location.hash='" + f + "'", null);
    }

    /** Vue ouverte quand l'intent n'en précise pas (PanneauActivity : le panneau). */
    protected String vueParDefaut() {
        return null;
    }

    private String fragment(Intent i) {
        String vue = i == null ? null : i.getStringExtra("vue");
        if (vue == null) vue = vueParDefaut();
        return vue != null && vue.matches("[a-z]+") ? "#" + vue : "";
    }

    @Override
    protected void onSaveInstanceState(Bundle etat) {
        super.onSaveInstanceState(etat);
        web.saveState(etat);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
