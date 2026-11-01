# ==============================================================================
# Control Hub - Ultra-Lightweight Homelab Command Center (<25MB RAM)
# Multi-Arch: linux/amd64, linux/arm64
# ==============================================================================

FROM python:3.12-slim

LABEL maintainer="RAM-MAHESHWARI24"
LABEL description="High-performance, ultra-lean homelab dashboard and node management daemon"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONTROL_HUB_HOST=0.0.0.0 \
    CONTROL_HUB_PORT=7575

WORKDIR /app

# Install system dependencies (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl procps && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create unprivileged service user
RUN groupadd -g 1000 homelab && \
    useradd -u 1000 -g homelab -s /bin/sh -d /app homelab

# Copy application source
COPY . .
RUN chown -R homelab:homelab /app

# Switch to unprivileged user
USER homelab

EXPOSE 7575

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:7575/api/health || exit 1

CMD ["python", "server.py"]
