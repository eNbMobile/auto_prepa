package fr.maison.app;

import android.os.Bundle;
import android.view.Gravity;
import android.view.WindowManager;

/**
 * Grande télécommande flottante, ouverte depuis la carte « Télécommande » (ou
 * la télé) de Contrôle appareil : elle s'affiche par-dessus le volet, en bas
 * de l'écran, et se ferme en touchant à côté.
 */
public class TelecommandeActivity extends MainActivity {

    @Override
    protected void onCreate(Bundle etat) {
        super.onCreate(etat);
        setFinishOnTouchOutside(true);
        int hauteur = Math.round(getResources().getDisplayMetrics().heightPixels * 0.86f);
        getWindow().setLayout(WindowManager.LayoutParams.MATCH_PARENT, hauteur);
        getWindow().setGravity(Gravity.BOTTOM);
    }

    @Override
    protected String vueParDefaut() {
        return "panneau";
    }
}
