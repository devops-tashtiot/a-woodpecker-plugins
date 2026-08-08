FROM docker.io/woodpeckerci/plugin-prettier:1.4.0

# The upstream Woodpecker prettier plugin (Alpine-based) with the Cloudflare Origin
# CA baked into the trust bundle, so when it runs in-cluster and reaches a
# *.devopstashtiot.page service it verifies TLS. Append directly to the existing
# bundle: alpine/plugin-prettier ships ca-certificates-bundle (so /etc/ssl/certs/
# ca-certificates.crt exists) but NOT the ca-certificates package, so
# update-ca-certificates is absent — and apk has no network inside the buildah
# build. A plain append needs no package and no network.
COPY cloudflare-origin-ca-rsa-root.pem /tmp/cloudflare-origin-ca-rsa-root.pem
RUN cat /tmp/cloudflare-origin-ca-rsa-root.pem >> /etc/ssl/certs/ca-certificates.crt \
 && rm /tmp/cloudflare-origin-ca-rsa-root.pem
