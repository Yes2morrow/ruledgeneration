FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mplconfig \
    PORT=8080 \
    UVICORN_WORKERS=2 \
    MAX_INFLIGHT=1 \
    UVICORN_LIMIT_CONCURRENCY=32 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY configs ./configs
COPY 01_pre_selection ./01_pre_selection
COPY 02_placement_generation ./02_placement_generation
COPY 03_visualization ./03_visualization
COPY 05_config_and_tools ./05_config_and_tools
COPY cloudrun_app ./cloudrun_app

# 非 root 运行; MPLCONFIGDIR 与产物目录需要可写
RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/generated_runs /tmp/mplconfig \
    && chown -R appuser:appuser /app /tmp/mplconfig

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health',timeout=4).status==200 else 1)"

# 排布/渲染是 CPU 密集: 多 worker 进程才能真正绕开 GIL 吃满多核。
# MAX_INFLIGHT 在应用层再限一次, 防止单个 worker 内并发打爆内存。
CMD ["sh", "-c", "uvicorn cloudrun_app.main:app \
  --host 0.0.0.0 --port ${PORT:-8080} \
  --workers ${UVICORN_WORKERS:-2} \
  --limit-concurrency ${UVICORN_LIMIT_CONCURRENCY:-32} \
  --timeout-keep-alive 30"]
