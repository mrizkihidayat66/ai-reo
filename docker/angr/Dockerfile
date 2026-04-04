# AI-REO — angr symbolic execution engine
# Provides path exploration, constraint solving, and vulnerability confirmation for binaries.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ai-reo/angr" \
      org.opencontainers.image.description="angr symbolic execution engine for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential gcc g++ libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir angr

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
