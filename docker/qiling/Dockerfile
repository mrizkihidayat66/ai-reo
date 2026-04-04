FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ libffi-dev zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir qiling

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
