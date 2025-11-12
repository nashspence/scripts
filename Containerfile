# syntax=docker/dockerfile:1.7

ARG VERSION=dev
ARG VCS_REF=unknown
ARG VCS_URL=https://example.invalid

FROM python:3.12-slim

LABEL org.opencontainers.image.source="${VCS_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

RUN set -eux; \
    pip install --no-cache-dir pillow

WORKDIR /app
COPY padimg.py /app/padimg
ENTRYPOINT ["python", "/app/padimg"]
