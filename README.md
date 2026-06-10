# 🎬 XLVideo - 智能视频下载器

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.1.3-green.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.6.0-orange.svg)
![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

**一个功能强大的视频下载工具，支持 Web 和桌面双端部署**
</div>
---

## 📖 项目简介

XLVideo 是一款现代化的视频下载工具，支持从多个平台下载视频内容。项目采用 Python 开发，提供 **Web 界面**和**桌面应用**两种使用方式，满足不同场景需求。

### ✨ 核心亮点

- 🚀 **双端部署**：Web 版本 + 桌面版本，灵活选择
- 🎯 **智能下载**：智能抓取网页视频链接，自动识别视频类型，选择最优下载引擎
- 🔄 **自动转码**：支持下载后自动转换为 MP4 格式
- 📡 **推送接收**：内置 Webhook 服务器，支持浏览器插件自动推送
- 🎨 **现代 UI**：Mac 风格界面，美观易用
- 🐳 **容器化**：完整的 Docker 支持，一键部署

---

## 🌟 功能特性

### 下载功能
- ✅ 支持 yt-dlp 和 N_m3u8DL-RE 双引擎
- ✅ 自动检测视频类型（普通视频 / m3u8 流）
- ✅ 多任务并发下载（可配置 1-10 个并发）
- ✅ 实时进度显示和状态跟踪
- ✅ 任务暂停、取消、删除管理
- ✅ 自定义视频名称

### 格式转换
- 🎬 自动检测非 MP4 格式
- 🔧 使用 FFmpeg 进行高质量转码
- ⚙️ 可配置的转码开关
- 🗑️ 转码后自动清理原文件

### 推送接收
- 🌐 内置 Webhook 服务器（web默认端口：5000，桌面默认端口：5001）
- 🔌 支持浏览器猫抓插件自动推送
- 💾 推送数据持久化保存

### 用户界面
- 🖥️ Web 界面：响应式设计，支持移动端
- 💻 桌面应用：PyQt6 打造，原生体验
- 🎨 简洁风格：现代化渐变设计
- ⚡ 实时刷新：任务列表自动更新

## 🚀 快速开始

### 前置要求

- Python 3.11+
- FFmpeg（用于视频转码）
- N_m3u8DL-RE（用于 m3u8 下载）

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://github.com/lxlmix/XLVideo.git cd XLVideo
```


#### 2. 安装依赖
```python
pip install -r requirements.txt
```


#### 3. 启动应用

**Web 版本：**

```python
python web_app.py
```

访问：http://localhost:5000

**桌面版本：**

```python
python desktop_app.py
```

## 🐳 Docker 部署

    docker compose build

Docker Compose：

    services:
      xlvideo:
        image: registry.cn-hangzhou.aliyuncs.com/xlvideo/xlvideo:latest
        container_name: xlvideo
        ports:
          - "5000:5000"
        volumes:
          # 挂载下载目录到宿主机
          - ./downloads:/app/downloads
          # 挂载日志目录到宿主机
          - ./logs:/app/logs
          # 挂载配置文件到宿主机（方便修改）
          - ./config.ini:/app/config.ini
        restart: unless-stopped
        environment:
          - TZ=Asia/Shanghai
        healthcheck:
          test: ["CMD", "curl", "-f", "http://localhost:5000/"]
          interval: 30s
          timeout: 10s
          retries: 3
          start_period: 40s
---

## 📱 使用方式

### 界面使用

1. **添加下载任务**
   - 在"视频链接"输入框粘贴视频 URL
   - （可选）填写自定义视频名称
   - 点击"添加任务"按钮

2. **管理任务**
   - 查看实时下载进度
   - 暂停/取消正在下载的任务
   - 删除已完成的任务记录
   - 一键清空所有已完成任务

3. **配置设置**
   - 设置保存目录
   - 调整并发任务数
   - 开启/关闭自动转码
   - 配置 Cookies 文件

### 浏览器插件推送

如果你使用了浏览器抓包插件，可以配置自动推送：

1. **配置推送地址**
   http://localhost:5001/webhook
2. **插件捕获视频后会自动推送到 XLVideo**

3. **查看推送记录**
   - 文件位置：`downloads/received_data.txt`


## 🛠️ 配置说明

### 配置文件 (config.ini)
### 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `save_directory` | 视频保存目录 | `./downloads` |
| `max_concurrent_tasks` | 最大并发任务数 | `3` |
| `convert_to_mp4` | 自动转码为 MP4 | `false` |
| `cookies_file` | Cookies 文件路径 | 空 |
| `ffmpeg_path` | FFmpeg 可执行文件路径 | 空（使用系统 PATH） |
| `n_m3u8dl_re_path` | N_m3u8DL-RE 路径 | 空（使用系统 PATH） |
| `webhook.port` | Webhook 服务器端口 | `5001` |


---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件


## 🙏 致谢

感谢以下开源项目：

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载工具
- [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) - m3u8 下载器
- [Flask](https://flask.palletsprojects.com/) - 轻量级 Web 框架
- [PyQt6](https://www.riverbankcomputing.com/external-links/pyqt6) - Python Qt 绑定
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具



---

<div align="center">
**如果这个项目对你有帮助，请给个 ⭐ Star 支持一下！**







