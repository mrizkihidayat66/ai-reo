# APKiD — Android packer/obfuscator identifier
FROM python:3.11-slim

# libmagic1 provides libmagic.so required by python-magic (apkid dependency).
# build-essential provides gcc/make for compiling yara-python's C extension.
# Do NOT install system libyara* — version conflicts cause apkid import failures.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
        build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir apkid

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
