# JADX — Android DEX/APK/AAR/JAR decompiler to Java/Kotlin source
# skylot/jadx has no official Docker Hub image; built locally.
FROM eclipse-temurin:17-jre-jammy

ARG JADX_VERSION=1.5.1

LABEL org.opencontainers.image.title="ai-reo/jadx" \
      org.opencontainers.image.description="JADX Android decompiler for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/* \
    && wget -q \
        "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" \
        -O /tmp/jadx.zip \
    && unzip -q /tmp/jadx.zip -d /opt/jadx \
    && ln -s /opt/jadx/bin/jadx /usr/local/bin/jadx \
    && ln -s /opt/jadx/bin/jadx-gui /usr/local/bin/jadx-gui \
    && rm /tmp/jadx.zip \
    && apt-get purge -y --auto-remove wget ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
