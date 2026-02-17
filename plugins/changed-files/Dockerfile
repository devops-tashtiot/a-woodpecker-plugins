FROM artifactory.company.zucaim/woodpecker/base/ubi-minimal:9.5-1745855087

WORKDIR /app

RUN microdnf -y install git && \
    microdnf clean all

COPY changed.sh changed.sh

RUN chmod +x changed.sh
RUN git config --global --add safe.directory '*'

ENTRYPOINT /app/changed.sh
