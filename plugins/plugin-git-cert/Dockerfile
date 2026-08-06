FROM woodpeckerci/plugin-git

# The clone step reaches Bitbucket internally via ingress-nginx, which presents a
# Cloudflare Origin CA-issued cert (not publicly trusted). Baking the CA in here means
# the clone step doesn't need custom_ssl_url to re-fetch it on every pipeline run.
COPY cloudflare-origin-ca-rsa-root.pem /usr/local/share/ca-certificates/cloudflare-origin-ca-rsa-root.crt
RUN update-ca-certificates
