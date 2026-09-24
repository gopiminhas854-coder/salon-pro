package com.salonpro.app

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.graphics.Color
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat

private const val SALON_PRO_URL = "https://salon-pro-pl4h.onrender.com/login"
private const val APP_VERSION = "1.0.5"

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Android 15+ can enforce edge-to-edge for apps targeting SDK 35.
        // Keep the WebView content clear of the status/navigation bars so the
        // Salon Pro top bar is never clipped in the native APK.
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            isAppearanceLightNavigationBars = true
        }

        webView = WebView(this).apply {
            setBackgroundColor(Color.WHITE)
            ViewCompat.setOnApplyWindowInsetsListener(this) { view, insets ->
                val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                setSupportZoom(false)
                cacheMode = WebSettings.LOAD_NO_CACHE
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                javaScriptCanOpenWindowsAutomatically = true
                setSupportMultipleWindows(false)
                loadsImagesAutomatically = true
                allowFileAccess = false
                allowContentAccess = true

                // Web servers can reject Android WebView's default "; wv" marker.
                // Keep the real Chrome version while presenting a browser-compatible UA.
                val chromeUa = userAgentString
                    .replace("; wv", "")
                    .replace("Version/4.0 ", "")
                    .replace(Regex("\\s+SalonProAndroid/[^\\s]+"), "")
                userAgentString = "$chromeUa SalonProAndroid/$APP_VERSION"
            }

            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                }

                // Only treat actual network-level failures as connection failures.
                // HTTP 4xx/5xx responses are allowed to render their response body,
                // so the app does not replace useful server diagnostics with a
                // generic "could not connect" page.
                override fun onReceivedError(
                    view: WebView?,
                    request: WebResourceRequest?,
                    error: WebResourceError?
                ) {
                    super.onReceivedError(view, request, error)
                    if (request?.isForMainFrame == true) {
                        showLoadError()
                    }
                }
            }

            clearCache(true)
            clearHistory()
            loadUrl(SALON_PRO_URL)
        }

        setContentView(webView)
    }

    private fun showLoadError() {
        val html = """
            <!doctype html>
            <html>
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <body style="font-family:sans-serif;padding:32px;text-align:center;">
                <h2>Salon Pro could not connect</h2>
                <p>There was a network-level WebView connection error.</p>
                <button onclick="location.href='$SALON_PRO_URL'">Retry Salon Pro</button>
              </body>
            </html>
        """.trimIndent()

        webView.post {
            webView.loadDataWithBaseURL(
                SALON_PRO_URL,
                html,
                "text/html",
                "UTF-8",
                null
            )
        }
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
