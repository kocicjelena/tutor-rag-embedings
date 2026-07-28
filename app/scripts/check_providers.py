"""Diagnose provider setup.

    uv run python -m app.scripts.check_providers

Checks each provider independently and reports what to do about failures, so
setup problems surface here rather than as a 503 mid-demo.
"""

import asyncio
import sys

from app.core.config import settings
from app.services.providers import (
    ProviderUnavailableError,
    describe_providers,
    get_chat_provider,
    get_embedding_provider,
)

OK = "  ok  "
FAIL = " FAIL "
SKIP = " skip "


async def check_embeddings() -> bool:
    embedder = get_embedding_provider()
    print(f"\nEmbeddings — {embedder.name} / {embedder.model}")
    try:
        await embedder.health()
        vectors = await embedder.embed(["hello world", "second text"])
    except ProviderUnavailableError as exc:
        print(f"[{FAIL}] {exc.detail}")
        return False
    dims = {len(v) for v in vectors}
    print(f"[{OK}] embedded 2 texts, dimensions={dims.pop()}, batched in one call")
    return True


async def check_chat(name: str) -> bool:
    print(f"\nChat — {name}")
    try:
        provider = get_chat_provider(name)
    except ProviderUnavailableError as exc:
        print(f"[{SKIP}] {exc.detail}")
        return True  # not configured is not a failure

    try:
        models = await provider.list_models()
    except ProviderUnavailableError as exc:
        print(f"[{FAIL}] {exc.detail}")
        return False

    print(f"[{OK}] {len(models)} model(s); default={provider.default_model}")
    for m in models[:5]:
        print(f"         - {m.name}")
    if len(models) > 5:
        print(f"         ... and {len(models) - 5} more")

    if provider.default_model not in {m.name for m in models} and name == "ollama":
        print(
            f"[{FAIL}] default model {provider.default_model!r} is not installed. "
            f"Run:  ollama pull {provider.default_model}"
        )
        return False

    try:
        chunks: list[str] = []
        async for fragment in provider.stream(
            system="You are terse. Reply with exactly one word.",
            user="Say the word: ready",
        ):
            chunks.append(fragment)
    except ProviderUnavailableError as exc:
        print(f"[{FAIL}] streaming failed: {exc.detail}")
        return False
    print(f"[{OK}] streamed {len(chunks)} fragment(s): {''.join(chunks)[:60]!r}")
    return True


async def main() -> int:
    print(f"Ollama host      : {settings.OLLAMA_HOST}")
    print(f"Default provider : {settings.DEFAULT_CHAT_PROVIDER}")
    print(f"Claude API key   : {'set' if settings.claude_available else 'not set'}")

    results = [await check_embeddings()]
    for name in ("ollama", "claude"):
        results.append(await check_chat(name))

    print("\nProvider inventory as the frontend sees it:")
    inventory = await describe_providers()
    for info in inventory.data:
        mark = OK if info.available else SKIP
        print(f"[{mark}] {info.name}: {len(info.models)} models"
              + (f" — {info.detail}" if info.detail else ""))

    if all(results):
        print("\nAll configured providers are working.")
        return 0
    print("\nSome checks failed — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
