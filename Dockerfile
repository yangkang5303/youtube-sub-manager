# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PORT=8765

WORKDIR /app

# 时区数据（日志时间戳正确）
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# 依赖单独一层：只改业务代码时无需重新安装
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 应用代码
COPY app.py ./
COPY templates ./templates
COPY static ./static
COPY scripts ./scripts

# 运行时目录（实际部署时会被 volume 覆盖）
RUN mkdir -p /app/config /app/data /app/output /app/cache/thumbs

EXPOSE 8765 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ.get('PORT','8765')+'/healthz', timeout=4)" || exit 1

# 单 worker + 多线程：
#   - 应用内有内存缓存（订阅快照）与头像下载锁，多 worker 会重复劳动
#   - 线程数给足，保证刷新（约 20s）期间页面仍可访问
#   - timeout 放宽，因为「刷新数据」要遍历几百个频道
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8765", \
     "--worker-class", "gthread", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
