FROM registry.access.redhat.com/ubi8/ubi:latest

# UBI base image with the Cloudflare Origin CA baked into the system trust store,
# so anything built FROM it that talks to a *.devopstashtiot.page service (behind
# ingress-nginx's Cloudflare Origin cert) verifies TLS. UBI is RHEL-based, so use
# the ca-trust framework (update-ca-trust) — it's local (no network), which also
# means it builds fine inside the buildah pipeline.
COPY cloudflare-origin-ca-rsa-root.pem /etc/pki/ca-trust/source/anchors/cloudflare-origin-ca-rsa-root.pem
RUN update-ca-trust
