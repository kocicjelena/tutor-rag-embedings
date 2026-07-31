#!/usr/bin/env sh
# Prove the image contains a working embedder.
#
#     docker run --rm ghcr.io/<owner>/mcp-py-ollama:nomic-embed-text verify
#
# Run this after every build. A base image that pulls but cannot embed fails
# much later and much less clearly — as an upload stuck at "processing".
set -eu

MODEL="${EMBED_MODEL:-nomic-embed-text}"
EXPECT_DIMS="${EXPECT_DIMS:-768}"

echo "→ starting ollama"
ollama serve >/tmp/ollama.log 2>&1 &
pid=$!
# shellcheck disable=SC2064
trap "kill $pid 2>/dev/null || true" EXIT

i=0
while ! ollama list >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "✗ ollama did not start in 30s" >&2
        cat /tmp/ollama.log >&2
        exit 1
    fi
    sleep 1
done
echo "✓ ollama up"

echo "→ models present:"
ollama list

# The real check: embed something and count the dimensions. `ollama list`
# only proves a file exists; this proves it loads and produces the width the
# vec0 index was created with.
echo "→ embedding a test string"
dims=$(
  curl -fsS http://127.0.0.1:11434/api/embed \
    -d "{\"model\":\"${MODEL}\",\"input\":\"hello world\"}" \
  | tr ',' '\n' | grep -c '[0-9]'
) || { echo "✗ embed call failed" >&2; exit 1; }

if [ "$dims" -lt "$EXPECT_DIMS" ]; then
    echo "✗ got ~$dims values, expected $EXPECT_DIMS — wrong model?" >&2
    exit 1
fi

echo "✓ ${MODEL} embeds, ~${dims} dimensions"
echo "✓ image is good"
