package jp.co.cyberagent.stf;

import android.os.Bundle;
import android.view.Window;
import android.view.WindowManager;

import com.journeyapps.barcodescanner.CaptureActivity;
import com.journeyapps.barcodescanner.DecoratedBarcodeView;

/**
 * Custom QR scan activity:
 *  - Portrait orientation (enforced via manifest screenOrientation)
 *  - Full-screen immersive camera
 *  - Custom layout with header/footer overlays
 */
public class QrCaptureActivity extends CaptureActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        super.onCreate(savedInstanceState);
    }

    /**
     * ZXing 4.x uses initializeContent() instead of getLayoutId().
     * Called by CaptureActivity.onCreate() to set the content view.
     */
    @Override
    protected DecoratedBarcodeView initializeContent() {
        setContentView(R.layout.activity_qr_capture);
        return (DecoratedBarcodeView) findViewById(R.id.zxing_barcode_scanner);
    }
}
