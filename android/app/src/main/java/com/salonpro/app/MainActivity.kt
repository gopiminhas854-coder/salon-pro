package com.salonpro.app

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

private const val SALON_PRO_URL = "https://salon-pro-pl4h.onrender.com/"
private const val APP_VERSION = "1.0.2"

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        webView = WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                setSupportZoom(false)
                cacheMode = WebSettings.LOAD_NO_CACHE
                userAgentString = "$userAgentString SalonProAndroid/$APP_VERSION"
            }

            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                }

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

                @Suppress("OVERRIDE_DEPRECATION")
                override fun onReceivedError(
                    view: WebView?,
                    errorCode: Int,
                    description: String?,
                    failingUrl: String?
                ) {
                    super.onReceivedError(view, errorCode, description, failingUrl)
                    showLoadError()
                }
            }

            clearCache(true)
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
                <p>Please check your internet connection and try again.</p>
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

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
