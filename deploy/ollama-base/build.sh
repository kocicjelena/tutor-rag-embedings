#!/usr/bin/env bash
# Build and (optionally) push the Ollama base image.
#
#     ./deploy/ollama-base/build.sh                 # build and verify locally
#     ./deploy/ollama-base/build.sh --push          # ...then push to GHCR
#
# You do not need this to deploy: the GitHub workflow beside it does the same
# thing on GitHub's runners, which matters because there is no Docker on this
# machine yet and the build downloads well over a gigabyte. Keep the script for
# when you want to build on the laptop in docs/LAPTOP8.md.
set -euo pipefail

OWNER="${OWNER:-kocicjelena}"
IMAGE="${IMAGE:-ghcr.io/${OWNER}/mcp-py-ollama}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
OLLAMA_VERSION="${OLLAMA_VERSION:-v0.32.5}"
TAG="${TAG:-${EMBED_MODEL}}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v docker >/dev/null || {
    echo "docker is not installed. See docs/LAPTOP8.md step 2, or use the" >&2
    echo "GitHub workflow instead — it needs nothing on this machine." >&2
    exit 1
}

echo "==> building ${IMAGE}:${TAG}"
docker build \
    --build-arg "OLLAMA_VERSION=${OLLAMA_VERSION}" \
    --build-arg "EMBED_MODEL=${EMBED_MODEL}" \
    -t "${IMAGE}:${TAG}" \
    -t "${IMAGE}:${TAG}-${OLLAMA_VERSION}" \
    "${here}"

echo
echo "==> final size"
docker image inspect "${IMAGE}:${TAG}" --format '{{.Size}}' \
  | awk '{printf "    %.0f MB\n", $1/1024/1024}'

# Never push an image that has not proved it can embed.
echo
echo "==> verifying"
docker run --rm -e "EMBED_MODEL=${EMBED_MODEL}" "${IMAGE}:${TAG}" verify

if [[ "${1:-}" == "--push" ]]; then
    echo
    echo "==> pushing"
    echo "    (log in first: echo \$GITHUB_TOKEN | docker login ghcr.io -u ${OWNER} --password-stdin)"
    docker push "${IMAGE}:${TAG}"
    docker push "${IMAGE}:${TAG}-${OLLAMA_VERSION}"
fi

echo
echo "Use it with:  FROM ${IMAGE}:${TAG}"
