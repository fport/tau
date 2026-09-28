# 034 · Hot-reloaded tools and `_pending` approval for tau-written tools

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: tau-core
Blocked by: 006

## What to build

Python tool files in the tools directory are hot-reloaded: add, edit and delete without a restart. tau can write a new tool, but it lands in `tools/_pending/` and activates only after a tier-2 approval that shows the full source. Rejected tools are archived.

## Acceptance criteria

- [ ] Dropping in a file makes the tool available on the next turn; editing changes behavior; deleting removes it
- [ ] A tau-written tool never executes before approval (test)
- [ ] The approval request shows the full source
- [ ] A tool with syntax or import errors does not crash the hub; the error is reported

## Blocked by

- [006 · Tool permission tiers with approval and a loop guard](../L1-agent/006-tool-permission-tiers.md)

## Comments
