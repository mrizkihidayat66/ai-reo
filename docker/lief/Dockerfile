# AI-REO — LIEF deep binary structural parser
# Parses PE, ELF, and Mach-O: sections, imports, exports, TLS callbacks, signatures.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ai-reo/lief" \
      org.opencontainers.image.description="LIEF deep binary structural parser for AI-REO"

RUN pip install --no-cache-dir "lief==0.14.1"

COPY lief_parse.py /app/lief_parse.py

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
