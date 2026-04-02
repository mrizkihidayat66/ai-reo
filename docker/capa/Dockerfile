# AI-REO -- Mandiant FLARE capa capability detector
# Identifies ATT&CK and MBC techniques in PE, ELF, and shellcode.
#
# Rules are cloned from GitHub at build time so the container works
# fully offline at analysis time without any internet dependency.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ai-reo/capa" \
      org.opencontainers.image.description="Mandiant FLARE capa capability detector for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install capa, then clone the matching rules branch into /opt/capa-rules.
# capa >= 7.x no longer bundles rules in the wheel, so we embed them here.
# Try the exact major.minor version tag; fall back to main if it does not exist.
RUN pip install --no-cache-dir flare-capa \
    && CAPA_VER=$(python -c \
         "import capa; v=capa.__version__; parts=v.split('.'); print('v'+'.'.join(parts[:2]))" \
       ) \
    && echo "Cloning capa-rules ${CAPA_VER}" \
    && (git clone --depth 1 --branch "${CAPA_VER}" \
           https://github.com/mandiant/capa-rules.git /opt/capa-rules 2>/dev/null \
       || git clone --depth 1 \
              https://github.com/mandiant/capa-rules.git /opt/capa-rules) \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
