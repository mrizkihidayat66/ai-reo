# AI-REO — FLARE FLOSS obfuscated string solver
# Extracts static, stack-based, and decoded strings from packed/obfuscated binaries.
# build-essential provides gcc/g++ for flare-floss's compiled extension deps (capstone, unicorn).
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ai-reo/floss" \
      org.opencontainers.image.description="FLARE FLOSS obfuscated string solver for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir flare-floss

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
