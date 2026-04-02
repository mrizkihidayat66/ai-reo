# AI-REO — UPX packer detection and decompression
# Alpine-based image for UPX binary listing and unpacking.
FROM alpine:3.20

LABEL org.opencontainers.image.title="ai-reo/upx" \
      org.opencontainers.image.description="UPX packer detection and decompression for AI-REO"

RUN apk add --no-cache upx

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
