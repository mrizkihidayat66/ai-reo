# AI-REO — unipacker emulation-based PE unpacker
# Supports ASPack, FSG, MEW, MPRESS, PEtite, WinUPack, and YZPack.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ai-reo/unipacker" \
      org.opencontainers.image.description="unipacker emulation-based PE unpacker for AI-REO"

RUN pip install --no-cache-dir unipacker

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
