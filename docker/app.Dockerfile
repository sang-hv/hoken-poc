# Image cho API và worker. Dùng chung cho một VM (compose), Azure Container Apps (+ Jobs) và AWS ECS.
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[azure,aws]"
RUN useradd -r -u 10001 app && mkdir -p /data/blob && chown -R app /data
USER app
EXPOSE 8000
CMD ["python", "-m", "app.main", "serve", "--port", "8000"]

# Worker parser (標準解析) — chọn target theo PARSER_TYPE: docling | paddleocr.
# Model tải sẵn lúc build để lúc chạy không cần mạng.

# Docling (torch CPU)
FROM base AS docling
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
 && pip install --extra-index-url https://download.pytorch.org/whl/cpu ".[docling]" \
 && docling-tools models download -o /models/docling \
 && chown -R app /models
ENV DOCLING_ARTIFACTS_PATH=/models/docling HF_HUB_OFFLINE=1
USER app
CMD ["python", "-m", "app.main", "worker", "--queues", "docling"]

# PaddleOCR (PP-StructureV3, CPU). `warmup` chạy thử một ảnh trắng để tải model vào /models/paddlex.
FROM base AS paddleocr
USER root
ENV PADDLE_PDX_CACHE_HOME=/models/paddlex PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install ".[paddleocr]" \
 && python -m app.steps.paddle_engine warmup \
 && chown -R app /models
USER app
CMD ["python", "-m", "app.main", "worker", "--queues", "docling"]
