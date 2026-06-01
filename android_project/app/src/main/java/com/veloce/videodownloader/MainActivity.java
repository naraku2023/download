package com.veloce.videodownloader;

import android.annotation.SuppressLint;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.google.android.material.bottomsheet.BottomSheetDialog;
import com.google.android.material.floatingactionbutton.FloatingActionButton;
import com.google.android.material.snackbar.Snackbar;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends AppCompatActivity {
    private final List<WebView> webViewList = new ArrayList<>();
    private int currentTabIndex = -1;
    private android.widget.FrameLayout browserContainer;
    
    private WebView downloadsWebView;
    private WebView settingsWebView;
    private LinearLayout topBar;
    private EditText urlInput;
    private ImageButton btnBack;
    private ImageButton btnRefresh;
    private ImageButton btnGo;
    private FloatingActionButton downloadFab;
    private BottomNavigationView bottomNavigationView;
    
    private android.widget.FrameLayout btnTabsContainer;
    private android.widget.ImageButton btnTabs;
    private TextView txtTabCount;
    
    private final List<String> detectedVideoUrls = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // Request runtime storage permissions for download folder write authorization
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
            if (checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE,
                    android.Manifest.permission.READ_EXTERNAL_STORAGE
                }, 100);
            }
        }

        // 1. Initialize Views
        browserContainer = findViewById(R.id.browser_container);
        downloadsWebView = findViewById(R.id.downloads_webview);
        settingsWebView = findViewById(R.id.settings_webview);
        topBar = findViewById(R.id.top_bar);
        urlInput = findViewById(R.id.url_input);
        btnBack = findViewById(R.id.btn_back);
        btnRefresh = findViewById(R.id.btn_refresh);
        btnGo = findViewById(R.id.btn_go);
        downloadFab = findViewById(R.id.download_fab);
        bottomNavigationView = findViewById(R.id.bottom_navigation);
        
        btnTabsContainer = findViewById(R.id.btn_tabs_container);
        btnTabs = findViewById(R.id.btn_tabs);
        txtTabCount = findViewById(R.id.txt_tab_count);
        
        // Programmatically style tab count bubble badge for rich visuals
        android.graphics.drawable.GradientDrawable badgeGd = new android.graphics.drawable.GradientDrawable();
        badgeGd.setColor(0xFFFF3B30); // Neon reddish-orange highlight
        badgeGd.setCornerRadius(99f);
        txtTabCount.setBackground(badgeGd);

        // 2. Start Python Flask server
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }
        new Thread(() -> {
            Python py = Python.getInstance();
            try {
                py.getModule("app").callAttr("run_server");
            } catch (Exception e) {
                e.printStackTrace();
            }
        }).start();

        // 3. Setup Split Views WebViews
        setupWebViews();

        // 4. Set Navigation Controls & Handlers
        btnBack.setOnClickListener(v -> {
            WebView active = getActiveWebView();
            if (active != null && active.canGoBack()) {
                active.goBack();
            }
        });

        btnRefresh.setOnClickListener(v -> {
            WebView active = getActiveWebView();
            if (active != null) {
                active.reload();
                Toast.makeText(MainActivity.this, "🔄 正在刷新页面...", Toast.LENGTH_SHORT).show();
            }
        });

        btnGo.setOnClickListener(v -> navigateToInputUrl());

        urlInput.setOnKeyListener((v, keyCode, event) -> {
            if (event.getAction() == KeyEvent.ACTION_DOWN && keyCode == KeyEvent.KEYCODE_ENTER) {
                navigateToInputUrl();
                return true;
            }
            return false;
        });

        btnTabs.setOnClickListener(v -> showTabSwitcherDialog());

        // 5. Native Edge-swipe / System Back Gesture Handler
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (bottomNavigationView.getSelectedItemId() == R.id.nav_browser) {
                    WebView active = getActiveWebView();
                    if (active != null && active.canGoBack()) {
                        active.goBack();
                    } else {
                        finish(); // Exit App
                    }
                } else {
                    bottomNavigationView.setSelectedItemId(R.id.nav_browser);
                }
            }
        });

        // 6. Bottom Navigation Three Tabs Switching
        bottomNavigationView.setOnItemSelectedListener(item -> {
            int itemId = item.getItemId();
            if (itemId == R.id.nav_browser) {
                topBar.setVisibility(View.VISIBLE);
                browserContainer.setVisibility(View.VISIBLE);
                downloadsWebView.setVisibility(View.GONE);
                settingsWebView.setVisibility(View.GONE);
                
                WebView active = getActiveWebView();
                if (active != null && (!detectedVideoUrls.isEmpty() || isPopularVideoPlatform(active.getUrl()))) {
                    downloadFab.show();
                }
                return true;
            } else if (itemId == R.id.nav_downloads) {
                topBar.setVisibility(View.GONE);
                browserContainer.setVisibility(View.GONE);
                downloadsWebView.setVisibility(View.VISIBLE);
                settingsWebView.setVisibility(View.GONE);
                downloadFab.hide();
                downloadsWebView.loadUrl("file:///android_asset/index.html?view=downloads");
                return true;
            } else if (itemId == R.id.nav_settings) {
                topBar.setVisibility(View.GONE);
                browserContainer.setVisibility(View.GONE);
                downloadsWebView.setVisibility(View.GONE);
                settingsWebView.setVisibility(View.VISIBLE);
                downloadFab.hide();
                settingsWebView.loadUrl("file:///android_asset/index.html?view=settings");
                return true;
            }
            return false;
        });

        // 7. FAB Highlights & BottomSheet Trigger
        downloadFab.setOnClickListener(v -> {
            WebView active = getActiveWebView();
            if (active != null) {
                String currentUrl = active.getUrl();
                if (currentUrl != null) {
                    if (isPopularVideoPlatform(currentUrl)) {
                        Toast.makeText(MainActivity.this, "🔍 正在深度解析网页视频...", Toast.LENGTH_SHORT).show();
                        fetchVideoMetadata(currentUrl);
                    } else if (!detectedVideoUrls.isEmpty()) {
                        String directUrl = detectedVideoUrls.get(0);
                        Toast.makeText(MainActivity.this, "⚡ 已拦截底层视频流，正在计算文件大小...", Toast.LENGTH_SHORT).show();
                        fetchSniffedMetadata(currentUrl, directUrl, active.getTitle());
                    } else {
                        Toast.makeText(MainActivity.this, "🔍 正在深度解析网页视频...", Toast.LENGTH_SHORT).show();
                        fetchVideoMetadata(currentUrl);
                    }
                }
            }
        });
    }

    @Override
    protected void onPause() {
        super.onPause();
        saveSessionState();
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebViews() {
        // Setup Downloads dashboard WebView
        WebSettings downloadSettings = downloadsWebView.getSettings();
        downloadSettings.setJavaScriptEnabled(true);
        downloadSettings.setDomStorageEnabled(true);
        downloadSettings.setAllowFileAccess(true);
        downloadSettings.setAllowContentAccess(true);
        downloadSettings.setAllowUniversalAccessFromFileURLs(true);
        downloadSettings.setAllowFileAccessFromFileURLs(true);
        downloadsWebView.setWebViewClient(new WebViewClient());

        // Setup Settings WebView
        WebSettings settingsSettings = settingsWebView.getSettings();
        settingsSettings.setJavaScriptEnabled(true);
        settingsSettings.setDomStorageEnabled(true);
        settingsSettings.setAllowFileAccess(true);
        settingsSettings.setAllowContentAccess(true);
        settingsSettings.setAllowUniversalAccessFromFileURLs(true);
        settingsSettings.setAllowFileAccessFromFileURLs(true);
        settingsWebView.setWebViewClient(new WebViewClient());

        // Register secure Javascript interface bridges on non-browser WebViews
        AndroidBridge bridge = new AndroidBridge();
        downloadsWebView.addJavascriptInterface(bridge, "AndroidBridge");
        settingsWebView.addJavascriptInterface(bridge, "AndroidBridge");

        // Restore past browser tabs or start default homepage
        restoreSessionState();
    }

    private boolean isPopularVideoPlatform(String url) {
        if (url == null) return false;
        String lower = url.toLowerCase();
        return lower.contains("youtube.com") || lower.contains("youtu.be") || 
               lower.contains("bilibili.com") || lower.contains("twitter.com") || 
               lower.contains("x.com") || lower.contains("tiktok.com") || 
               lower.contains("rou.video") || lower.contains("instagram.com") ||
               lower.contains("hsex.tv") || lower.contains("91porn.com") ||
               lower.contains("91prony.com") || lower.contains("91porn");
    }

    private void navigateToInputUrl() {
        String input = urlInput.getText().toString().trim();
        if (input.isEmpty()) return;

        if (!input.startsWith("http://") && !input.startsWith("https://")) {
            if (input.contains(".") && !input.contains(" ")) {
                input = "https://" + input;
            } else {
                input = "https://www.google.com/search?q=" + android.net.Uri.encode(input);
            }
        }
        
        WebView active = getActiveWebView();
        if (active != null) {
            active.loadUrl(input);
        }
    }

    private void updateFabStatus(boolean active) {
        if (active && bottomNavigationView.getSelectedItemId() == R.id.nav_browser) {
            downloadFab.show();
        } else {
            downloadFab.hide();
        }
    }

    // === 异步直链流大小侦测与弹窗加载器 ===
    private void fetchSniffedMetadata(String webpageUrl, String directUrl, String pageTitle) {
        new Thread(() -> {
            String size = "未知大小";
            try {
                URL url = new URL(directUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("HEAD");
                
                WebView active = getActiveWebView();
                String ua = active != null ? active.getSettings().getUserAgentString() : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
                conn.setRequestProperty("User-Agent", ua);
                conn.setRequestProperty("Referer", webpageUrl);
                
                String cookies = android.webkit.CookieManager.getInstance().getCookie(webpageUrl);
                if (cookies != null) {
                    conn.setRequestProperty("Cookie", cookies);
                }
                
                conn.setConnectTimeout(6000);
                conn.setReadTimeout(6000);
                
                long length = conn.getContentLengthLong();
                if (length > 0) {
                    if (length > 1024 * 1024 * 1024) {
                        size = String.format("%.2f GB", (double) length / (1024 * 1024 * 1024));
                    } else {
                        size = String.format("%.1f MB", (double) length / (1024 * 1024));
                    }
                }
            } catch (Exception e) {
                e.printStackTrace();
            }

            final String finalSize = size;
            String platform = "网页直链视频";
            if (directUrl.contains(".m3u8")) {
                platform = "HLS 流媒体";
            }
            final String finalPlatform = platform;
            
            runOnUiThread(() -> showBottomSheet(webpageUrl, directUrl, pageTitle, "网页嗅探器", finalPlatform, "", finalSize, "sniffed_direct"));
        }).start();
    }

    // === Async Metadata Loader from local Python Server ===
    private void fetchVideoMetadata(String videoUrl) {
        WebView active = getActiveWebView();
        final String ua = active != null ? active.getSettings().getUserAgentString() : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
        String cookies = android.webkit.CookieManager.getInstance().getCookie(videoUrl);
        final String finalCookies = cookies != null ? cookies : "";

        new Thread(() -> {
            try {
                URL url = new URL("http://127.0.0.1:5000/api/analyze");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json; utf-8");
                conn.setRequestProperty("Accept", "application/json");
                conn.setDoOutput(true);

                JSONObject payload = new JSONObject();
                payload.put("url", videoUrl);
                if (!finalCookies.isEmpty()) {
                    payload.put("cookies", finalCookies);
                }
                if (!ua.isEmpty()) {
                    payload.put("user_agent", ua);
                }

                try (OutputStream os = conn.getOutputStream()) {
                    byte[] input = payload.toString().getBytes("utf-8");
                    os.write(input, 0, input.length);			
                }

                BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), "utf-8"));
                StringBuilder response = new StringBuilder();
                String responseLine;
                while ((responseLine = br.readLine()) != null) {
                    response.append(responseLine.trim());
                }
                
                JSONObject jsonObj = new JSONObject(response.toString());
                if (jsonObj.getBoolean("success")) {
                    JSONObject metadata = jsonObj.getJSONObject("metadata");
                    String title = metadata.optString("title", "未知视频");
                    String author = metadata.optString("author", "未知作者");
                    String platform = metadata.optString("platform", "网页视频");
                    String thumbnail = metadata.optString("thumbnail", "");
                    
                    JSONArray formats = metadata.optJSONArray("formats");
                    String size = "未知大小";
                    String formatId = "";
                    if (formats != null && formats.length() > 0) {
                        JSONObject bestFormat = formats.optJSONObject(0);
                        if (bestFormat != null) {
                            size = bestFormat.optString("size", "未知大小");
                            formatId = bestFormat.optString("format_id", "");
                        }
                    }
                    
                    final String finalTitle = title;
                    final String finalAuthor = author;
                    final String finalPlatform = platform;
                    final String finalThumbnail = thumbnail;
                    final String finalSize = size;
                    final String finalFormatId = formatId;
                    
                    runOnUiThread(() -> showBottomSheet(videoUrl, "", finalTitle, finalAuthor, finalPlatform, finalThumbnail, finalSize, finalFormatId));
                } else {
                    handleMetadataFailure(videoUrl, active);
                }
            } catch (Exception e) {
                e.printStackTrace();
                handleMetadataFailure(videoUrl, active);
            }
        }).start();
    }

    private void handleMetadataFailure(String videoUrl, WebView active) {
        runOnUiThread(() -> {
            if (detectedVideoUrls != null && !detectedVideoUrls.isEmpty()) {
                String directUrl = detectedVideoUrls.get(0);
                Toast.makeText(MainActivity.this, "⚠️ 深度解析未就绪，正在尝试用拦截的直链下载...", Toast.LENGTH_SHORT).show();
                fetchSniffedMetadata(videoUrl, directUrl, active != null ? active.getTitle() : "网页视频");
            } else {
                Toast.makeText(MainActivity.this, "深度解析解析失败，建议刷新网页或复制网址解析", Toast.LENGTH_SHORT).show();
            }
        });
    }

    // === Custom BottomSheet Dialog Creator ===
    private void showBottomSheet(String webpageUrl, String directUrl, String title, String author, String platform, String thumbnailUrl, String size, String formatOrSniffedId) {
        BottomSheetDialog bottomSheetDialog = new BottomSheetDialog(MainActivity.this);
        View dialogView = getLayoutInflater().inflate(R.layout.dialog_video_info, null);
        bottomSheetDialog.setContentView(dialogView);

        TextView txtTitle = dialogView.findViewById(R.id.dialog_video_title);
        TextView txtAuthor = dialogView.findViewById(R.id.dialog_video_author);
        TextView txtPlatform = dialogView.findViewById(R.id.dialog_video_platform);
        TextView txtSize = dialogView.findViewById(R.id.dialog_video_size);
        ImageView imgThumbnail = dialogView.findViewById(R.id.dialog_video_thumbnail);
        Button btnConfirm = dialogView.findViewById(R.id.dialog_btn_confirm_download);

        txtTitle.setText(title);
        txtAuthor.setText("来源: " + author);
        txtPlatform.setText(platform);
        txtSize.setText(size);

        // Load Thumbnail via local Python proxy to completely bypass 403 hotlink blocks
        if (thumbnailUrl != null && !thumbnailUrl.isEmpty()) {
            WebView active = getActiveWebView();
            final String ua = active != null ? active.getSettings().getUserAgentString() : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
            final String cookies = android.webkit.CookieManager.getInstance().getCookie(webpageUrl);

            new Thread(() -> {
                try {
                    String finalThumbUrl = thumbnailUrl;
                    if (thumbnailUrl.startsWith("/")) {
                        finalThumbUrl = "http://127.0.0.1:5000" + thumbnailUrl;
                    } else if (thumbnailUrl.startsWith("http")) {
                        // Proxy remote cover image through local python proxy to completely bypass all 403 hotlink blocks
                        String encUrl = android.net.Uri.encode(thumbnailUrl);
                        String encReferer = android.net.Uri.encode(webpageUrl != null ? webpageUrl : "");
                        String encCookies = android.net.Uri.encode(cookies != null ? cookies : "");
                        String encUa = android.net.Uri.encode(ua != null ? ua : "");
                        finalThumbUrl = "http://127.0.0.1:5000/api/proxy_image?url=" + encUrl + 
                                         "&referer=" + encReferer + 
                                         "&cookies=" + encCookies + 
                                         "&ua=" + encUa;
                    }
                    
                    URL url = new URL(finalThumbUrl);
                    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                    conn.setRequestMethod("GET");
                    conn.setConnectTimeout(8000);
                    conn.setReadTimeout(8000);
                    
                    try (InputStream in = conn.getInputStream()) {
                        Bitmap bmp = BitmapFactory.decodeStream(in);
                        runOnUiThread(() -> imgThumbnail.setImageBitmap(bmp));
                    }
                } catch (Exception e) {
                    e.printStackTrace();
                    runOnUiThread(() -> imgThumbnail.setImageResource(android.R.drawable.ic_media_play));
                }
            }).start();
        } else {
            imgThumbnail.setImageResource(android.R.drawable.ic_media_play);
        }

        btnConfirm.setOnClickListener(v -> {
            bottomSheetDialog.dismiss();
            if ("sniffed_direct".equals(formatOrSniffedId)) {
                startDownloadTask(webpageUrl, directUrl, "", title, thumbnailUrl, platform, size);
            } else {
                startDownloadTask(webpageUrl, "", formatOrSniffedId, title, thumbnailUrl, platform, size);
            }
        });

        bottomSheetDialog.show();
    }

    // === Async Download Trigger ===
    private void startDownloadTask(String webpageUrl, String directUrl, String formatId, String title, String thumbnail, String platform, String size) {
        WebView active = getActiveWebView();
        final String ua = active != null ? active.getSettings().getUserAgentString() : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
        String cookies = android.webkit.CookieManager.getInstance().getCookie(webpageUrl);
        final String finalCookies = cookies != null ? cookies : "";

        new Thread(() -> {
            try {
                URL url = new URL("http://127.0.0.1:5000/api/download");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json; utf-8");
                conn.setDoOutput(true);

                JSONObject payload = new JSONObject();
                payload.put("url", webpageUrl);
                payload.put("direct_url", directUrl);
                payload.put("format_id", formatId);
                payload.put("title", title);
                payload.put("thumbnail", thumbnail);
                payload.put("platform", platform);
                payload.put("size", size);
                if (!finalCookies.isEmpty()) {
                    payload.put("cookies", finalCookies);
                }
                if (!ua.isEmpty()) {
                    payload.put("user_agent", ua);
                }

                try (OutputStream os = conn.getOutputStream()) {
                    byte[] input = payload.toString().getBytes("utf-8");
                    os.write(input, 0, input.length);			
                }

                int code = conn.getResponseCode();
                runOnUiThread(() -> {
                    if (code == 200) {
                        Snackbar.make(
                            bottomNavigationView, 
                            "🚀 任务已成功加入下载队列！", 
                            5000
                        ).setAction("去查看", v -> {
                            bottomNavigationView.setSelectedItemId(R.id.nav_downloads);
                        }).show();
                    } else {
                        Toast.makeText(MainActivity.this, "下载任务启动失败", Toast.LENGTH_SHORT).show();
                    }
                });
            } catch (Exception e) {
                e.printStackTrace();
                runOnUiThread(() -> Toast.makeText(MainActivity.this, "下载任务发起异常，请检查后台服务", Toast.LENGTH_SHORT).show());
            }
        }).start();
    }

    // === Secure JavaScript Bridge Class (JS 通信桥接类) ===
    public class AndroidBridge {
        @android.webkit.JavascriptInterface
        public void playVideo(String filepath) {
            runOnUiThread(() -> androidPlayVideo(filepath));
        }

        @android.webkit.JavascriptInterface
        public void openFolder() {
            runOnUiThread(() -> androidOpenFolder());
        }

        @android.webkit.JavascriptInterface
        public void openBrowserUrl(String url) {
            runOnUiThread(() -> {
                bottomNavigationView.setSelectedItemId(R.id.nav_browser);
                WebView active = getActiveWebView();
                if (active != null) {
                    active.loadUrl(url);
                }
            });
        }
    }

    // === Android Native Video Player Launcher ===
    private void androidPlayVideo(String filepath) {
        try {
            java.io.File file = new java.io.File(filepath);
            if (!file.exists()) {
                Toast.makeText(MainActivity.this, "视频文件不存在或已被删除", Toast.LENGTH_SHORT).show();
                return;
            }
            
            android.net.Uri fileUri;
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.N) {
                fileUri = androidx.core.content.FileProvider.getUriForFile(
                    MainActivity.this, 
                    getApplicationContext().getPackageName() + ".fileprovider", 
                    file
                );
            } else {
                fileUri = android.net.Uri.fromFile(file);
            }

            android.content.Intent intent = new android.content.Intent(android.content.Intent.ACTION_VIEW);
            intent.setDataAndType(fileUri, "video/*");
            intent.addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(intent);
        } catch (Exception e) {
            e.printStackTrace();
            Toast.makeText(MainActivity.this, "未能找到匹配的视频播放器", Toast.LENGTH_SHORT).show();
        }
    }

    // === Android Native File Explorer Launcher ===
    private void androidOpenFolder() {
        try {
            android.content.Intent intent = new android.content.Intent(android.content.Intent.ACTION_GET_CONTENT);
            android.net.Uri uri = android.net.Uri.parse(android.os.Environment.getExternalStoragePublicDirectory(
                android.os.Environment.DIRECTORY_DOWNLOADS).getPath() + "/VeloceDownloads");
            intent.setDataAndType(uri, "*/*");
            startActivity(android.content.Intent.createChooser(intent, "打开下载文件夹"));
        } catch (Exception e) {
            e.printStackTrace();
            try {
                android.content.Intent intent = new android.content.Intent(android.content.Intent.ACTION_VIEW);
                intent.setDataAndType(android.net.Uri.parse("content://media/external/file"), "*/*");
                startActivity(intent);
            } catch (Exception ex) {
                Toast.makeText(MainActivity.this, "未能找到合适的文件管理器", Toast.LENGTH_SHORT).show();
            }
        }
    }

    // === Multi-Tab Management & Session Persistence Core ===
    
    @SuppressLint("SetJavaScriptEnabled")
    private WebView createNewTabWebView(String url) {
        WebView webView = new WebView(this);
        webView.setLayoutParams(new android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT
        ));
        
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setAllowUniversalAccessFromFileURLs(true);
        settings.setAllowFileAccessFromFileURLs(true);
        
        // Add JavaScript communication bridge
        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");
        
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String pageUrl, android.graphics.Bitmap favicon) {
                super.onPageStarted(view, pageUrl, favicon);
                if (view == getActiveWebView()) {
                    if (pageUrl != null && pageUrl.startsWith("file:///android_asset")) {
                        urlInput.setText("");
                    } else {
                        urlInput.setText(pageUrl);
                    }
                    detectedVideoUrls.clear();
                    updateFabStatus(false);
                }
            }

            @Override
            public void onPageFinished(WebView view, String pageUrl) {
                super.onPageFinished(view, pageUrl);
                saveSessionState();
                
                if (view == getActiveWebView()) {
                    btnBack.setEnabled(view.canGoBack());
                    if (!pageUrl.startsWith("file:///android_asset")) {
                        if (isPopularVideoPlatform(pageUrl)) {
                            updateFabStatus(true);
                        }
                    }
                }
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String reqUrl = request.getUrl().toString();
                String lowerUrl = reqUrl.toLowerCase();
                // Intercept actual index streams and full media assets, ignore ad trackers / html paths / HLS chunk fragments
                if (lowerUrl.contains(".mp4") || lowerUrl.contains(".m3u8") || 
                    lowerUrl.contains(".flv") || lowerUrl.contains("ext=mp4") ||
                    lowerUrl.contains(".webm") || lowerUrl.contains(".mkv") ||
                    lowerUrl.contains(".mov") || lowerUrl.contains(".mp3") ||
                    lowerUrl.contains(".m4a")) {
                    if (!detectedVideoUrls.contains(reqUrl)) {
                        detectedVideoUrls.add(reqUrl);
                        runOnUiThread(() -> {
                            if (view == getActiveWebView()) {
                                updateFabStatus(true);
                            }
                        });
                    }
                }
                return super.shouldInterceptRequest(view, request);
            }
        });
        
        webView.loadUrl(url);
        return webView;
    }

    private WebView getActiveWebView() {
        if (currentTabIndex >= 0 && currentTabIndex < webViewList.size()) {
            return webViewList.get(currentTabIndex);
        }
        return null;
    }

    private void switchTab(int index) {
        if (index < 0 || index >= webViewList.size()) return;
        
        // Hide all WebViews
        for (int i = 0; i < webViewList.size(); i++) {
            webViewList.get(i).setVisibility(View.GONE);
        }
        
        currentTabIndex = index;
        WebView activeWebView = webViewList.get(index);
        activeWebView.setVisibility(View.VISIBLE);
        
        // Update URL Input text
        String currentUrl = activeWebView.getUrl();
        if (currentUrl != null && currentUrl.startsWith("file:///android_asset")) {
            urlInput.setText("");
        } else {
            urlInput.setText(currentUrl != null ? currentUrl : "");
        }
        
        // Sync backward controls
        btnBack.setEnabled(activeWebView.canGoBack());
        
        // Sync FAB state
        detectedVideoUrls.clear();
        if (currentUrl != null && !currentUrl.startsWith("file:///android_asset")) {
            if (isPopularVideoPlatform(currentUrl)) {
                updateFabStatus(true);
            }
        } else {
            updateFabStatus(false);
        }
        
        updateTabCountBadge();
        saveSessionState();
    }

    private void addNewTab(String url) {
        WebView newWebView = createNewTabWebView(url);
        webViewList.add(newWebView);
        browserContainer.addView(newWebView);
        switchTab(webViewList.size() - 1);
    }

    private void closeTab(int index) {
        if (index < 0 || index >= webViewList.size()) return;
        
        WebView webViewToRemove = webViewList.get(index);
        browserContainer.removeView(webViewToRemove);
        webViewToRemove.destroy();
        webViewList.remove(index);
        
        if (webViewList.isEmpty()) {
            addNewTab("file:///android_asset/index.html");
        } else {
            if (currentTabIndex >= webViewList.size()) {
                currentTabIndex = webViewList.size() - 1;
            }
            switchTab(currentTabIndex);
        }
    }

    private void updateTabCountBadge() {
        if (txtTabCount != null) {
            txtTabCount.setText(String.valueOf(webViewList.size()));
        }
    }

    private void saveSessionState() {
        try {
            JSONArray array = new JSONArray();
            for (WebView wv : webViewList) {
                String url = wv.getUrl();
                if (url != null) {
                    array.put(url);
                }
            }
            getSharedPreferences("veloce_browser", MODE_PRIVATE)
                .edit()
                .putString("saved_tabs", array.toString())
                .putInt("active_tab_index", currentTabIndex)
                .apply();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void restoreSessionState() {
        try {
            String savedTabs = getSharedPreferences("veloce_browser", MODE_PRIVATE)
                .getString("saved_tabs", null);
            int activeIndex = getSharedPreferences("veloce_browser", MODE_PRIVATE)
                .getInt("active_tab_index", 0);
                
            if (savedTabs != null) {
                JSONArray array = new JSONArray(savedTabs);
                if (array.length() > 0) {
                    for (int i = 0; i < array.length(); i++) {
                        String url = array.getString(i);
                        WebView webView = createNewTabWebView(url);
                        webViewList.add(webView);
                        browserContainer.addView(webView);
                    }
                    currentTabIndex = Math.min(activeIndex, webViewList.size() - 1);
                    if (currentTabIndex < 0) currentTabIndex = 0;
                    switchTab(currentTabIndex);
                    return;
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        // Fallback: Default to home tab
        addNewTab("file:///android_asset/index.html");
    }

    private void showTabSwitcherDialog() {
        BottomSheetDialog dialog = new BottomSheetDialog(this);
        
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 50, 40, 50);
        root.setBackgroundColor(0xFF1E1E1E); // Slate dark-themed dialog background
        
        TextView title = new TextView(this);
        title.setText("📑 浏览器标签管理");
        title.setTextColor(0xFFFFFFFF);
        title.setTextSize(18);
        title.setPadding(0, 0, 0, 32);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        root.addView(title);
        
        android.widget.ScrollView scrollView = new android.widget.ScrollView(this);
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1.0f);
        scrollView.setLayoutParams(scrollParams);
        
        LinearLayout listContainer = new LinearLayout(this);
        listContainer.setOrientation(LinearLayout.VERTICAL);
        
        for (int i = 0; i < webViewList.size(); i++) {
            final int index = i;
            WebView wv = webViewList.get(i);
            String tabTitleStr = wv.getTitle();
            String tabUrlStr = wv.getUrl();
            
            if (tabTitleStr == null || tabTitleStr.isEmpty()) {
                tabTitleStr = "新标签页";
            }
            if (tabUrlStr != null && tabUrlStr.startsWith("file:///android_asset")) {
                tabTitleStr = "Veloce 极速视频首页";
                tabUrlStr = "导航主页";
            }
            
            LinearLayout itemLayout = new LinearLayout(this);
            itemLayout.setOrientation(LinearLayout.HORIZONTAL);
            itemLayout.setGravity(android.view.Gravity.CENTER_VERTICAL);
            itemLayout.setPadding(24, 24, 24, 24);
            
            android.graphics.drawable.GradientDrawable itemBg = new android.graphics.drawable.GradientDrawable();
            if (i == currentTabIndex) {
                itemBg.setColor(0xFF2C2C2C);
                itemBg.setStroke(2, 0xFFFF3B30); // Orange-red gradient active border matching our neon look
            } else {
                itemBg.setColor(0xFF252525);
            }
            itemBg.setCornerRadius(16f);
            itemLayout.setBackground(itemBg);
            
            LinearLayout.LayoutParams itemParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            itemParams.setMargins(0, 0, 0, 16);
            itemLayout.setLayoutParams(itemParams);
            
            TextView letterBadge = new TextView(this);
            letterBadge.setText(tabTitleStr.substring(0, Math.min(1, tabTitleStr.length())).toUpperCase());
            letterBadge.setTextColor(0xFFFFFFFF);
            letterBadge.setTextSize(14);
            letterBadge.setGravity(android.view.Gravity.CENTER);
            android.graphics.drawable.GradientDrawable badgeBg = new android.graphics.drawable.GradientDrawable();
            badgeBg.setColor(i == currentTabIndex ? 0xFFFF3B30 : 0xFF444444);
            badgeBg.setCornerRadius(99f);
            letterBadge.setBackground(badgeBg);
            LinearLayout.LayoutParams badgeParams = new LinearLayout.LayoutParams(64, 64);
            badgeParams.setMargins(0, 0, 16, 0);
            letterBadge.setLayoutParams(badgeParams);
            itemLayout.addView(letterBadge);
            
            LinearLayout textLayout = new LinearLayout(this);
            textLayout.setOrientation(LinearLayout.VERTICAL);
            LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.0f);
            textLayout.setLayoutParams(textParams);
            
            TextView txtTitle = new TextView(this);
            txtTitle.setText(tabTitleStr);
            txtTitle.setTextColor(0xFFFFFFFF);
            txtTitle.setTextSize(14);
            txtTitle.setSingleLine(true);
            txtTitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
            textLayout.addView(txtTitle);
            
            TextView txtUrl = new TextView(this);
            txtUrl.setText(tabUrlStr);
            txtUrl.setTextColor(0xFF888888);
            txtUrl.setTextSize(11);
            txtUrl.setSingleLine(true);
            txtUrl.setEllipsize(android.text.TextUtils.TruncateAt.END);
            textLayout.addView(txtUrl);
            
            itemLayout.addView(textLayout);
            
            ImageButton btnClose = new ImageButton(this);
            btnClose.setImageResource(android.R.drawable.ic_menu_close_clear_cancel);
            btnClose.setColorFilter(0xFF888888);
            btnClose.setBackground(null);
            btnClose.setOnClickListener(v -> {
                closeTab(index);
                dialog.dismiss();
                showTabSwitcherDialog();
            });
            itemLayout.addView(btnClose);
            
            itemLayout.setOnClickListener(v -> {
                switchTab(index);
                dialog.dismiss();
            });
            
            listContainer.addView(itemLayout);
        }
        
        scrollView.addView(listContainer);
        root.addView(scrollView);
        
        Button btnNewTab = new Button(this);
        btnNewTab.setText("＋ 新建空白标签页");
        btnNewTab.setTextColor(0xFFFFFFFF);
        btnNewTab.setTextSize(14);
        btnNewTab.setTypeface(null, android.graphics.Typeface.BOLD);
        android.graphics.drawable.GradientDrawable btnBg = new android.graphics.drawable.GradientDrawable();
        btnBg.setColor(0xFFFF3B30);
        btnBg.setCornerRadius(16f);
        btnNewTab.setBackground(btnBg);
        
        LinearLayout.LayoutParams btnParams = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 96);
        btnParams.setMargins(0, 24, 0, 0);
        btnNewTab.setLayoutParams(btnParams);
        btnNewTab.setOnClickListener(v -> {
            addNewTab("file:///android_asset/index.html");
            dialog.dismiss();
        });
        root.addView(btnNewTab);
        
        dialog.setContentView(root);
        dialog.show();
    }
}
