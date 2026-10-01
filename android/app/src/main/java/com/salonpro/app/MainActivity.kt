package com.salonpro.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File

private const val SALON_PRO_URL = "https://salon-pro-pl4h.onrender.com/"
private const val APP_VERSION = "1.0.8"
private const val APP_VERSION_CODE = 9
private const val SESSION_PREFS = "salon_pro_auth"
private const val SESSION_COOKIE_KEY = "session_cookie"
private const val FILE_CHOOSER_REQUEST_CODE = 4201
private const val CAMERA_PERMISSION_REQUEST_CODE = 4202

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var pendingCameraUri: Uri? = null
    private var pendingCameraFile: File? = null

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
                // Draw edge-to-edge. The Salon Pro top bar owns the top safe-area
                // inset so the status bar and app header form one continuous surface.
                view.setPadding(bars.left, 0, bars.right, bars.bottom)
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

            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    view: WebView?,
                    uploadMsg: ValueCallback<Array<Uri>>?,
                    fileChooserParams: FileChooserParams?
                ): Boolean {
                    this@MainActivity.filePathCallback?.onReceiveValue(null)
                    this@MainActivity.filePathCallback = uploadMsg

                    if (uploadMsg == null) {
                        return false
                    }

                    launchPhotoChooser()
                    return true
                }
            }
            webViewClient = object : WebViewClient() {
                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    val currentUrl = url.orEmpty()
                    if (currentUrl.startsWith(SALON_PRO_URL.removeSuffix("/"))) {
                        saveCurrentSessionCookie()
                    }

                    // A real logout or an expired/invalid session eventually
                    // lands on the login page. Remove the device-side backup so
                    // an old cookie can never silently log the user back in.
                    if (currentUrl.contains("/login")) {
                        clearSavedSessionCookie()
                    }
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

            // Keep cached page data conservative, but never clear cookies here.
            // Authentication cookies must survive an app restart.
            clearCache(true)
            clearHistory()
        }

        setContentView(webView)

        // Restore the saved device session first. Only then load Salon Pro so
        // the first request carries the existing authentication cookie.
        restoreSavedSessionCookie {
            webView.loadUrl(SALON_PRO_URL)
        }
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

    private fun launchPhotoChooser() {
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(android.Manifest.permission.CAMERA),
                CAMERA_PERMISSION_REQUEST_CODE
            )
            return
        }

        try {
            pendingCameraFile = File.createTempFile("salon_pro_camera_", ".jpg", cacheDir)
            pendingCameraUri = FileProvider.getUriForFile(
                this,
                "${BuildConfig.APPLICATION_ID}.fileprovider",
                pendingCameraFile!!
            )

            val cameraIntent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, pendingCameraUri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                clipData = android.content.ClipData.newRawUri("Salon Pro camera photo", pendingCameraUri)
            }

            val galleryIntent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "image/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }

            val chooser = Intent.createChooser(galleryIntent, "Choose salon photo").apply {
                putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(cameraIntent))
            }

            startActivityForResult(chooser, FILE_CHOOSER_REQUEST_CODE)
        } catch (e: Exception) {
            filePathCallback?.onReceiveValue(null)
            filePathCallback = null
            pendingCameraUri = null
            pendingCameraFile = null
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)

        if (requestCode == CAMERA_PERMISSION_REQUEST_CODE) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                launchPhotoChooser()
            } else {
                filePathCallback?.onReceiveValue(null)
                filePathCallback = null
            }
        }
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)

        if (requestCode != FILE_CHOOSER_REQUEST_CODE) return

        val results: Array<Uri>? = when {
            resultCode != Activity.RESULT_OK -> null
            data?.data != null -> arrayOf(data.data!!)
            pendingCameraUri != null -> arrayOf(pendingCameraUri!!)
            else -> null
        }

        filePathCallback?.onReceiveValue(results)
        filePathCallback = null

        val tempFile = pendingCameraFile
        pendingCameraUri = null
        pendingCameraFile = null

        // Give Chromium time to consume the URI before cleaning up the temporary
        // camera file.
        if (tempFile != null) {
            Handler(Looper.getMainLooper()).postDelayed({
                runCatching { tempFile.delete() }
            }, 60_000)
        }
    }

    override fun onPause() {
        // Persist WebView cookies before the Android activity is suspended.
        saveCurrentSessionCookie()
        CookieManager.getInstance().flush()
        super.onPause()
    }

    private fun sessionPrefs() =
        getSharedPreferences(SESSION_PREFS, Context.MODE_PRIVATE)

    private fun saveCurrentSessionCookie() {
        val cookie = CookieManager.getInstance().getCookie(SALON_PRO_URL).orEmpty()
        val sessionCookie = cookie.split(";")
            .map { it.trim() }
            .firstOrNull { it.startsWith("session=") }

        if (!sessionCookie.isNullOrBlank()) {
            sessionPrefs().edit().putString(SESSION_COOKIE_KEY, sessionCookie).apply()
        }
    }

    private fun restoreSavedSessionCookie(onComplete: () -> Unit) {
        val savedCookie = sessionPrefs().getString(SESSION_COOKIE_KEY, null)
        CookieManager.getInstance().setAcceptCookie(true)

        if (savedCookie.isNullOrBlank()) {
            onComplete()
            return
        }

        CookieManager.getInstance().setCookie(
            SALON_PRO_URL,
            savedCookie
        ) {
            CookieManager.getInstance().flush()
            onComplete()
        }
    }

    private fun clearSavedSessionCookie() {
        sessionPrefs().edit().remove(SESSION_COOKIE_KEY).apply()
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        // Match the expected mobile-drawer behavior: the first Android Back
        // closes the open Salon Pro navigation drawer; only a second Back
        // navigates the WebView history or exits the app.
        webView.evaluateJavascript(
            "(function(){return !!(window.SalonProSidebar && window.SalonProSidebar.isOpen && window.SalonProSidebar.isOpen());})()"
        ) { result ->
            if (result == "true") {
                webView.evaluateJavascript(
                    "(function(){if(window.SalonProSidebar && window.SalonProSidebar.close){window.SalonProSidebar.close();} return true;})()",
                    null
                )
                return@evaluateJavascript
            }

            if (webView.canGoBack()) {
                webView.goBack()
            } else {
                super.onBackPressed()
            }
        }
    }
}
