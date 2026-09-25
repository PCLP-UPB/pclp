# syntax=docker/dockerfile:1
# PCLP — mediul de lucru al studentului (code-server + toolchain C + portal + înregistrare proces).
# Build context = rădăcina repo-ului:  docker compose -f env/compose.yaml build
# Multi-arch:  docker buildx build --platform linux/amd64,linux/arm64 -f env/Dockerfile -t <img> --push .
FROM ubuntu:24.04

ARG TARGETARCH
ARG CODE_SERVER_VERSION=4.138.0
ARG NODE_MAJOR=22
ARG PCLP_VERSION=dev
# 1 = imaginea eșuează dacă pipeline-ul de conținut eșuează (recomandat pentru release)
ARG PCLP_STRICT_CONTENT=0
ENV DEBIAN_FRONTEND=noninteractive \
    PCLP_VERSION=${PCLP_VERSION}

LABEL org.opencontainers.image.title="pclp-env" \
      org.opencontainers.image.description="Mediu de lucru PCLP (C, code-server, portal)" \
      org.opencontainers.image.version="${PCLP_VERSION}"

# 1) Imaginea Ubuntu este "minimizată": exclude /usr/share/man și înlocuiește `man` cu un stub.
#    Scoatem excluderile ÎNAINTE de a instala pachete, apoi restaurăm `man` real.
RUN rm -f /etc/dpkg/dpkg.cfg.d/excludes \
 && if [ -f /usr/bin/man.REAL ] || dpkg-divert --list /usr/bin/man | grep -q man; then \
      rm -f /usr/bin/man; dpkg-divert --quiet --remove --rename /usr/bin/man; fi \
 && userdel -r ubuntu 2>/dev/null || true

# 2) Toolchain C + utilitare + pagini de manual
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential gcc clang clangd gdb valgrind make cppcheck clang-format \
      git inotify-tools python3 python3-venv curl ca-certificates less nano \
      locales man-db manpages manpages-dev manpages-posix manpages-posix-dev mandoc \
      bash-completion procps util-linux file xxd gnupg tzdata \
 && apt-get install -y --reinstall --no-install-recommends \
      coreutils bash grep sed findutils tar gzip diffutils procps util-linux \
 && sed -i -e 's/^# *\(en_US.UTF-8\)/\1/' -e 's/^# *\(ro_RO.UTF-8\)/\1/' /etc/locale.gen \
 && locale-gen \
 && mandb -q || true \
 && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 TZ=Europe/Bucharest

# 3) Node.js LTS (NodeSource) — pentru CLI-urile AI instalate opțional de student (pclp ai-install)
RUN mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# 4) code-server (release oficial .deb, arhitectura din TARGETARCH)
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
 && curl -fsSL -o /tmp/cs.deb \
      "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server_${CODE_SERVER_VERSION}_${arch}.deb" \
 && dpkg -i /tmp/cs.deb && rm -f /tmp/cs.deb

# 5) Utilizatorul student (uid 1000)
RUN useradd -m -u 1000 -U -s /bin/bash student \
 && mkdir -p /home/student/work /opt/pclp/extensions \
 && git config --system init.defaultBranch main \
 && git config --system --add safe.directory '*' \
 && git config --system core.quotepath false

# 6) Extensii VS Code din Open VSX, într-un director comun (nu în $HOME, care nu e persistent)
RUN for ext in llvm-vs-code-extensions.vscode-clangd webfreak.debug Continue.continue; do \
      code-server --extensions-dir /opt/pclp/extensions --install-extension "$ext" || exit 1; \
    done \
 && chown -R student:student /opt/pclp/extensions

# 7) Python venv pentru portal
COPY portal/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/pclp/venv \
 && /opt/pclp/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/pclp/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# 8) Scripturi, configurații, șabloane
COPY env/rootfs/ /
RUN cat /opt/pclp/shell/bash.bashrc.append >> /etc/bash.bashrc \
 && cp /opt/pclp/shell/student.bashrc /home/student/.bashrc \
 && mkdir -p /home/student/.config/code-server \
 && cp /opt/pclp/code-server/config.yaml /home/student/.config/code-server/config.yaml \
 && chown -R student:student /home/student \
 && chmod 0755 /opt/pclp/bin/* /opt/pclp/wrap/pclp-wrap \
 && for t in gcc cc clang make valgrind; do ln -sf pclp-wrap /opt/pclp/wrap/$t; done

# 9) Codul cursului (portal, conținut, unelte). `content*` = tolerant dacă directorul lipsește încă.
COPY tools/ /opt/pclp/tools/
COPY portal/ /opt/pclp/portal/
COPY content* /opt/pclp/content/
COPY sources/ /opt/pclp/sources/
RUN chmod 0755 /opt/pclp/tools/pclp /opt/pclp/tools/pclp-verify \
 && ln -sf /opt/pclp/tools/pclp /usr/local/bin/pclp \
 && if [ -f /opt/pclp/content/pipeline/build.py ]; then \
      cd /opt/pclp/content && /opt/pclp/venv/bin/python /opt/pclp/content/pipeline/build.py --out /opt/pclp/content/build \
      || { echo "!!! build-ul de conținut a eșuat"; [ "$PCLP_STRICT_CONTENT" = 1 ] && exit 1; true; }; \
    else echo "content/pipeline/build.py lipsește — sar peste build-ul de conținut"; fi \
 && mkdir -p /opt/pclp/content/build

ENV PATH=/opt/pclp/wrap:/opt/pclp/bin:/home/student/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    NPM_CONFIG_PREFIX=/home/student/.npm-global \
    CLAUDE_CONFIG_DIR=/home/student/.claude \
    PCLP_WORK=/home/student/work \
    PCLP_CONTENT=/opt/pclp/content/build \
    PCLP_STATE=/home/student/work/.pclp/state \
    PCLP_HOME=/opt/pclp \
    PCLP_TOOLS=/opt/pclp/tools \
    PCLP_CONTENT_URL=https://github.com/PCLP-UPB/pclp/releases/latest/download/content.json

WORKDIR /home/student/work
EXPOSE 8080 8000
# Pornește ca root doar cât să ajusteze uid-ul/permisiunile, apoi coboară la `student`.
ENTRYPOINT ["/opt/pclp/bin/entrypoint"]
