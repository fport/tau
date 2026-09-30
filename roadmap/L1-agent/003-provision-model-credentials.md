# 003 · Provision model credentials with cost guards

Status: ready-for-human
Type: HITL
Layer: L1 · Agent
Packages: -
Blocked by: none

## What to build

Create the accounts and credentials the agent needs, with spend alarms in place before the first real model call.

Scope changed on 2026-09-30: Bedrock was dropped and Anthropic is the only cloud provider ([ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md)), so the AWS criteria below no longer apply. The hard per-role budgets of the LiteLLM proxy (010, 011) take the place of the AWS Budgets alarms.

## Acceptance criteria

- ~~AWS account with a dedicated least-privilege identity for tau (Bedrock invoke only)~~ dropped (ADR 0009)
- ~~Bedrock model access granted for Claude Sonnet and Claude Haiku in the chosen region~~ dropped (ADR 0009)
- ~~AWS Budgets alarms (e.g. $5 and $15 per month) email the user~~ dropped (ADR 0009); the proxy's per-role budgets replace them
- [x] Anthropic API key created (now the only provider)
- [ ] A monthly spend limit is set on the Anthropic workspace in the Console (the last line of defence behind the proxy budgets)
- [x] Credentials live only in the local `.env`; variable names match `.env.example`
- ~~No Bedrock Knowledge Base / OpenSearch Serverless resources were created (idle cost trap)~~ nothing was created on AWS

## Blocked by

None - can start immediately

## Comments

- 2026-09-30: rescoped by [ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md). The owner dropped Bedrock, so nothing is created on AWS. The Anthropic key is in `.env` and serves every role through the LiteLLM proxy (010), which also holds the hard budgets that replace the AWS Budgets alarms (011). One thing left for the owner: set a monthly spend limit on the Anthropic workspace in the Console, then close this issue.
