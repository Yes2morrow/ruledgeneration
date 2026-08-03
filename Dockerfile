FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY 01_pre_selection ./01_pre_selection
COPY 02_placement_generation ./02_placement_generation
COPY 03_visualization ./03_visualization
COPY 05_config_and_tools ./05_config_and_tools
COPY cloudrun_app ./cloudrun_app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn cloudrun_app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
