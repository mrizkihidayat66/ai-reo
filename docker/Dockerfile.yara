# YARA pattern-matching engine for binary signatures and rule scanning.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends yara \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
CMD ["/bin/sh"]
