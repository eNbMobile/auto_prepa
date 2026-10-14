package fr.maison.app;

/**
 * L'app Maison affichée à l'intérieur du panneau « Contrôle appareil »
 * (déclarée dans le manifeste sur le service Controles) et dans la fenêtre
 * ouverte en touchant la télé. Par défaut elle montre la vue « panneau » :
 * cartes des lumières et grande télécommande, comme le panneau SmartThings.
 */
public class PanneauActivity extends MainActivity {

    @Override
    protected String vueParDefaut() {
        return "panneau";
    }
}
