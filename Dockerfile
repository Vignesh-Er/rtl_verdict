# UNTESTED. This image has never been built or run.
#
# Docker Desktop requires an admin-level install on the machine this
# project was developed on, which was not available (see FINDINGS.md).
# This Dockerfile is believed correct by inspection - it mirrors
# docs/REPRODUCE.md's Linux install steps (themselves also untested by
# this project - developed and validated on Windows 11 only, see that
# file) onto a Linux base image - but "believed correct" is not the same
# claim as "verified." Do not report this as a working reproduction path
# until someone with a working Docker install has actually run it.
#
# If you do get this running, please also run `make verify` inside the
# container and update this header (remove UNTESTED, note what you ran
# it on) rather than silently assuming it worked.

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    make bash curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# OSS CAD Suite Linux release - pinned to a specific tag rather than
# "latest" so a container build today and one built next year use the
# same toolchain this project's results were validated against (see
# docs/REPRODUCE.md's Windows toolchain-versions table for the matching
# Windows build - this tag is the closest available Linux release to it,
# NOT verified to produce byte-identical tool versions, since the whole
# point of this file being untested is that no one has checked).
ARG OSS_CAD_SUITE_TAG=2026-08-01
RUN curl -fsSL -o /tmp/oss-cad-suite.tgz \
      "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_SUITE_TAG}/oss-cad-suite-linux-x64-$(echo ${OSS_CAD_SUITE_TAG} | tr -d '-').tgz" \
    && mkdir -p /opt/oss-cad-suite \
    && tar -xzf /tmp/oss-cad-suite.tgz -C /opt \
    && rm /tmp/oss-cad-suite.tgz

ENV RTLVERDICT_OSS_CAD_ROOT=/opt/oss-cad-suite

WORKDIR /rtlverdict
COPY requirements.txt .
RUN python3 -m venv /rtlverdict/.venv \
    && /rtlverdict/.venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

RUN /rtlverdict/.venv/bin/python -m rtlverdict.doctor

CMD ["/rtlverdict/.venv/bin/python", "scripts/verify.py"]
