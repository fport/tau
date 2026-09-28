# 028 · tau as an MCP server for Claude Code

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-core
Blocked by: 020, 021

## What to build

tau exposes an MCP server (stdio locally, streamable HTTP on the tailnet) so Claude Code and Claude Desktop can use memory (remember/recall), KB search, the routine list, and ask tau a question. Tier rules apply to calls that arrive over MCP.

## Acceptance criteria

- [ ] `claude mcp add` instructions work and the tools show up in Claude Code
- [ ] Memory and KB tools return the same results as in `tau chat`
- [ ] Tier-2 tools called over MCP require approval through the configured channel
- [ ] Reachable only from localhost and the tailnet, with authentication

## Blocked by

- [020 · Memory with Vectorize and a Self-RAG loop](../L3-cloud/020-memory-self-rag.md)
- [021 · Knowledge base: markdown → R2 → AI Search with `kb_search`](../L3-cloud/021-knowledge-base-ai-search.md)

## Comments
