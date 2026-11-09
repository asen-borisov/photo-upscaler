# Reproducible Linux build. Ubuntu 22.04 = oldest supported system (newer ones run it too).
#   docker build -t photo-upscaler-build linux
#   docker run --rm -v "$PWD:/src:ro" -v "$PWD/dist:/out" photo-upscaler-build bash -c \
#     "cp -r /src /work && cd /work && rm -rf .venv dist build engine && ./build.sh && cp dist/*.tar.gz /out/"
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends software-properties-common gpg-agent \
 && add-apt-repository -y ppa:deadsnakes/ppa && apt-get update \
 && apt-get install -y --no-install-recommends \
      python3.11 python3.11-venv python3.11-dev binutils ca-certificates \
      libvulkan1 mesa-vulkan-drivers libgomp1 \
      libnss3 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
      libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-randr0 libxcb-xkb1 libegl1 libgl1 \
      libfontconfig1 libdbus-1-3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2 libxkbfile1 \
      libpulse0 \
      xvfb x11-apps imagemagick \
 && ln -sf /usr/bin/python3.11 /usr/local/bin/python3 \
 && rm -rf /var/lib/apt/lists/*
