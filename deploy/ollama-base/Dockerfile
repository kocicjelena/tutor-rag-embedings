# A base image: Ollama, CPU-only, with `nomic-embed-text` already inside.
#
# Built on its own schedule (see build.sh and the workflow beside this file),
# pushed to GHCR, then consumed by the app image as:
#
#     FROM ghcr.io/<owner>/mcp-py-ollama:nomic-embed-text
#
# Why it is separate — Jelena's call, and the right one:
#
#   * the model is ~274 MB and never changes, so it has no business being
#     rebuilt every time a route changes;
#   * the same base serves the Hugging Face Space AND the laptop in
#     docs/LAPTOP8.md — `docker pull` instead of `ollama pull` over a home
#     connection;
#   * a failed model download fails *this* build, loudly, rather than becoming
#     a Space that starts and then cannot embed.
#
# ── Read this before trusting the size ────────────────────────────────────
# Ollama's Linux release is **1.36 GB** (v0.32.5, measured 2026-07-31), almost
# all of it GPU runners that cannot execute on a free CPU Space or on either of
# Jelena's laptops. The prune step below removes them and prints the before and
# after, because an unverified size claim in a comment is worth nothing.
# **Read the real number off the first build and record it in
# .claude/rules/DEPLOY-HF.md.** If the pruned image is still over ~800 MB, the fallback
# is discussed there.

FROM debian:12-slim

# Pin it. "latest" means an unrelated push six weeks from now can change what
# the Space runs, and the failure would look like an app bug.
ARG OLLAMA_VERSION=v0.32.5
ARG EMBED_MODEL=nomic-embed-text

ENV OLLAMA_MODELS=/opt/ollama/models \
    OLLAMA_HOST=127.0.0.1:11434 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl zstd \
 && rm -rf /var/lib/apt/lists/*

# ── Ollama, without the GPU runtimes ──────────────────────────────────────
RUN set -eux; \
    url="https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst"; \
    curl -fL --retry 3 "$url" -o /tmp/ollama.tar.zst; \
    mkdir -p /usr/local; \
    tar -C /usr/local --zstd -xf /tmp/ollama.tar.zst; \
    rm /tmp/ollama.tar.zst; \
    echo "=== unpacked ==="; du -sh /usr/local/lib/ollama 2>/dev/null || true; \
    # Nothing here has a GPU. These runners are hundreds of megabytes that can
    # never be loaded. Globs are permissive on purpose — the layout has changed
    # between releases and a missed directory is only wasted space, while a
    # deleted binary would fail the version check on the next line.
    rm -rf /usr/local/lib/ollama/cuda* \
           /usr/local/lib/ollama/*cuda* \
           /usr/local/lib/ollama/rocm* \
           /usr/local/lib/ollama/*rocm* \
           /usr/local/lib/ollama/runners/*cuda* \
           /usr/local/lib/ollama/runners/*rocm* || true; \
    echo "=== after pruning GPU runtimes ==="; du -sh /usr/local/lib/ollama 2>/dev/null || true; \
    # If pruning broke the install, fail here rather than at runtime.
    ollama --version

# ── The model, baked in ───────────────────────────────────────────────────
#
# `ollama pull` needs a running daemon, so one is started, used and stopped
# inside a single layer. The wait loop matters: a fixed `sleep` is how this
# becomes a build that fails once a month on a slow runner.
RUN set -eux; \
    ollama serve & \
    pid=$!; \
    for i in $(seq 1 60); do \
        if ollama list >/dev/null 2>&1; then break; fi; \
        if [ "$i" = 60 ]; then echo "ollama did not start within 60s" >&2; exit 1; fi; \
        sleep 1; \
    done; \
    ollama pull "${EMBED_MODEL}"; \
    ollama list; \
    kill "$pid"; \
    wait "$pid" 2>/dev/null || true; \
    echo "=== models ==="; du -sh /opt/ollama/models

# World-readable, because the app image does not run as root.
#
# Hugging Face Spaces run the container as UID 1000, and Ollama's default model
# path is /root/.ollama — unreadable to that user. A model baked into a
# directory nobody can read fails in a way that looks exactly like "the model
# was never downloaded", so the path is explicit and the permissions are set.
RUN chmod -R a+rX /opt/ollama

COPY verify.sh /usr/local/bin/verify
RUN chmod +x /usr/local/bin/verify

EXPOSE 11434
CMD ["ollama", "serve"]
