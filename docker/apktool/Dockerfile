# Apktool — Android APK disassembly and resource decoding
FROM eclipse-temurin:17-jre-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && wget -q \
        "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar" \
        -O /opt/apktool.jar \
    && printf '#!/bin/sh\nexec java -jar /opt/apktool.jar "$@"\n' > /usr/local/bin/apktool \
    && chmod +x /usr/local/bin/apktool

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
