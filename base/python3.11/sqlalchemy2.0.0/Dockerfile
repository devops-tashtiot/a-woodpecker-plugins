FROM docker.io/library/python:3.11-slim

# Python 3.11 + SQLAlchemy 2.0.0 (new API: db.execute(text("SELECT ...")); the
# legacy db.execute("SELECT ...") from 1.4 now raises). Cloudflare Origin CA baked
# into the Debian trust store (update-ca-certificates, local/no-network).
COPY cloudflare-origin-ca-rsa-root.pem /usr/local/share/ca-certificates/cloudflare-origin-ca-rsa-root.crt
RUN update-ca-certificates \
 && pip install --no-cache-dir "SQLAlchemy==2.0.0"
