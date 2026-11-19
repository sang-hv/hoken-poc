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

# Worker Docling: thêm Docling (torch CPU) và tải sẵn model lúc build để lúc chạy không cần mạng.
FROM base AS docling
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
 && pip install --extra-index-url https://download.pytorch.org/whl/cpu ".[docling]" \
 && docling-tools models download -o /models/docling \
 && chown -R app /models
ENV DOCLING_ARTIFACTS_PATH=/models/docling HF_HUB_OFFLINE=1
USER app
CMD ["python", "-m", "app.main", "worker", "--queues", "docling"]
