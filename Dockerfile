FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY pyproject.toml README.md LICENSE ./
COPY graqle/ graqle/

# Install graqle with server extras
RUN pip install --no-cache-dir ".[server,api]"

# Default config and graph placeholders
COPY graqle.example.yaml /app/graqle.yaml

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["graq", "serve", "--host", "0.0.0.0", "--port", "8000"]
