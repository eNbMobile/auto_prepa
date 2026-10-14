package fr.maison.app;

import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.TileService;

/** Ouverture d'une activité depuis une tuile, en refermant le volet. */
final class Tuiles {

    private Tuiles() {}

    @SuppressWarnings("deprecation")
    static void ouvrir(TileService service, Intent intent, int code) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        Runnable go = () -> {
            if (Build.VERSION.SDK_INT >= 34) {
                service.startActivityAndCollapse(PendingIntent.getActivity(service, code, intent,
                        PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
            } else {
                service.startActivityAndCollapse(intent);
            }
        };
        if (service.isLocked()) service.unlockAndRun(go);
        else go.run();
    }
}
