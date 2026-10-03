# BEG Orchestrator v0.1 — DRAFT

Purpose: let ChatGPT use GitHub as a command bus to wake the local Codex desktop session, while Codex acts only as the local PC executor that controls Claude Desktop.

Target flow:
ChatGPT architect → GitHub Issue command → Windows BEG Bridge (no LLM) → Codex Desktop → Claude Desktop → GitHub result → ChatGPT.

The bridge does not make architectural or business decisions. It only transports a verified command from GitHub to the Codex desktop input.

Safety boundary:
- allowed automatically: focus Codex, paste one bounded prompt, press Enter, write local audit, optionally post ACK;
- never automatic: merge, deploy, production/NAS/Atlas writes, credentials, deletion, locked FLOW/D changes, irreversible actions.

Command format:
BEG_BRIDGE_COMMAND
command_id: CMD-0001
target: CODEX
callback_issue: 22
---
Use the beg-claude-relay skill.
Send Claude Desktop this exact test prompt:
BRIDGE_TEST_1: Отговори само с CHATGPT_TO_CLAUDE_BRIDGE_OK.
Do not modify code, GitHub, files, branches, PRs or settings.
Publish the observed result in Issue #22.

Install:
1. Ensure GitHub CLI gh is installed and authenticated.
2. Copy config.example.json to C:\BEG\beg-orchestrator\config.json.
3. Keep dry_run=true for the first test.
4. Run bridge.ps1 with that config.
5. Only after dry-run proves the right command is selected, switch dry_run=false.

Important limitation: v0.1 wakes/focuses Codex Desktop through Windows UI automation. It is not a native inbound Codex webhook. If window focus cannot be proven, it must stop rather than type into an unknown window.
