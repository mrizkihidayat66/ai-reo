# AI-REO — Binwalk firmware and archive analyzer
# Scans binaries for embedded files, compressed archives, and firmware signatures.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ai-reo/binwalk" \
      org.opencontainers.image.description="Binwalk firmware and archive analyzer for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
        binutils \
        file \
        zlib1g \
        liblzma5 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir binwalk python-magic

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
