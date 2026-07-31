---
title: mcp-py — LLM, RAG and MCP
emoji: 📚
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: A learning tutor whose lessons become a searchable model you can export.
---

# mcp-py

A small app built to show three things working together: **LLM, RAG and MCP.**

Ask the tutor to explain something and it teaches you. Every exchange is
indexed. Over time that becomes **your model** — a corpus of what you have been
taught, which the app can answer from and which you can export and download.
You can also upload your own documents and ask questions about them, with
citations back to the passages the answer came from.

Tick *let the model use tools* and Claude decides which searches to run over
your material, over a real **MCP** server and client running inside the app.
Every tool call appears in the panel as it happens.

## Two things to know before you try it

**Bring your own Anthropic key.** Generation here is Claude, and this Space
holds no key of its own — so paste yours into *Claude access* and your usage is
billed to your account. The app stores only a one-way hash and the last four
characters, neither of which can call Anthropic; the working key stays in your
browser session and is dropped when you close it. That is also why you have to
add it again next time.

**Documents you add here are temporary.** This Space runs on an ephemeral disk,
so uploads and lessons are lost when it restarts. That is deliberate rather
than broken — the point being demonstrated is the pipeline, not storage. If you
build something you want to keep, **export your model**: it downloads as a JSON
file you can import again later, here or on your own copy.

## Running it yourself

Everything works better locally, where Ollama can do the generation too and
nothing is temporary. The source and its documentation live at
[kocicjelena/tutor-rag-embedings](https://github.com/kocicjelena/tutor-rag-embedings)
— currently private while the work is in progress.

---

*A personal learning project, built in the open. It runs and it is tested, but
it is not finished and not production software — the repository says plainly
what does not work yet.*
