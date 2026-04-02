# AI-REO — YARA pattern matching engine
# Debian-based image for binary signature scanning and custom YARA rule execution.
FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="ai-reo/yara" \
      org.opencontainers.image.description="YARA pattern matching engine for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends yara \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
