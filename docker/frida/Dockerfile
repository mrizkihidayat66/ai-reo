FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir frida-tools

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
