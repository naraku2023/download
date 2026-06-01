// Override fetch to support absolute path under local file protocol (Android WebView assets)
if (window.location.protocol === 'file:') {
    const originalFetch = window.fetch;
    window.fetch = function(url, options) {
        if (typeof url === 'string' && url.startsWith('/')) {
            url = 'http://127.0.0.1:5000' + url;
        }
        return originalFetch(url, options);
    };
}

// State management
let currentMetadata = null;
let activeTasks = new Set();
let isPolling = false;
let pollingInterval = null;

// DOM Elements
const urlInput = document.getElementById('url-input');
const btnPaste = document.getElementById('btn-paste');
const btnAnalyze = document.getElementById('btn-analyze');
const analyzeSpinner = document.getElementById('analyze-spinner');
const videoInfoCard = document.getElementById('video-info-card');
const progressContainer = document.getElementById('progress-container');
const progressList = document.getElementById('progress-list');
const activeCount = document.getElementById('active-count');
const historyContainer = document.getElementById('history-container');
const historyGrid = document.getElementById('history-grid');
const historyEmpty = document.getElementById('history-empty');

// Settings Drawer Elements
const settingsDrawer = document.getElementById('settings-drawer');
const btnSettingsToggle = document.getElementById('btn-settings-toggle');
const btnSettingsClose = document.getElementById('btn-settings-close');
const btnSaveSettings = document.getElementById('btn-save-settings');
const downloadDirInput = document.getElementById('download-dir-input');
const concurrentInput = document.getElementById('concurrent-input');
const adBlockInput = document.getElementById('adblock-input');
const popupBlockInput = document.getElementById('popup-block-input');
const pickerBlockInput = document.getElementById('picker-block-input');
const btnOpenDir = document.getElementById('btn-open-dir');
const btnRevealDownloads = document.getElementById('btn-reveal-downloads');
const ffmpegBanner = document.getElementById('ffmpeg-banner');

// Toast notification helper
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let iconName = 'info';
    if (type === 'success') iconName = 'check-circle';
    if (type === 'error') iconName = 'alert-triangle';
    if (type === 'warning') iconName = 'alert-circle';
    
    toast.innerHTML = `
        <i data-lucide="${iconName}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    lucide.createIcons();
    
    // Animate in
    setTimeout(() => toast.classList.add('show'), 50);
    
    // Remove after 3.5s
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, 3500);
}

// Format duration
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return 'Unknown';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Resolve image URL (especially remote URLs that need proxying or relative local api paths under file:// protocol)
function getImageUrl(url, referer) {
    if (!url) return 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=400&auto=format&fit=crop&q=60';
    if (url.startsWith('/')) {
        return 'http://127.0.0.1:5000' + url;
    }
    if (url.startsWith('http://127.0.0.1') || url.startsWith('http://localhost')) {
        return url;
    }
    if (url.startsWith('http')) {
        // Proxy remote cover image through local python proxy to completely bypass all 403 hotlink blocks
        let proxyUrl = 'http://127.0.0.1:5000/api/proxy_image?url=' + encodeURIComponent(url);
        if (referer) {
            proxyUrl += '&referer=' + encodeURIComponent(referer);
        }
        return proxyUrl;
    }
    return url;
}

// Fetch settings and check environment
async function fetchSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        if (data.success) {
            downloadDirInput.value = data.settings.download_dir || '';
            concurrentInput.value = data.settings.max_concurrent || 3;
            if (adBlockInput) {
                adBlockInput.checked = data.settings.adblock_enabled !== false;
            }
            if (popupBlockInput) {
                popupBlockInput.checked = data.settings.popup_block_enabled !== false;
            }
            if (pickerBlockInput) {
                pickerBlockInput.checked = data.settings.picker_block_enabled !== false;
            }
            
            // Sync with Android native bridge if available on startup
            if (window.AndroidBridge) {
                if (window.AndroidBridge.setAdBlockEnabled && adBlockInput) {
                    window.AndroidBridge.setAdBlockEnabled(adBlockInput.checked);
                }
                if (window.AndroidBridge.setPopupBlockEnabled && popupBlockInput) {
                    window.AndroidBridge.setPopupBlockEnabled(popupBlockInput.checked);
                }
                if (window.AndroidBridge.setPickerBlockEnabled && pickerBlockInput) {
                    window.AndroidBridge.setPickerBlockEnabled(pickerBlockInput.checked);
                }
            }
            
            const btnInstallFfmpeg = document.getElementById('btn-install-ffmpeg');
            const installProgressBar = document.getElementById('ffmpeg-install-progress-bar');
            
            // Render FFmpeg Banner status
            if (data.settings.ffmpeg_installed) {
                ffmpegBanner.className = 'ffmpeg-status-card active';
                document.getElementById('ffmpeg-title').innerText = 'FFmpeg 已就绪';
                document.getElementById('ffmpeg-desc').innerText = '系统已检测到 FFmpeg 编码器，支持合并下载 1080P/4K 高清视频流。';
                document.getElementById('ffmpeg-icon').setAttribute('data-lucide', 'check-circle');
                
                if (btnInstallFfmpeg) btnInstallFfmpeg.classList.add('hidden');
                if (installProgressBar) installProgressBar.classList.add('hidden');
            } else {
                ffmpegBanner.className = 'ffmpeg-status-card missing';
                document.getElementById('ffmpeg-title').innerText = '未检测到 FFmpeg';
                document.getElementById('ffmpeg-desc').innerText = '未发现 FFmpeg。您仍能下载 720P 及以下整合视频；高清 1080P 下载可能会没有声音或失败。';
                document.getElementById('ffmpeg-icon').setAttribute('data-lucide', 'alert-circle');
                
                // Show installation actions only on Windows (Chaquopy on Android handles FFmpeg release natively)
                if (navigator.userAgent.indexOf('Windows') !== -1 || navigator.platform.indexOf('Win') !== -1 || window.AndroidBridge === undefined) {
                    if (btnInstallFfmpeg) btnInstallFfmpeg.classList.remove('hidden');
                } else {
                    if (btnInstallFfmpeg) btnInstallFfmpeg.classList.add('hidden');
                }
            }
            // Fetch and render physical diagnostics to settings description
            try {
                const diagResp = await fetch('/api/debug_ffmpeg');
                const diagData = await diagResp.json();
                if (diagData.success) {
                    const descEl = document.getElementById('ffmpeg-desc');
                    if (descEl) {
                        const cleanDesc = descEl.innerHTML.split('诊断信息:')[0].trim();
                        const diagText = `<br><span style="font-size:10px; color:rgba(255,255,255,0.45); font-family:monospace; display:block; margin-top:8px; line-height:1.3; word-break:break-all;">诊断信息: ${JSON.stringify(diagData.diagnostic)}</span>`;
                        descEl.innerHTML = cleanDesc + diagText;
                    }
                }
            } catch (diagErr) {
                console.error('Failed to fetch diagnostics:', diagErr);
            }
            lucide.createIcons();
        }
    } catch (err) {
        console.error('Error fetching settings:', err);
    }
}

// Load download history
async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();
        if (data.success && data.history.length > 0) {
            historyEmpty.classList.add('hidden');
            historyGrid.classList.remove('hidden');
            historyGrid.innerHTML = '';
            
            data.history.forEach(item => {
                const card = document.createElement('div');
                card.className = 'history-card';
                
                let durationBadge = '';
                if (item.duration && item.duration !== 'Unknown') {
                    durationBadge = `<span class="history-card-duration" style="position:absolute; bottom:0.5rem; right:0.5rem; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); font-size:0.65rem; font-weight:600; color:white; padding:0.15rem 0.4rem; border-radius:4px; letter-spacing:0.5px; z-index:2;">${item.duration}</span>`;
                }
                
                card.innerHTML = `
                    <div class="history-thumb-wrapper">
                        <img src="${getImageUrl(item.thumbnail, item.url)}" alt="${item.title}" onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=400&auto=format&fit=crop&q=60'">
                        <span class="history-card-size" style="position:absolute; bottom:0.5rem; left:0.5rem; right:auto; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); font-size:0.65rem; font-weight:600; color:white; padding:0.15rem 0.4rem; border-radius:4px; z-index:2;">${item.size || '未知'}</span>
                        ${durationBadge}
                    </div>
                    <div class="history-card-body">
                        <h4 title="${item.title}">${item.title}</h4>
                        <div class="history-card-actions">
                            <button class="card-action-btn play" onclick="playVideo('${item.filepath.replace(/\\/g, '\\\\')}')">
                                <i data-lucide="play" style="width:14px;height:14px;"></i> 播放
                            </button>
                            <button class="card-action-btn reveal" onclick="revealFile('${item.filepath.replace(/\\/g, '\\\\')}')">
                                <i data-lucide="folder" style="width:14px;height:14px;"></i> 定位
                            </button>
                            <button class="card-action-btn source" onclick="openSourceUrl('${item.url}')">
                                <i data-lucide="globe" style="width:14px;height:14px;"></i> 来源
                            </button>
                            <button class="card-action-btn delete" onclick="deleteHistory(this, '${item.id}', '${item.title.replace(/'/g, "\\'")}')">
                                <i data-lucide="trash-2" style="width:14px;height:14px;"></i> 删除
                            </button>
                        </div>
                    </div>
                `;
                historyGrid.appendChild(card);
            });
            lucide.createIcons();
        } else {
            historyEmpty.classList.remove('hidden');
            historyGrid.classList.add('hidden');
        }
    } catch (err) {
        console.error('Error loading history:', err);
    }
}

// Play Video via API / Android Bridge
async function playVideo(filepath) {
    if (!filepath) return;
    if (window.AndroidBridge && window.AndroidBridge.playVideo) {
        window.AndroidBridge.playVideo(filepath);
        return;
    }
    try {
        const response = await fetch('/api/play_video', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath })
        });
        const data = await response.json();
        if (!data.success) {
            showToast(`播放失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('播放请求异常', 'error');
    }
}

// Reveal File in Explorer / Android Bridge
async function revealFile(filepath) {
    if (!filepath) return;
    if (window.AndroidBridge && window.AndroidBridge.openFolder) {
        window.AndroidBridge.openFolder();
        return;
    }
    try {
        const dirPath = filepath.substring(0, filepath.lastIndexOf('\\')) || filepath.substring(0, filepath.lastIndexOf('/'));
        const response = await fetch('/api/open_folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: dirPath })
        });
        const data = await response.json();
        if (data.success) {
            showToast('已打开所在文件夹', 'success');
        } else {
            showToast(`打开失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('打开文件夹异常', 'error');
    }
}

// Open source webpage URL
function openSourceUrl(url) {
    if (!url) return;
    if (window.AndroidBridge && window.AndroidBridge.openBrowserUrl) {
        window.AndroidBridge.openBrowserUrl(url);
    } else {
        window.open(url, '_blank');
    }
}

// Track timers for delete button reverts
const deleteTimers = new Map();

// Delete History Record and Physical File (Custom Double-Click confirmation to bypass native WebView alert limitations)
async function deleteHistory(btn, id, title) {
    if (!btn.classList.contains('confirm-active')) {
        btn.classList.add('confirm-active');
        btn.innerHTML = `<i data-lucide="alert-triangle" style="width:14px;height:14px;"></i> 确认？`;
        lucide.createIcons();
        btn.style.background = '#ef4444';
        btn.style.color = 'white';
        btn.style.borderColor = 'transparent';
        
        const timer = setTimeout(() => {
            btn.classList.remove('confirm-active');
            btn.innerHTML = `<i data-lucide="trash-2" style="width:14px;height:14px;"></i> 删除`;
            lucide.createIcons();
            btn.style.background = '';
            btn.style.color = '';
            btn.style.borderColor = '';
            deleteTimers.delete(id);
        }, 3000);
        
        deleteTimers.set(id, timer);
        return;
    }
    
    const timer = deleteTimers.get(id);
    if (timer) {
        clearTimeout(timer);
        deleteTimers.delete(id);
    }
    
    try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="width:12px;height:12px;display:inline-block;border:2px solid rgba(255,255,255,0.3);border-top-color:white;border-radius:50%;animation:spin 0.8s linear infinite;"></span>`;
        
        const response = await fetch('/api/delete_history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, delete_file: true })
        });
        const data = await response.json();
        if (data.success) {
            showToast('已成功物理删除视频及本地记录', 'success');
            loadHistory();
        } else {
            showToast(`删除失败: ${data.error}`, 'error');
            btn.disabled = false;
            btn.classList.remove('confirm-active');
            btn.innerHTML = `<i data-lucide="trash-2" style="width:14px;height:14px;"></i> 删除`;
            lucide.createIcons();
            btn.style.background = '';
            btn.style.color = '';
            btn.style.borderColor = '';
        }
    } catch (err) {
        showToast('删除连接请求异常', 'error');
        btn.disabled = false;
        btn.classList.remove('confirm-active');
        btn.innerHTML = `<i data-lucide="trash-2" style="width:14px;height:14px;"></i> 删除`;
        lucide.createIcons();
        btn.style.background = '';
        btn.style.color = '';
        btn.style.borderColor = '';
    }
}

// Analyze link
async function analyzeLink() {
    const url = urlInput.value.trim();
    if (!url) {
        showToast('请先输入有效的视频网址', 'warning');
        return;
    }
    
    // UI state loading
    btnAnalyze.disabled = true;
    urlInput.disabled = true;
    analyzeSpinner.classList.remove('hidden');
    
    const arrowIcon = btnAnalyze.querySelector('.arrow-icon') || btnAnalyze.querySelector('svg');
    if (arrowIcon) arrowIcon.classList.add('hidden');
    
    videoInfoCard.classList.add('hidden');
    
    showToast('正在解析视频流，这可能需要数秒...', 'info');
    
    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await response.json();
        
        if (data.success) {
            currentMetadata = data.metadata;
            renderVideoDetails(data.metadata);
            showToast('解析成功！', 'success');
        } else {
            showToast(`解析失败: ${data.error || '未知网络错误'}`, 'error');
        }
    } catch (err) {
        showToast('解析请求失败，请检查网络连接及后台状态', 'error');
        console.error(err);
    } finally {
        btnAnalyze.disabled = false;
        urlInput.disabled = false;
        analyzeSpinner.classList.add('hidden');
        if (arrowIcon) arrowIcon.classList.remove('hidden');
    }
}

// Render analyzed video info
function renderVideoDetails(meta) {
    document.getElementById('video-thumbnail').src = getImageUrl(meta.thumbnail, meta.url);
    document.getElementById('video-duration').innerText = meta.duration || '00:00';
    document.getElementById('video-platform').innerText = meta.platform || 'Generic';
    document.getElementById('video-title').innerText = meta.title || 'Unknown Title';
    document.getElementById('video-author').innerText = meta.author || '未知作者';
    
    const tbody = document.getElementById('formats-tbody');
    tbody.innerHTML = '';
    
    if (meta.formats && meta.formats.length > 0) {
        meta.formats.forEach(f => {
            // Determine type badge
            let typeBadge = '';
            if (f.has_video && f.has_audio) {
                typeBadge = '<span class="type-badge combined"><i data-lucide="video" style="width:12px;height:12px"></i> 整合流</span>';
            } else if (f.has_video) {
                typeBadge = '<span class="type-badge video"><i data-lucide="eye" style="width:12px;height:12px"></i> 仅视频</span>';
            } else if (f.has_audio) {
                typeBadge = '<span class="type-badge audio"><i data-lucide="music" style="width:12px;height:12px"></i> 仅音频</span>';
            }
            
            const tr = document.createElement('tr');
            // Store direct_url as escaped data-attribute on the button
            const directUrlAttr = f.direct_url ? ` data-direct-url="${encodeURIComponent(f.direct_url)}"` : '';
            tr.innerHTML = `
                <td style="font-weight:600;color:var(--text-primary);">${f.label || f.resolution}</td>
                <td><span style="font-family:monospace;background:rgba(255,255,255,0.04);padding:2px 6px;border-radius:4px;">${f.ext}</span></td>
                <td>${f.size || '未知'}</td>
                <td>${typeBadge}</td>
                <td>
                    <button class="dl-btn" onclick="startDownload('${f.format_id}', '${f.size}', this)"${directUrlAttr}>
                        <i data-lucide="download" style="width:12px;height:12px;"></i> 下载
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        lucide.createIcons();
    } else {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">未发现可用清晰度选项，您可以尝试默认下载。</td></tr>';
    }
    
    videoInfoCard.classList.remove('hidden');
    // Scroll smoothly to video info card
    videoInfoCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Start download stream
// btn element is passed so we can read data-direct-url attribute if present
async function startDownload(formatId, sizeStr, btn) {
    if (!currentMetadata) return;
    
    // Extract the direct_url from the button's data attribute (used for sites like rou.video)
    let directUrl = null;
    if (btn && btn.dataset && btn.dataset.directUrl) {
        directUrl = decodeURIComponent(btn.dataset.directUrl);
    }
    
    showToast(`正在创建下载任务: ${currentMetadata.title}`, 'info');
    
    try {
        const payload = {
            url: currentMetadata.url,
            format_id: formatId,
            title: currentMetadata.title,
            thumbnail: currentMetadata.thumbnail,
            platform: currentMetadata.platform,
            size: sizeStr,
            duration: currentMetadata.duration || 'Unknown'
        };
        
        // Pass the real stream URL if we scraped it ourselves
        if (directUrl) {
            payload.direct_url = directUrl;
        }
        
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('任务已成功提交至后台下载队列！', 'success');
            activeTasks.add(data.task_id);
            progressContainer.classList.remove('hidden');
            
            // Trigger rapid polling
            if (!isPolling) {
                startProgressPolling();
            }
        } else {
            showToast(`下载失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('提交下载请求异常', 'error');
        console.error(err);
    }
}

// Track tasks that just finished — show 100% briefly before removing
const finishedTaskTimers = new Map();

// Cancel downloading task
async function cancelTask(taskId, title) {
    try {
        const response = await fetch('/api/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId })
        });
        const data = await response.json();
        if (data.success) {
            showToast(`已取消下载: ${title}`, 'warning');
            
            // Remove DOM instantly with animation
            const el = document.getElementById(`task-card-${taskId}`);
            if (el) {
                el.style.opacity = '0';
                el.style.transform = 'translateY(10px)';
                setTimeout(() => el.remove(), 300);
            }
            activeTasks.delete(taskId);
        } else {
            showToast(`取消失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('取消下载连接异常', 'error');
    }
}

// Pause download task
async function pauseTask(taskId) {
    try {
        const response = await fetch('/api/pause', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId })
        });
        const data = await response.json();
        if (data.success) {
            showToast('任务已暂停', 'warning');
            pollProgress(); // Update UI instantly
        } else {
            showToast(`暂停失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('请求暂停异常', 'error');
    }
}

// Resume download task
async function resumeTask(taskId) {
    try {
        const response = await fetch('/api/resume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId })
        });
        const data = await response.json();
        if (data.success) {
            showToast('正在恢复下载...', 'success');
            pollProgress(); // Update UI instantly
        } else {
            showToast(`恢复失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('请求恢复异常', 'error');
    }
}

// Poll Active Download progress with smooth diffing
function startProgressPolling() {
    isPolling = true;
    pollProgress();
    pollingInterval = setInterval(pollProgress, 900);
}

function stopProgressPolling() {
    isPolling = false;
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function pollProgress() {
    try {
        const response = await fetch('/api/progress');
        const data = await response.json();
        
        if (data.success) {
            const tasks = data.tasks;
            
            // Separate active (downloading/paused) and just-finished tasks
            const downloadingList = tasks.filter(t => t.status === 'downloading' || t.status === 'paused');
            const finishedList = tasks.filter(t => t.status === 'finished' || t.status === 'error');

            // Handle newly finished tasks: show 100% for 2s then remove
            finishedList.forEach(task => {
                if (!finishedTaskTimers.has(task.id)) {
                    // Mark as "finishing" and schedule removal
                    finishedTaskTimers.set(task.id, true);

                    // Update/create card showing 100%
                    let card = document.getElementById(`task-card-${task.id}`);
                    if (card) {
                        const isError = task.status === 'error';
                        const statusLabel = isError ? '❌ 下载失败' : '✅ 下载完成';
                        const pct = isError ? task.percent : 100;
                        card.innerHTML = `
                            <div class="item-thumb">
                                <img src="${getImageUrl(task.thumbnail, task.url)}" alt="Thumb" onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=400&auto=format&fit=crop&q=60'">
                            </div>
                            <div class="item-details">
                                <div class="item-title-row">
                                    <h4 title="${task.title}">${task.title}</h4>
                                    <span class="item-pct" style="color:${isError ? '#ff6b6b' : '#4ade80'}">${statusLabel}</span>
                                </div>
                                <div class="progress-bar-bg">
                                    <div class="progress-bar-fill" style="width: ${pct}%; background: ${isError ? 'var(--error, #ff6b6b)' : 'var(--success, #4ade80)'};"></div>
                                </div>
                                <div class="item-meta-row">
                                    <span>${isError ? (task.error_msg || '下载出错') : '文件已保存至下载目录'}</span>
                                </div>
                            </div>
                            <div></div>
                        `;
                        lucide.createIcons();
                    }

                    // Remove after 2 seconds
                    setTimeout(() => {
                        const el = document.getElementById(`task-card-${task.id}`);
                        if (el) {
                            el.style.opacity = '0';
                            el.style.transform = 'translateY(-10px)';
                            setTimeout(() => el.remove(), 300);
                        }
                        finishedTaskTimers.delete(task.id);
                        // If no more cards, hide container and reload history
                        if (progressList.children.length === 0) {
                            progressContainer.classList.add('hidden');
                            stopProgressPolling();
                            loadHistory();
                        }
                    }, 2000);
                }
            });

            // Update active count (only downloading tasks count as "active")
            activeCount.innerText = downloadingList.length;
            
            // Show/hide progress container
            const hasAnyCard = downloadingList.length > 0 || finishedTaskTimers.size > 0;
            if (!hasAnyCard) {
                progressContainer.classList.add('hidden');
                stopProgressPolling();
                loadHistory();
                return;
            }
            
            progressContainer.classList.remove('hidden');
            
            // Intelligent DOM Diffing for downloading tasks
            downloadingList.forEach(task => {
                // Skip if this task is in finishing state (already showing 100%)
                if (finishedTaskTimers.has(task.id)) return;

                let card = document.getElementById(`task-card-${task.id}`);
                
                if (!card) {
                    card = document.createElement('div');
                    card.id = `task-card-${task.id}`;
                    card.className = 'progress-item-card';
                    progressList.appendChild(card);
                }
                
                let controlBtn = '';
                if (task.status === 'paused') {
                    controlBtn = `
                        <button class="icon-btn btn-resume-task" onclick="resumeTask('${task.id}')" title="恢复下载" style="margin-right: 8px; color: #4ade80;">
                            <i data-lucide="play-circle"></i>
                        </button>
                    `;
                } else {
                    controlBtn = `
                        <button class="icon-btn btn-pause-task" onclick="pauseTask('${task.id}')" title="暂停下载" style="margin-right: 8px; color: #f59e0b;">
                            <i data-lucide="pause-circle"></i>
                        </button>
                    `;
                }

                card.innerHTML = `
                    <div class="item-thumb">
                        <img src="${getImageUrl(task.thumbnail, task.url)}" alt="Thumb" onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=400&auto=format&fit=crop&q=60'">
                    </div>
                    <div class="item-details">
                        <div class="item-title-row">
                            <h4 title="${task.title}">${task.title}</h4>
                            <span class="item-pct">${task.percent}%</span>
                        </div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" style="width: ${task.percent}%;"></div>
                        </div>
                        <div class="item-meta-row">
                            <span><i data-lucide="download-cloud"></i> ${task.speed || '0 KB/s'}</span>
                            <span><i data-lucide="clock"></i> 剩余：${task.eta || '未知'}</span>
                            <span><i data-lucide="database"></i> 大小：${task.size || '未知'}</span>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center;">
                        ${controlBtn}
                        <button class="icon-btn btn-cancel-task" onclick="cancelTask('${task.id}', '${task.title.replace(/'/g, "\\'")}')" title="取消下载">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                `;
            });
            
            // Remove cards for tasks no longer in either list
            const allKnownIds = [...downloadingList.map(t => t.id), ...finishedList.map(t => t.id)];
            const currentDomIds = Array.from(progressList.children).map(c => c.id.replace('task-card-', ''));
            
            currentDomIds.forEach(domId => {
                if (!allKnownIds.includes(domId) && !finishedTaskTimers.has(domId)) {
                    const el = document.getElementById(`task-card-${domId}`);
                    if (el) {
                        el.style.opacity = '0';
                        el.style.transform = 'translateY(-10px)';
                        setTimeout(() => el.remove(), 300);
                    }
                }
            });
            
            lucide.createIcons();
        }
    } catch (err) {
        console.error('Error polling progress:', err);
    }
}

// Settings toggle events
btnSettingsToggle.addEventListener('click', () => {
    settingsDrawer.classList.toggle('hidden');
    if (!settingsDrawer.classList.contains('hidden')) {
        fetchSettings();
    }
});

btnSettingsClose.addEventListener('click', () => {
    settingsDrawer.classList.add('hidden');
});

// Save settings configuration
btnSaveSettings.addEventListener('click', async () => {
    const downloadDir = downloadDirInput.value.trim();
    const maxConcurrent = parseInt(concurrentInput.value) || 3;
    const adblockEnabled = adBlockInput ? adBlockInput.checked : true;
    const popupBlockEnabled = popupBlockInput ? popupBlockInput.checked : true;
    const pickerBlockEnabled = pickerBlockInput ? pickerBlockInput.checked : true;
    
    if (!downloadDir) {
        showToast('下载文件夹路径不能为空', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                download_dir: downloadDir,
                max_concurrent: maxConcurrent,
                adblock_enabled: adblockEnabled,
                popup_block_enabled: popupBlockEnabled,
                picker_block_enabled: pickerBlockEnabled
            })
        });
        const data = await response.json();
        
        if (data.success) {
            showToast('系统配置保存成功！', 'success');
            if (window.AndroidBridge) {
                if (window.AndroidBridge.setAdBlockEnabled) {
                    window.AndroidBridge.setAdBlockEnabled(adblockEnabled);
                }
                if (window.AndroidBridge.setPopupBlockEnabled) {
                    window.AndroidBridge.setPopupBlockEnabled(popupBlockEnabled);
                }
                if (window.AndroidBridge.setPickerBlockEnabled) {
                    window.AndroidBridge.setPickerBlockEnabled(pickerBlockEnabled);
                }
            }
            settingsDrawer.classList.add('hidden');
        } else {
            showToast(`保存失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('保存设置连接异常', 'error');
    }
});

// Open downloads directory
btnOpenDir.addEventListener('click', async () => {
    if (window.AndroidBridge && window.AndroidBridge.openFolder) {
        window.AndroidBridge.openFolder();
        return;
    }
    try {
        const response = await fetch('/api/open_folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: downloadDirInput.value.trim() })
        });
        const data = await response.json();
        if (data.success) {
            showToast('已成功开启系统下载目录', 'success');
        } else {
            showToast(`无法打开文件夹: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('触发本地目录文件夹异常', 'error');
    }
});

// Link reveal dir
btnRevealDownloads.addEventListener('click', async () => {
    if (window.AndroidBridge && window.AndroidBridge.openFolder) {
        window.AndroidBridge.openFolder();
        return;
    }
    try {
        const response = await fetch('/api/open_folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        const data = await response.json();
        if (data.success) {
            showToast('已在文件管理器中打开目录', 'success');
        } else {
            showToast(`打开目录失败: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('启动本地资源管理器异常', 'error');
    }
});

// Paste shortcut helper
btnPaste.addEventListener('click', async () => {
    try {
        // Read text from clipboard
        const text = await navigator.clipboard.readText();
        if (text) {
            urlInput.value = text.trim();
            showToast('已粘贴剪贴板内容', 'success');
            // Proactively auto-trigger analyze
            analyzeLink();
        } else {
            showToast('剪贴板为空！', 'warning');
        }
    } catch (err) {
        // Security block fallback
        showToast('浏览器权限限制，请使用 Ctrl+V 快捷键粘贴链接。', 'info');
    }
});

// Enter key press triggers analyze
urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        analyzeLink();
    }
});

// Analyze click binding
btnAnalyze.addEventListener('click', analyzeLink);

// Install FFmpeg Handler with Polling
let ffmpegInstallInterval = null;

async function startFFmpegInstallation() {
    const btnInstallFfmpeg = document.getElementById('btn-install-ffmpeg');
    const installProgressBar = document.getElementById('ffmpeg-install-progress-bar');
    const installFill = document.getElementById('ffmpeg-install-fill');
    const installText = document.getElementById('ffmpeg-install-text');
    
    if (btnInstallFfmpeg) btnInstallFfmpeg.classList.add('hidden');
    if (installProgressBar) installProgressBar.classList.remove('hidden');
    if (installFill) installFill.style.width = '0%';
    if (installText) installText.innerText = '正在启动下载任务...';
    
    try {
        const response = await fetch('/api/install_ffmpeg', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast('已启动 FFmpeg 自动部署，请勿关闭应用或断开网络', 'info');
            
            // Start polling progress
            if (ffmpegInstallInterval) clearInterval(ffmpegInstallInterval);
            ffmpegInstallInterval = setInterval(pollFFmpegInstallStatus, 800);
        } else {
            showToast(`启动自动部署失败: ${data.error}`, 'error');
            if (btnInstallFfmpeg) btnInstallFfmpeg.classList.remove('hidden');
            if (installProgressBar) installProgressBar.classList.add('hidden');
        }
    } catch (err) {
        showToast('发起自动部署发生异常', 'error');
        if (btnInstallFfmpeg) btnInstallFfmpeg.classList.remove('hidden');
        if (installProgressBar) installProgressBar.classList.add('hidden');
    }
}

async function pollFFmpegInstallStatus() {
    const btnInstallFfmpeg = document.getElementById('btn-install-ffmpeg');
    const installProgressBar = document.getElementById('ffmpeg-install-progress-bar');
    const installFill = document.getElementById('ffmpeg-install-fill');
    const installText = document.getElementById('ffmpeg-install-text');
    
    try {
        const response = await fetch('/api/install_status');
        const data = await response.json();
        
        if (data.success && data.state) {
            const state = data.state;
            
            if (installFill) installFill.style.width = `${state.progress}%`;
            if (installText) installText.innerText = state.message || '正在部署...';
            
            if (state.status === 'success') {
                clearInterval(ffmpegInstallInterval);
                ffmpegInstallInterval = null;
                showToast('FFmpeg 便携包部署成功！已开启超高清合并与 HLS 切片转换支持。', 'success');
                fetchSettings(); // Refresh settings UI to show "ready"
            } else if (state.status === 'error') {
                clearInterval(ffmpegInstallInterval);
                ffmpegInstallInterval = null;
                showToast(`部署出错: ${state.message}`, 'error');
                if (btnInstallFfmpeg) btnInstallFfmpeg.classList.remove('hidden');
                if (installProgressBar) installProgressBar.classList.add('hidden');
            }
        }
    } catch (err) {
        console.error('Error polling FFmpeg status:', err);
    }
}

// Initialization on DOM content load
document.addEventListener('DOMContentLoaded', () => {
    // Parse URL query parameters to split browser views dynamically
    const urlParams = new URLSearchParams(window.location.search);
    const view = urlParams.get('view');
    if (view === 'downloads') {
        document.body.classList.add('view-downloads');
    } else if (view === 'settings') {
        document.body.classList.add('view-settings');
        if (settingsDrawer) {
            settingsDrawer.classList.remove('hidden');
            if (btnSettingsClose) btnSettingsClose.style.display = 'none';
        }
    } else {
        document.body.classList.add('view-home');
    }

    // Bind FFmpeg install trigger
    const btnInstallFfmpeg = document.getElementById('btn-install-ffmpeg');
    if (btnInstallFfmpeg) {
        btnInstallFfmpeg.addEventListener('click', startFFmpegInstallation);
    }

    lucide.createIcons();
    fetchSettings();
    loadHistory();
    
    // Check if there are any active downloads running in the background upon startup
    startProgressPolling();
});
