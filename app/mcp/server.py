"""The MCP server: registration and description text, nothing else.

Every behaviour lives in `app/mcp/tools.py`. What this module contributes is
the part MCP actually adds — a machine-readable catalogue of what the app can
do, with descriptions written *for a model to read*, not for a developer.

Those descriptions are prompt text. They are the only thing standing between a
model and calling `get_document` in a loop, so they say what each tool costs
and when to prefer another one. Treat edits here as prompt changes.

The server is built once at import. It holds no per-user state — the caller is
carried in a context variable (`app/mcp/context.py`), so one server instance
serves every user without any of them being able to name another.
"""

from mcp.server.fastmcp import FastMCP

from app.mcp import tools

INSTRUCTIONS = """\
Tools over one learner's private study material: documents they uploaded, and
lessons an AI tutor taught them, which were saved and indexed.

Everything is already scoped to the signed-in learner. There is no way to
address another user's material and no parameter that would let you try.

Two tools search, and the choice between them is the choice of *what you are
asking about*:

  search_documents  everything the learner owns — lessons and uploaded files
                    alike. The cheap, general answer to "what material is there
                    about X".
  recall_lessons    only what the tutor taught them. Use it when the question
                    is about the person rather than the material: what do they
                    know, what have they covered. It is the only one that can
                    tell you a topic was never taught.

Both search meaning rather than words, so either finds a lesson on embeddings
when asked about vector representations.\
"""


def build_server() -> FastMCP:
    server: FastMCP = FastMCP(
        name="mcp-py",
        instructions=INSTRUCTIONS,
    )

    server.add_tool(
        tools.search_documents,
        title="Search the learner's material",
        description=(
            "Semantic search across everything this learner owns — uploaded "
            "documents and saved tutor lessons. Matches on meaning, not "
            "keywords. Returns the closest passages with a similarity score "
            "(1.0 is identical) and the title of the document each came from, "
            "so you can cite them.\n\n"
            "Prefer this over reading documents whole. Note that results are "
            "always the nearest matches available, so a low score means the "
            "learner probably has not covered the topic — say so rather than "
            "answering from your own knowledge.\n\n"
            "top_k defaults to 5 and is capped at 20."
        ),
    )

    server.add_tool(
        tools.list_documents,
        title="List the learner's documents",
        description=(
            "Every document this learner owns, newest first, each marked "
            "'lesson' (taught by the tutor and saved) or 'upload' (a file they "
            "added). Use it to see what material exists before searching, or "
            "to get a document_id for get_document.\n\n"
            "Returns metadata only, never content."
        ),
    )

    server.add_tool(
        tools.get_document,
        title="Read one document",
        description=(
            "The full indexed text of one document, as the list of chunks it "
            "was split into. Requires a document_id from list_documents or "
            "from a search_documents match.\n\n"
            "This is the expensive tool — a document can be long, and the "
            "reply is truncated when it is. Use search_documents unless you "
            "specifically need the whole thing."
        ),
    )

    server.add_tool(
        tools.recall_lessons,
        title="Ask the learner's own model",
        description=(
            "What this learner has been *taught* about something — their own "
            "lessons only, never their uploaded files. Use it when the "
            "question is about the person rather than about a document: what "
            "do they know, what have they covered, what would they say.\n\n"
            "The difference from search_documents matters. This tool can tell "
            "you the learner has never been taught a topic, and that answer is "
            "reliable, because it searched everything they were taught and "
            "nothing else. A weak result from search_documents cannot support "
            "the same claim — the material might simply have been in a file "
            "they uploaded rather than a lesson.\n\n"
            "Returns passages with a similarity score (1.0 is identical) and "
            "the topic each lesson was filed under. It does not write an "
            "answer; that is your job, from these passages."
        ),
    )

    server.add_tool(
        tools.tutor_stats,
        title="Summarise the learner's model",
        description=(
            "How much this learner's model holds: number of lessons, the list "
            "of topics covered, the number of indexed chunks, and which "
            "embedding model indexed them.\n\n"
            "Use it to answer questions about progress, or to name what the "
            "learner *has* covered when a search comes back weak."
        ),
    )

    return server


server: FastMCP = build_server()
