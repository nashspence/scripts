# syntax=docker/dockerfile:1.7

ARG VERSION=dev
ARG VCS_REF=unknown
ARG VCS_URL=https://example.invalid

FROM mwader/static-ffmpeg:latest AS ffmpeg

FROM python:3.12-alpine

LABEL org.opencontainers.image.source="${VCS_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

RUN apk add --no-cache \
      coreutils \
      tzdata \
      perl \
      exiftool \
      mediainfo

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

RUN pip install --no-cache-dir python-dateutil

WORKDIR /app
COPY when.py /app/when.py

ENTRYPOINT ["python", "/app/when.py"]
