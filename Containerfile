# syntax=docker/dockerfile:1.7

ARG VERSION=dev
ARG VCS_REF=unknown
ARG VCS_URL=https://example.invalid

FROM python:3.12-alpine

LABEL org.opencontainers.image.source="${VCS_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

RUN set -eux; \
    apk add --no-cache cdrkit coreutils; \
    genisoimage --version

WORKDIR /app
COPY mkiso.py /app/mkiso
ENTRYPOINT ["python", "/app/mkiso"]
