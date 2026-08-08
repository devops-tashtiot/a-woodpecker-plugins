FROM docker.io/alpine/git:latest

# Base image for the pipeline's git-command steps ("Push changelogs to Git",
# "Mirror to GitHub"). Those steps talk to bitbucket.devopstashtiot.page over TLS
# terminated by a Cloudflare Origin CA cert that no public trust store carries, so
# without this the git calls fail with "unable to get local issuer certificate"
# (which the pipelines used to paper over with `git config http.sslVerify false`).
# Baking the Origin CA root in lets git verify TLS normally — same approach as
# plugins/plugin-git-cert (the clone image) and plugins/master-versions.
COPY cloudflare-origin-ca-rsa-root.pem /usr/local/share/ca-certificates/cloudflare-origin-ca-rsa-root.crt
# alpine/git doesn't ship the ca-certificates package (no update-ca-certificates),
# so install it before folding the Origin CA into the trust bundle.
RUN apk add --no-cache ca-certificates && update-ca-certificates
