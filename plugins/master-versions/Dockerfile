FROM netanelzucaim123/python-git-cliff:latest

WORKDIR /app

# Build context must be the repo root:
#   docker build -f plugins/master-versions/Dockerfile -t <image> .
COPY release.py /app/release.py
COPY cliff.toml /app/cliff.toml

ENTRYPOINT ["python3", "/app/release.py"]




