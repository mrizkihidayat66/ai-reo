# AI-REO — GNU binutils (objdump, readelf, nm)
# Lightweight Debian image for binary header, section, and symbol inspection.
FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="ai-reo/objdump" \
      org.opencontainers.image.description="GNU binutils (objdump/readelf/nm) for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends binutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
