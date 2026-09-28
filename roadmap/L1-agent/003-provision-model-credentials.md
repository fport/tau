# 003 · Provision model credentials with cost guards

Status: ready-for-human
Type: HITL
Layer: L1 · Agent
Packages: -
Blocked by: none

## What to build

Create the accounts and credentials the agent needs, with spend alarms in place before the first real model call.

## Acceptance criteria

- [ ] AWS account with a dedicated least-privilege identity for tau (Bedrock invoke only)
- [ ] Bedrock model access granted for Claude Sonnet and Claude Haiku in the chosen region
- [ ] AWS Budgets alarms (e.g. $5 and $15 per month) email the user
- [ ] Anthropic API key created with a monthly spend limit (fallback provider)
- [ ] Credentials live only in the local `.env`; variable names match `.env.example`
- [ ] No Bedrock Knowledge Base / OpenSearch Serverless resources were created (idle cost trap)

## Blocked by

None - can start immediately

## Comments
