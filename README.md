# XLVideo — 智能视频下载 & 批量文件管理

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.1.3-green.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.6.0-orange.svg)
![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

**视频下载 + 批量重命名，Web & 桌面双端一体化工具**

https://github.com/lxlmix/XLVideo

</div>

---

## 项目简介

XLVideo 是一款集**视频下载**和**批量文件管理**于一体的 Python 工具，提供 **Web 界面**和**桌面应用**两种使用方式。除了强大的多引擎视频下载能力外，还内置了功能完备的批量重命名模块，一站解决视频获取与文件整理需求。

---

## 功能特性

### 视频下载（主页）

| 功能 | 说明 |
|------|------|
| 双引擎 | yt-dlp + N_m3u8DL-RE，自动识别视频类型选择最优引擎 |
| 并发下载 | 可配置 1-10 个任务同时下载 |
| 自动转码 | 下载后自动通过 FFmpeg 转为 MP4 |
| 任务管理 | 实时进度、暂停、取消、删除、一键清空已完成 |
| 浏览器推送 | 内置 Webhook 服务器，支持猫抓等插件自动推送视频链接 |
| 请求头自定义 | 可选自定义 User-Agent 和 Referer，应对防盗链 |
| Cookies | 支持配置 cookies 文件 |

### 批量重命名（中间标签页）

支持 **7 种重命名模式**，带预览和即时执行：

| 模式 | 说明 | 示例 |
|------|------|------|
| 查找替换 | 替换文件名中指定文本 | `photo_copy` → `photo` |
| 添加前缀 | 文件名前添加固定文本 | `IMG_0001.jpg` → `旅行_IMG_0001.jpg` |
| 添加后缀 | 扩展名前添加文本 | `report` → `report_v2.pdf` |
| 序号重命名 | 格式 + 序号统一编号 | `文件_001.txt`, `文件_002.txt` |
| 删除字符 | 删除文件名中的指定字符 | `【广告】电影.mp4` → `电影.mp4` |
| 大小写转换 | 全小写 / 全大写 / 首字母大写 | `Hello World.txt` → `hello world.txt` |
| 正则替换 | 完整正则 + 捕获组引用 | `2024年01月15日` → `2024-01-15` |

额外特性：
- 面包屑导航，支持 Docker 映射目录多级浏览
- 复选框多选，批量操作灵活
- 单文件重命名弹窗，文件名与扩展名分离编辑
- 预览确认机制，执行前可看到所有变更

### 设置页

- 保存目录白名单选择（由 `XLVIDEO_ALLOWED_DIRS` 环境变量控制）
- 并发任务数、自动转码开关
- 自定义 User-Agent 和 Referer（可选）
- Cookies 文件路径配置

---

## 快速开始

### 前置要求

- Python 3.11+
- FFmpeg（用于视频转码）
- N_m3u8DL-RE（用于 m3u8 下载）

### 安装

```bash
git clone https://github.com/lxlmix/XLVideo.git
cd XLVideo
pip install -r requirements.txt
```

### 启动

**Web 版本：**

```bash
python web_app.py
```

访问 http://localhost:5000

**桌面版本：**

```bash
python desktop_app.py
```

---

## Docker 部署

```bash
# 1. 创建配置文件
cp config.ini.example config.ini

# 2. 编辑 config.ini 配置保存目录等
# 3. 启动服务
docker compose up -d
```

### docker-compose.yml 参考

```yaml
services:
  xlvideo:
    image: registry.cn-hangzhou.aliyuncs.com/xlvideo/xlvideo:latest
    container_name: xlvideo
    ports:
      - "5000:5000"
    volumes:
      - ./downloads:/app/downloads
      - ./logs:/app/logs
      - ./config.ini:/app/config.ini
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
      - XLVIDEO_ALLOWED_DIRS=/app/downloads,/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

> **批量重命名的保存目录**由环境变量 `XLVIDEO_ALLOWED_DIRS` 控制（逗号分隔），只有白名单内的目录才可在页面中选择和操作。

---

## 配置说明

### config.ini

配置文件包含本机路径，**不纳入版本控制**。首次使用请复制模板：

```bash
cp config.ini.example config.ini
```

### 配置项

| 配置项 | 段 | 说明 | 默认值 |
|--------|-----|------|--------|
| `save_directory` | `[download]` | 视频保存目录 | `./downloads` |
| `max_concurrent_tasks` | `[download]` | 最大并发任务数 | `3` |
| `convert_to_mp4` | `[download]` | 自动转码为 MP4 | `false` |
| `cookies_file` | `[download]` | Cookies 文件路径 | 空 |
| `ffmpeg_path` | `[tools]` | FFmpeg 可执行文件路径 | 空（使用系统 PATH） |
| `n_m3u8dl_re_path` | `[tools]` | N_m3u8DL-RE 路径 | 空（使用系统 PATH） |
| `webhook_port` | `[webhook]` | Webhook 服务器端口 | `5001` |
| `user_agent` | `[request]` | 自定义 User-Agent | 空（使用默认） |
| `referer` | `[request]` | 自定义 Referer | 空 |

### Web 安全说明

Web 版默认只监听 `127.0.0.1`。如需局域网/公网访问，设置环境变量 `XLVIDEO_HOST=0.0.0.0`，但**当前版本无鉴权**，请勿暴露到不受信任的网络。

批量重命名的可操作目录受 `XLVIDEO_ALLOWED_DIRS` 白名单限制，防止路径穿越风险。

---

## 使用方式

### 视频下载

1. 在「主页」输入视频链接（和可选的自定义名称）
2. 点击「添加任务」，实时查看下载进度
3. 在「设置」页面配置保存目录、并发数、请求头等

### 批量重命名

1. 切换到「批量重命名」标签页
2. 通过面包屑导航浏览目录
3. 勾选文件多选，或点击「重命名」编辑单个文件
4. 选择批量模式 → 填写参数 → 预览 → 执行

### 浏览器插件推送

配置猫抓等插件的推送地址为 `http://localhost:5001/webhook`，捕获的视频链接会自动推送到 XLVideo。

---

## 项目结构

```
XLVideo/
├── xlvideo/                # 核心模块
│   ├── config.py           # 配置管理（单例 + 文件锁）
│   ├── engine.py           # 下载引擎（yt-dlp / N_m3u8DL-RE）
│   ├── task_manager.py     # 任务管理器（并发调度 + 文件名净化）
│   ├── logger.py           # 日志管理（单例）
│   └── m3u8_tool.py        # m3u8 链接解析
├── templates/
│   └── index.html          # Web 前端（主页 + 批量重命名 + 设置）
├── web_app.py              # Flask Web 服务
├── desktop_app.py          # PyQt6 桌面应用
├── docker-compose.yml      # Docker 部署编排
├── Dockerfile              # Docker 镜像构建
├── config.ini.example      # 配置文件模板
├── requirements.txt        # Python 依赖
└── LICENSE                 # MIT 许可证
```

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — 强大的视频下载工具
- [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) — m3u8 下载器
- [Flask](https://flask.palletsprojects.com/) — 轻量级 Web 框架
- [PyQt6](https://www.riverbankcomputing.com/external-links/pyqt6) — Python Qt 绑定
- [FFmpeg](https://ffmpeg.org/) — 音视频处理工具

---

<div align="center">
**如果这个项目对你有帮助，请给个 ⭐ Star 支持一下！**
</div>
