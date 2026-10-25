# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Screenshots and an animated walkthrough of the live demo in the README.
- CodeQL code scanning workflow (Python, JavaScript/TypeScript and Actions) and Dependabot updates for pip, npm (`ui/`), Docker and GitHub Actions.
- Roadmap tracked as GitHub issues under the v0.2.0 milestone.
- This changelog.

### Changed

- Demo seed data and eval expectations use a neutral courier name (Swift Courier, `SC-` tracking codes) ([#1](https://github.com/AkibUllah/ai-support-agent/pull/1)).
- CI workflow runs with a read-only `GITHUB_TOKEN` by default.

## [0.1.0] - 2026-10-25

First public release.

### Added

- Tool-calling agent loop with a provider-neutral message format and eight JSON-schema tools (order lookup, tracking, recent orders, refunds, address changes, tickets, FAQ search, human handoff).
- Offline scripted policy model (default), Anthropic Messages and OpenAI-compatible adapters over httpx.
- Authorisation from the session: tools read the customer from the authenticated session and cross-customer attempts are audited.
- Policy engine for refunds (7-day window, ৳5,000 auto-approve limit, escalation with a ticket) and address changes (before dispatch only).
- Guardrails: prompt-injection heuristics on user text (English and Bangla) and tool output, strict argument validation, step and tool budgets, PII redaction in logs.
- Human handoff state that freezes the session until staff take over.
- Per-turn traces of tool calls, results, durations and guardrail events.
- `agent-eval` with 53 scripted scenarios checking tools, guardrails, replies and database state, plus guardrail ablation runs.
- React + Vite chat UI with a tool-call timeline and a replay mode for GitHub Pages.
- 78 pytest tests and 10 UI tests, CI matrix, multi-stage Dockerfile and docker compose.
- Live demo kit: GitHub Pages replay site with API reference, Codespaces dev container and Render blueprint.

[Unreleased]: https://github.com/AkibUllah/ai-support-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AkibUllah/ai-support-agent/releases/tag/v0.1.0
