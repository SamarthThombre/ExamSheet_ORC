# Multi-stage / slim production image for exam paper extractor v2
# Uses Python 3.13 to match working environment Python version
FROM python:3.13-slim

# Install minimal OS runtime dependencies for OpenCV and ONNX runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root application user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

WORKDIR /app

# Copy production requirements and install
COPY requirements-prod.txt /app/requirements-prod.txt
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application source code, models, configs, and frontend
COPY app /app/app
COPY ocr_v2 /app/ocr_v2
COPY configs /app/configs
COPY models /app/models
COPY frontend /app/frontend

# Create and grant permissions for job storage
RUN mkdir -p /app/data/jobs && chown -R appuser:appuser /app

# Run as non-root user
USER appuser

EXPOSE 8000

ENV HOST=0.0.0.0 \
    PORT=8000 \
    WORKERS=2 \
    ORT_THREADS=4 \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
