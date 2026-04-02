# AI-REO — Detect-It-Easy (diec) packer/compiler/protector identification
# Identifies packers, compilers, and protectors from binary signatures.
FROM ubuntu:22.04

LABEL org.opencontainers.image.title="ai-reo/die" \
      org.opencontainers.image.description="Detect-It-Easy packer/compiler detector for AI-REO"

ARG DIE_VERSION=3.09

RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && wget -q "https://github.com/horsicq/DIE-engine/releases/download/${DIE_VERSION}/die_${DIE_VERSION}_Ubuntu_22.04_amd64.deb" \
    && dpkg -i "die_${DIE_VERSION}_Ubuntu_22.04_amd64.deb" \
    || apt-get install -fy --no-install-recommends \
    && rm -f "die_${DIE_VERSION}_Ubuntu_22.04_amd64.deb" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
