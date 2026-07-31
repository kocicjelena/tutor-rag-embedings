"""The MCP layer: tools, server, in-process client.

    app/mcp/context.py   who the tool acts for — set by the route, never by the model
    app/mcp/tools.py     the tool bodies, plain async functions, no MCP imports
    app/mcp/server.py    FastMCP, registering those functions
    app/mcp/client.py    an MCP client that talks to that server over a real session

The split matters. `tools.py` knows nothing about MCP, so the tools are testable
as ordinary functions and can be reached by a second transport later without
being rewritten. `server.py` is only registration and description text.

See `.claude/rules/MCP.md` for the design, and `.claude/rules/TODO.md` Milestone 3 for what is
still missing (tool-calling in the providers, which is what finally lights up
the tool-trace panel in the UI).
"""
