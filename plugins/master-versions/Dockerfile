FROM docker.io/netanelzucaim123/python-git-cliff:latest

WORKDIR /app

# Trust Cloudflare's Origin CA root. On a pull_request event,
# _retrieve_pull_request_message() in release.py fetches the PR description
# directly from bitbucket.devopstashtiot.page's REST API via urlopen().
# In-cluster callers reach that hostname through a CoreDNS rewrite straight to
# ingress-nginx, which terminates TLS with a real Cloudflare Origin CA
# certificate — a cert type that's deliberately not in any public trust
# store, so the default urlopen() SSL context rejects it with
# CERTIFICATE_VERIFY_FAILED. Baked in at build time here (rather than fetched
# at runtime like pr.yml's clone step does via custom_ssl_url) so release.py
# needs no SSL-context code of its own — Python's default context already
# reads the OS trust store that update-ca-certificates writes to. Same public
# PEM Cloudflare hosts for this exact purpose, not pulled from SSM, so no new
# secret is needed.
RUN apk add --no-cache ca-certificates && \
    wget -q -O /usr/local/share/ca-certificates/cloudflare-origin-ca-root.crt \
      https://developers.cloudflare.com/ssl/static/origin_ca_rsa_root.pem && \
    update-ca-certificates

# Build context must be the repo root:
#   docker build -f plugins/master-versions/Dockerfile -t <image> .
COPY release.py /app/release.py
COPY cliff.toml /app/cliff.toml

ENTRYPOINT ["python3", "/app/release.py"]

