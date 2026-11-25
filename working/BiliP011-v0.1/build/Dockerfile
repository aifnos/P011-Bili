FROM ubuntu:22.04@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config python3 python3-pip \
    autoconf automake libtool bison flex texinfo nasm yasm perl git \
    curl ca-certificates xz-utils bzip2 unzip file patch gettext \
    libegl-dev libgles-dev libsdl2-dev libpulse-dev \
    libxml2-dev libexpat1-dev libwayland-dev wayland-protocols \
    libfreetype-dev libharfbuzz-dev libfribidi-dev libass-dev \
    && python3 -m pip install --no-cache-dir meson==1.5.2
WORKDIR /opt/p011
RUN curl --fail --location --retry 2 --output toolchain.tar.bz2 \
    https://toolchains.bootlin.com/downloads/releases/toolchains/armv7-eabihf/tarballs/armv7-eabihf--glibc--bleeding-edge-2018.07-3.tar.bz2 \
    && echo '9c45a1c9cf5c70ed26348a7d2420733dbb7eb9eaae0b87ae2d6017a7f188f6ab  toolchain.tar.bz2' | sha256sum -c - \
    && tar -xjf toolchain.tar.bz2 \
    && mv armv7-eabihf--glibc--bleeding-edge-2018.07-3 sdk \
    && ./sdk/relocate-sdk.sh
ENV PATH="/opt/p011/sdk/bin:${PATH}"
WORKDIR /src
