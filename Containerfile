# syntax=docker/dockerfile:1.7

ARG VERSION=dev
ARG VCS_REF=unknown
ARG VCS_URL=https://example.invalid
FROM --platform=$TARGETPLATFORM mwader/static-ffmpeg:latest AS ffmpeg
FROM --platform=$TARGETPLATFORM python:3.12-alpine

LABEL org.opencontainers.image.source="${VCS_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

RUN set -eux; \
    echo "https://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories; \
    apk add --no-cache coreutils curl tar xz mkvtoolnix ttf-dejavu; \
    mkvmerge --version

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

WORKDIR /app
COPY qcut.py /app/qcut
ENTRYPOINT ["python", "/app/qcut"]
