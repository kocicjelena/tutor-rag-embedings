#!/usr/bin/env bash
# Start the three processes that make up the deployed app, in one container.
#
#     ollama    :11434   embedding only — never reachable from outside
#     fastapi   :8000    the API, on localhost
#     next      :7860    the only public port
#
# Not supervisord, not s6. Three processes with one rule between them — if any
# of them dies the container should die too — is about forty lines of bash, and
# a supervisor that restarts a crash-looping API in place is worse here: the
# platform's own restart is the thing that should handle it, and it only can if
# the container actually exits.
set -euo pipefail

log() { printf '[start] %s\n' "$*"; }
die() { printf '[start] FATAL: %s\n' "$*" >&2; exit 1; }

APP_DIR="${APP_DIR:-/app}"
DATA_DIR="${DATA_DIR:-/data}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${PORT:-7860}"          # Spaces sets $PORT; 7860 is its default

export SQLITE_PATH="${SQLITE_PATH:-${DATA_DIR}/rag.db}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/opt/ollama/models}"

# OLLAMA_HOST is host:port here, never a URL — the checks below build
# "http://${OLLAMA_HOST}/api/tags" themselves.
#
# Both spellings are legitimate and people write both: Ollama's own client
# libraries take a full URL, the server takes host:port. So a perfectly
# reasonable OLLAMA_HOST=http://127.0.0.1:11434 in a .env — which is exactly
# what this project's .env carries, for the Python client that wants it —
# produced "http://http://127.0.0.1:11434/api/tags", a URL that can never
# answer, and the container died 60 seconds later saying Ollama was not ready.
# It looked like a broken model server and was a string.
#
# Found on the first real container run, 2026-08-02. Normalise rather than
# document: the scheme is dropped if present, and a trailing slash with it.
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
OLLAMA_HOST="${OLLAMA_HOST#http://}"
OLLAMA_HOST="${OLLAMA_HOST#https://}"
OLLAMA_HOST="${OLLAMA_HOST%/}"
export OLLAMA_HOST

# The Next.js side talks to FastAPI over loopback. This is the variable that,
# when wrong, produces a UI that loads and then fails every request.
export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:${API_PORT}}"

mkdir -p "${DATA_DIR}" || die "cannot write to ${DATA_DIR}"

# ── Fail fast on configuration, before anything starts ────────────────────
#
# `config.py` already refuses placeholder secrets when ENVIRONMENT=production,
# but it does so inside FastAPI's startup, where the message is buried in a
# traceback three processes deep. Checking here makes the first line of the log
# say what is wrong.
if [[ "${ENVIRONMENT:-local}" == "production" ]]; then
    [[ "${SECRET_KEY:-changethis}" == "changethis" ]] && die "SECRET_KEY is unset — set it as a Space secret"
    [[ -z "${IDENTITY_PEPPER:-}" ]] && log "WARNING: IDENTITY_PEPPER is empty; it falls back to SECRET_KEY, so rotating SECRET_KEY will break every published public_id link"
    [[ "${ALLOW_APP_KEY_FALLBACK:-true}" != "false" ]] && log "WARNING: ALLOW_APP_KEY_FALLBACK is not false — every visitor can spend this app's Anthropic balance"
fi

# ── Shut everything down together ─────────────────────────────────────────
pids=()
cleanup() {
    log "stopping"
    for pid in "${pids[@]:-}"; do
        [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_for() {
    # wait_for <name> <url> <seconds>
    local name="$1" url="$2" limit="$3" i=0
    while ! curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; do
        i=$((i + 1))
        if (( i >= limit )); then
            die "${name} did not become ready in ${limit}s"
        fi
        sleep 1
    done
    log "${name} ready after ${i}s"
}

# ── 1. Ollama ─────────────────────────────────────────────────────────────
#
# Embedding runs on the *write* path — every upload and every tutor lesson — so
# this is not optional infrastructure, it is a dependency of the app booting
# usefully.
#
# Whether *this* process starts it is a different question from whether it must
# be running. On the laptop, compose points the container at the model server
# already running on the host — the one with llama3.1:8b in it, so generation is
# local and free — and starting a second one here would try to bind a port the
# host already holds. The container would then look healthy for a second and die.
#
#   MANAGE_OLLAMA=1  start it (what a single-container deploy does)
#   MANAGE_OLLAMA=0  someone else owns it; just wait for it
#   unset            decide from OLLAMA_HOST: loopback means it is ours
#
# Either way the readiness check and the model check below still run. Not
# starting a dependency is never a reason to stop verifying it.
case "${MANAGE_OLLAMA:-auto}" in
    1|true|yes)  manage_ollama=1 ;;
    0|false|no)  manage_ollama=0 ;;
    *)
        case "${OLLAMA_HOST}" in
            127.0.0.1:*|localhost:*|0.0.0.0:*) manage_ollama=1 ;;
            *)                                 manage_ollama=0 ;;
        esac
        ;;
esac

if (( manage_ollama )); then
    log "starting ollama (models: ${OLLAMA_MODELS})"
    ollama serve &
    pids+=($!)
else
    log "using the ollama at ${OLLAMA_HOST} — not starting one here"
fi
wait_for ollama "http://${OLLAMA_HOST}/api/tags" 60

# The model is baked into the base image. If it is missing, something is wrong
# with the image rather than with the network, and pulling 274 MB at boot to
# paper over that would hide the real problem.
if ! ollama list | grep -q "${EMBEDDING_MODEL:-nomic-embed-text}"; then
    if (( manage_ollama )); then
        die "${EMBEDDING_MODEL:-nomic-embed-text} is not in this image — rebuild deploy/ollama-base"
    else
        die "${EMBEDDING_MODEL:-nomic-embed-text} is missing from the ollama at ${OLLAMA_HOST} — run: ollama pull ${EMBEDDING_MODEL:-nomic-embed-text}"
    fi
fi
log "embedding model present"

# ── 2. FastAPI ────────────────────────────────────────────────────────────
log "starting api on :${API_PORT}"
cd "${APP_DIR}"
uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT}" --workers 1 &
pids+=($!)
# One worker, always. SQLite has a single writer, and a second worker in the
# same container is the easy way to corrupt it. See PLAN.md "SQLite in
# deployment".
wait_for api "http://127.0.0.1:${API_PORT}/health" 90

# ── 3. Next.js ────────────────────────────────────────────────────────────
#
# The standalone build. `output: "standalone"` in web/next.config.js traces the
# imports it actually needs, so the runtime has ~19 MB of node_modules instead
# of 360 MB and needs no npm install. The nested web/ in the path is real — the
# turbopack root is the repo root, so the trace keeps that structure.
log "starting web on :${WEB_PORT}"
cd "${APP_DIR}/web"
HOSTNAME=0.0.0.0 PORT="${WEB_PORT}" node server.js &
pids+=($!)

log "up — http://0.0.0.0:${WEB_PORT}"

# ── Die together ──────────────────────────────────────────────────────────
#
# `wait -n` returns as soon as ANY child exits. Without it, bash would sit
# waiting on the others while the container looked healthy and served errors —
# the failure mode where a Space is "running" and nothing works.
#
# The `|| code=$?` is load-bearing, not defensive style. Under `set -e` a bare
# `wait -n` that returns non-zero terminates the script *at that line*, so the
# assignment below it never runs and the log line explaining which process died
# is never printed. Caught by a smoke test, not by reading.
code=0
wait -n || code=$?
log "a process exited (${code}) — shutting the container down"
exit "${code}"
