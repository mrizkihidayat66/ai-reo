# Hollows Hunter via Wine — process PE anomaly scanner by hasherezade
FROM scottyhardy/docker-wine:latest

ARG HH_VERSION=0.3.8

RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hollows_hunter \
    && wget -q \
        "https://github.com/hasherezade/hollows_hunter/releases/download/v${HH_VERSION}/hollows_hunter64.exe" \
        -O /opt/hollows_hunter/hollows_hunter.exe \
    && chmod +x /opt/hollows_hunter/hollows_hunter.exe

RUN ln -s /opt/hollows_hunter/hollows_hunter.exe /usr/local/bin/hollows_hunter.exe

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
