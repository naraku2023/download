# 🚀 Veloce Video Downloader & Companion Android App

[![Language](https://img.shields.io/badge/Language-Python%20%7C%20HTML%20%7C%20JS%20%7C%20Java-blue.svg)](#)
[![Framework](https://img.shields.io/badge/Framework-Flask%20%7C%20Android%20SDK-orange.svg)](#)
[![Engine](https://img.shields.io/badge/Engine-yt--dlp-red.svg)](#)

**Veloce Video Downloader** 是一款全栈式网页及安卓伴侣视频下载工具。它集成了功能强大的 `yt-dlp` 引擎，提供了高颜值的 Web 控制台，以及针对特定流媒体平台的独家解析和解密引擎，并配备了完整的 Android WebView 封装项目。

---

## 🌟 核心功能特性

### 1. 🎛️ 高颜值 Web 控制面板
- **现代极简设计**：精心打磨的响应式卡片流布局，暗黑高雅配色。
- **实时进度反馈**：实时的下载进度百分比、下载速度、剩余时间 (ETA) 及已下载字节数展示。
- **任务管理系统**：支持一键**暂停 (Pause)**、**恢复 (Resume)** 及**取消 (Cancel)** 正在进行的下载。
- **本地便捷交互**：支持在网页端一键**打开下载文件夹**或**直接播放下载完成的视频**（自动调用系统默认播放器）。

### 2. ⚡ 强悍的解析与下载引擎
- **万能解析**：底层基于成熟的 `yt-dlp` 开源引擎，支持数千个主流视频网站的嗅探与分流解析。
- **流媒体解密器**：内置针对特定流媒体（如 `rou.video`）的**位移解密（Shift-Minus Decryptor）算法**，能自动解析并重新获取防盗链加密 HLS 视频切片地址。
- **双重保底机制**：若 `yt-dlp` 下载 HLS 分片超时，系统将自动激活 **FFmpeg 后备下载管道**，实现断点续传级的高效下载。
- **图片代理模块**：内置防盗链图片代理服务，确保网页端能够跨域完美展示各大视频平台的视频封面图。

### 3. 📱 伴侣式 Android 原生应用
- **原生封装**：位于 `android_project/` 下的 Android Studio 项目，采用高性能 WebView 完美融合 Web 前端与本地应用交互。
- **内置资源离线化**：原生打包前端静态资源，提供极佳的载入速度与流畅的操作体验。

---

## 📂 项目结构说明

```text
.
├── android_project/         # Android Companion App 项目目录 (Android Studio)
│   ├── app/                 # 应用程序模块
│   │   ├── src/main/assets/ # 原生打包的前端静态网页资源
│   │   └── src/main/python/ # 内部 Chaquopy Python 环境/核心代码
│   └── build.gradle         # Gradle 构建文件
├── downloads/               # 默认视频下载保存目录（自动生成）
├── static/                  # 网页控制台前端资源
│   ├── app.js               # 核心交互逻辑与 WebSocket/轮询接口调用
│   ├── index.html           # 现代 UI 控制台骨架
│   └── style.css            # 动态光影、卡片渐变等现代视觉样式表
├── app.py                   # Flask 后端服务、多线程下载管理器与平台解密核心
├── run.bat                  # Windows 一键环境检测、安装依赖与启动脚本
└── .gitignore               # 智能 Git 忽略规则（过滤大体积视频、本地运行日志等）
```

---

## 🛠️ 快速开始

### 方式一：Windows 一键运行（推荐）
双击运行根目录下的 **`run.bat`**。该脚本将自动帮您完成：
1. 检测本地 Python 环境。
2. 检查并自动安装/更新依赖项：`pip install flask yt-dlp`。
3. 检查并自动创建本地 `downloads/` 文件夹。
4. 自动在您的默认浏览器中打开 `http://127.0.0.1:5000`。
5. 开启 Flask 服务端守护进程。

### 方式二：手动命令行启动
1. **安装依赖**：
   ```bash
   pip install flask yt-dlp
   ```
   > 💡 *提示：为了更好地进行多格式合并或 HLS 解密下载，强烈建议将 `ffmpeg` 添加到您的系统环境变量 (PATH) 中。*

2. **启动 Flask 服务**：
   ```bash
   python app.py
   ```

3. **访问应用**：
   打开浏览器，访问 [http://127.0.0.1:5000](http://127.0.0.1:5000)。

---

## 🛠️ 技术选型与依赖

- **后端**：Python 3.x + Flask + `yt-dlp` (+ 可选 FFmpeg 辅助)
- **前端**：Vanilla HTML5 + Modern CSS3 (包含渐变、玻璃拟态、卡片动画) + Vanilla ES6 JS
- **存储**：基于 `tasks.json`, `settings.json` 和 `history.json` 的轻量级本地 JSON 持久化方案
- **安卓端**：Android SDK (API 21+) + Gradle 构建系统

---

## ⚠️ 免责声明与注意事项

1. **合法用途**：本工具仅限个人学习研究及备份自己拥有版权的视频。请勿使用本工具下载任何受版权保护、违法的视频或用于商业用途。
2. **遵守服务条款**：使用本工具可能违反部分视频网站的用户服务协议，请使用者自行承担全部责任。