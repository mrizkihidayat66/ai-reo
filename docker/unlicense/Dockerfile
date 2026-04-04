# unlicense — dynamic Themida/WinLicense 2.x & 3.x unpacker
# Requires Wine to instrument the target PE process during unpacking.
# Uses Ubuntu 22.04 + distro Wine to avoid dependency on third-party base images.
FROM ubuntu:22.04

ARG UNLICENSE_VERSION=0.4.0

ENV DEBIAN_FRONTEND=noninteractive

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        wget ca-certificates \
        unzip \
        wine wine32 wine64 \
    && rm -rf /var/lib/apt/lists/* \
    && wget -q \
        "https://github.com/ergrelet/unlicense/releases/download/${UNLICENSE_VERSION}/unlicense-py3.11-x64.zip" \
        -O /tmp/unlicense.zip \
    && mkdir -p /opt/unlicense \
    && unzip -q /tmp/unlicense.zip -d /opt/unlicense \
    && printf '%s\n' '#!/bin/sh' 'exec wine /opt/unlicense/unlicense.exe "$@"' > /usr/local/bin/unlicense \
    && chmod +x /usr/local/bin/unlicense \
    && rm -rf /tmp/unlicense.zip

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
