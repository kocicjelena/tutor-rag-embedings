# The app image — Next.js, FastAPI and Ollama in one container.
#
# One image, three destinations: the Hugging Face Space, the laptop in
# docs/ops/LAPTOP8.md, and a VPS later. That is deliberate (docs/PLAN.md
# §"The property that makes this low-risk") and it is why nothing in here is
# Spaces-specific except the default port.
#
#     docker build -t mcp-py .
#     docker run -p 7860:7860 -v "$PWD/data:/data" --env-file .env mcp-py
#
# The Ollama layer is NOT built here. It comes from deploy/ollama-base, built
# and pushed separately, because a 1.36 GB download plus a 274 MB model has no
# business being rebuilt every time a route changes. Build that first:
#     Actions → "Ollama base image" → Run workflow

# syntax=docker/dockerfile:1

ARG OLLAMA_BASE=ghcr.io/kocicjelena/mcp-py-ollama:nomic-embed-text


# ──────────────────────────── 1. The frontend ────────────────────────────
#
# Node is needed to *build* and to *run* the Next server, but the 400 MB of
# build tooling is not. It stays in this stage; only the traced bundle and one
# node binary cross into the final image.
FROM node:22-slim AS web

WORKDIR /src

# Dependencies first, and only the manifests, so this layer is cached until a
# dependency actually changes — not on every source edit.
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci

COPY web ./web
# `turbopack.root` in next.config.js points at the repo root, which is why the
# app is built at /src/web with /src present rather than at / directly. The
# traced output mirrors that, so everything lands under standalone/web/.
RUN cd web && npm run build \
 && test -f .next/standalone/web/server.js


# ──────────────────────────── 2. Python deps ─────────────────────────────
#
# Resolved from uv.lock, so the image gets the exact versions the tests ran
# against. `--frozen` fails rather than silently re-resolving if the lock and
# pyproject.toml have drifted — on a deploy that is the behaviour you want.
# debian:12-slim, and not python:3.11-slim, for one specific reason: a venv
# records an absolute path to the interpreter that created it. The final image
# is Debian 12 (via the Ollama base), whose `python3` is 3.11 at
# /usr/bin/python3.11. Building the venv on the *same* distro means that path
# is real in both stages. Building it on python:3.11-slim would point it at
# /usr/local/bin/python3.11 and require smuggling the interpreter across —
# which works until a shared library it needs is missing, and then fails at
# runtime rather than at build time.
FROM debian:12-slim AS deps

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Pinned, for the same reason the Ollama version is: `latest` means an
# unrelated release can change what your Space installs, on a day you did not
# touch anything. 0.11.28 is what resolved uv.lock locally.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# --frozen: fail rather than re-resolve if the lock and pyproject have drifted.
# --no-install-project: the app is copied as source, not installed as a package.
# --no-dev: pytest and pyright are not deployed.
#
# Every dependency here has a manylinux wheel for cp311, so no compiler is
# needed. If that ever stops being true the build fails loudly here with a
# missing-wheel error — add build-essential at that point, not pre-emptively.
RUN uv sync --frozen --no-install-project --no-dev --python /usr/bin/python3 \
 && /opt/venv/bin/python -c "import fastapi, sqlmodel, sqlite_vec, anthropic, mcp; print('deps ok')"


# ──────────────────────────── 3. The runtime ─────────────────────────────
FROM ${OLLAMA_BASE} AS runtime

# The same Debian 12 python3 the venv was built against — same distro, same
# path (/usr/bin/python3.11), so the venv's recorded interpreter is real.
# curl is not decoration: start.sh uses it to wait for each service, and the
# HEALTHCHECK below uses it too.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 \
        libstdc++6 \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Node is needed only to *run* server.js, so the binary comes across on its own
# rather than the whole node image. node:22-slim is bookworm as well, so it
# links against this glibc and this libstdc++ — that match is the only reason
# copying a bare binary is sound here rather than a trick that happens to work.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node

COPY --from=deps /opt/venv /opt/venv

# Fail at build time if either runtime is broken, rather than at boot.
RUN node --version \
 && /opt/venv/bin/python --version \
 && /opt/venv/bin/python -c "import sqlite_vec, sqlite3; \
c = sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c); \
print('sqlite-vec', c.execute('select vec_version()').fetchone()[0])"

WORKDIR /app

# The backend.
COPY pyproject.toml ./
COPY app ./app

# The frontend: the standalone server, plus the two directories Next does NOT
# trace into it. `.next/static` and `public` are served by the node server but
# resolved at runtime, so a build that forgets them looks fine until every
# stylesheet and image 404s.
COPY --from=web /src/web/.next/standalone/web ./web
COPY --from=web /src/web/.next/static ./web/.next/static
# (there is no web/public in this project; add a COPY here if one appears)

COPY deploy/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# ── The user, and the two writable directories ───────────────────────────
#
# Hugging Face Spaces run the container as UID 1000. Everything this process
# writes has to be owned by that user, and there are exactly two such places:
# /data (the SQLite file) and Ollama's runtime scratch. Getting this wrong
# produces a container that starts and then fails on the first upload.
RUN useradd --uid 1000 --create-home --shell /bin/bash appuser \
 && mkdir -p /data /home/appuser/.ollama \
 && chown -R appuser:appuser /data /home/appuser /app

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_DIR=/app \
    DATA_DIR=/data \
    SQLITE_PATH=/data/rag.db \
    API_PORT=8000 \
    PORT=7860 \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_MODELS=/opt/ollama/models \
    NODE_ENV=production \
    ENVIRONMENT=production \
    EMBEDDING_PROVIDER=ollama \
    EMBEDDING_MODEL=nomic-embed-text \
    EMBEDDING_DIMENSIONS=768 \
    DEFAULT_CHAT_PROVIDER=claude \
    ANTHROPIC_API_KEY="" \
    ALLOW_APP_KEY_FALLBACK=false

# Two defaults above are deployment decisions, not conveniences:
#
#   DEFAULT_CHAT_PROVIDER=claude — there is no chat model in this image. Only
#   nomic-embed-text is baked in, because a generation model is gigabytes and
#   would be unusably slow on 2 shared vCPUs. Embedding is local; generation is
#   Claude. Locally you override this back to ollama.
#
#   ALLOW_APP_KEY_FALLBACK=false — with a public URL, `true` means every visitor
#   spends the operator's Anthropic balance. This is the setting BYOK exists to
#   make safe: visitors bring their own key. Do not flip it to ship a demo.
#
# SECRET_KEY and IDENTITY_PEPPER are deliberately absent. ENVIRONMENT=production
# makes app/core/config.py refuse to start on a placeholder SECRET_KEY, and
# start.sh checks first so the failure is one clear line rather than a traceback
# three processes deep. Supply them as Space secrets or --env-file.

USER appuser
VOLUME ["/data"]
EXPOSE 7860

# Checks the whole chain — the Next server answers only if it is up, and /health
# answers only if FastAPI started and sqlite-vec loaded.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null \
     && curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null || exit 1

CMD ["/usr/local/bin/start.sh"]
