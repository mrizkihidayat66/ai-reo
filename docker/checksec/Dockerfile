# AI-REO — checksec binary hardening analysis
# Reports PIE, NX, stack canary, RELRO, and Fortify Source protection status.
# Uses checksec.sh (bash) — avoids Python/lief dependency issues entirely.
FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="ai-reo/checksec" \
      org.opencontainers.image.description="checksec binary hardening analysis for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        binutils \
        file \
        curl \
        ca-certificates \
    && curl --fail -sSL https://raw.githubusercontent.com/slimm609/checksec.sh/2.7.1/checksec \
       -o /usr/local/bin/checksec \
    && chmod +x /usr/local/bin/checksec \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
