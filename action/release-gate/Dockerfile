FROM python:3.11-slim

LABEL maintainer="GraQle <hello@graqle.dev>"
LABEL org.opencontainers.image.source="https://github.com/quantamixsol/graqle"
LABEL org.opencontainers.image.description="GraQle Release Gate — pre-publish KG + multi-agent governance gate"

RUN apt-get update && \
    apt-get install -y --no-install-recommends git jq gh && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir "graqle>=0.52.0"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
