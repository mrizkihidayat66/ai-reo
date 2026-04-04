# AI-REO -- Mandiant FLARE capa capability detector
# Identifies ATT&CK and MBC techniques in PE, ELF, and shellcode.
#
# Installed via pip — the capa Python package bundles its rules,
# so no separate binary download or rules archive is needed.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ai-reo/capa" \
      org.opencontainers.image.description="Mandiant FLARE capa capability detector for AI-REO"

RUN pip install --no-cache-dir flare-capa

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
