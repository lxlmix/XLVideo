FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    echo "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security/ bookworm-security main" >> /etc/apt/sources.list

RUN apt-get update && apt-get install -y \
    wget \
    curl \
    ffmpeg \
    libicu-dev \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 下载并安装 N_m3u8DL-RE（Linux 最新版本）
RUN wget --tries=3 --retry-connrefused --waitretry=10 \
    https://cors.isteed.cc/github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.5.1-beta/N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz \
    && tar -xzf N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz \
    && mv N_m3u8DL-RE /usr/local/bin/ \
    && chmod +x /usr/local/bin/N_m3u8DL-RE \
    && rm N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz

# 安装 Playwright 浏览器
RUN pip install --no-cache-dir playwright && \
    playwright install chromium

# 复制依赖文件
COPY requirements.txt .


RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p downloads logs

EXPOSE 5000

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=web_app.py

CMD ["python", "web_app.py"]
