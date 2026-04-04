# PE-sieve via Wine — in-memory PE scanner by hasherezade
FROM scottyhardy/docker-wine:latest

ARG PESIEVE_VERSION=0.3.9

RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/pe-sieve \
    && wget -q \
        "https://github.com/hasherezade/pe-sieve/releases/download/v${PESIEVE_VERSION}/pe-sieve64.exe" \
        -O /opt/pe-sieve/pe-sieve.exe \
    && chmod +x /opt/pe-sieve/pe-sieve.exe

# Convenience symlink so "wine pe-sieve.exe" resolves without full path
RUN ln -s /opt/pe-sieve/pe-sieve.exe /usr/local/bin/pe-sieve.exe

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
