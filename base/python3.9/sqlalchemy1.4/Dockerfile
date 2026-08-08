FROM docker.io/library/python:3.9-slim

# Python 3.9 + SQLAlchemy 1.4 (legacy execution API: db.execute("SELECT ...")).
# Cloudflare Origin CA baked into the Debian trust store (update-ca-certificates,
# local/no-network) so code that reaches a *.devopstashtiot.page service verifies
# TLS. pip install needs PyPI network, which the buildah build has (only apk's
# self-TLS was the earlier problem, not connectivity).
COPY cloudflare-origin-ca-rsa-root.pem /usr/local/share/ca-certificates/cloudflare-origin-ca-rsa-root.crt
RUN update-ca-certificates \
 && pip install --no-cache-dir "SQLAlchemy==1.4.54"
