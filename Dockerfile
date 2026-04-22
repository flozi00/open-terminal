# Pin to a specific patch version for reproducible builds.
# To pick up security patches, bump this version and rebuild.
FROM python:3.12.13

ARG RTK_VERSION=0.35.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core utilities
    coreutils findutils grep sed gawk diffutils patch \
    less file tree bc man-db \
    # Networking
    curl wget net-tools iputils-ping dnsutils netcat-openbsd socat telnet \
    openssh-client rsync \
    # Editors
    vim nano \
    # Version control
    git \
    # Build tools
    build-essential cmake make pkg-config \
    # Scripting & languages
    perl ruby-full lua5.4 \
    # Python system packages
    python3-dev python3-venv \
    # Data processing
    jq xmlstarlet sqlite3 \
    # Media & documents
    ffmpeg pandoc imagemagick texlive-latex-base \
    # Compression
    zip unzip tar gzip bzip2 xz-utils zstd p7zip-full \
    # Search tools
    ripgrep fd-find \
    # Fun
    cowsay figlet \
    # System
    procps htop lsof strace sysstat \
    sudo tmux screen tini iptables ipset dnsmasq \
    ca-certificates gnupg apt-transport-https \
    # Capabilities (needed for setcap on Python binary)
    libcap2-bin \
    && rm -rf /var/lib/apt/lists/*

# Node.js (LTS)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI + Compose + Buildx (mount socket at runtime for access)
RUN curl -fsSL https://get.docker.com | sh

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) rtk_target="x86_64-unknown-linux-musl" ;; \
        arm64) rtk_target="aarch64-unknown-linux-gnu" ;; \
        *) echo "Unsupported architecture for RTK: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk-${rtk_target}.tar.gz" -o /tmp/rtk.tar.gz; \
    tar -xzf /tmp/rtk.tar.gz -C /usr/local/bin rtk; \
    chmod +x /usr/local/bin/rtk; \
    rm -f /tmp/rtk.tar.gz

# Uncomment to apply security patches beyond what the base image provides.
# Not recommended for reproducible builds; prefer bumping the base image tag.
# RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*


WORKDIR /app

RUN pip install --no-cache-dir \
    numpy pandas scipy scikit-learn \
    polars pyarrow \
    matplotlib seaborn plotly \
    jupyterlab notebook ipython ipykernel \
    httpx requests beautifulsoup4 lxml \
    sqlalchemy psycopg2-binary \
    pyyaml toml jsonlines \
    tqdm rich sympy \
    pillow opencv-python \
    openpyxl weasyprint \
    python-docx python-pptx pypdf csvkit \
    pytest ruff black mypy

COPY . .
# Create a capability-bearing Python copy for the server process only.
# The system python3 stays clean so user-spawned Python processes remain
# dumpable (readable via /proc/[pid]/fd/ for port detection).
RUN pip install --no-cache-dir ".[browser]" \
    && cp "$(readlink -f "$(which python3)")" /usr/local/bin/python3-ot \
    && setcap cap_setgid+ep /usr/local/bin/python3-ot \
    && sed -i "1s|.*|#!/usr/local/bin/python3-ot|" "$(which open-terminal)"

# Install Playwright Chromium browser + OS dependencies
RUN playwright install --with-deps

RUN useradd -m -s /bin/bash user && echo 'user ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER user
ENV SHELL=/bin/bash
ENV PATH="/home/user/.local/bin:${PATH}"
WORKDIR /home/user

EXPOSE 8000

COPY entrypoint.sh /app/entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["run"]
