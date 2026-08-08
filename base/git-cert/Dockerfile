FROM docker.io/alpine/git:latest

# Bake the Cloudflare Origin CA into the trust bundle so the pipeline's git-command
# steps (changelog push, GitHub mirror) verify TLS to bitbucket.devopstashtiot.page
# instead of needing `git config http.sslVerify false`.
#
# Append directly to the existing bundle rather than `update-ca-certificates`:
# alpine/git ships `ca-certificates-bundle` (so git's HTTPS works and
# /etc/ssl/certs/ca-certificates.crt exists) but NOT the `ca-certificates` package,
# so update-ca-certificates is absent — and `apk add` has no working network inside
# the buildah build (APKINDEX fetch fails with a TLS error). A plain append needs
# no package and no network. git reads this bundle by default on Alpine.
COPY cloudflare-origin-ca-rsa-root.pem /tmp/cloudflare-origin-ca-rsa-root.pem
RUN cat /tmp/cloudflare-origin-ca-rsa-root.pem >> /etc/ssl/certs/ca-certificates.crt \
 && rm /tmp/cloudflare-origin-ca-rsa-root.pem
