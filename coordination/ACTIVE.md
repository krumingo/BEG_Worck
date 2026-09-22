# BEG_Work Claude assignment queue

Status: IDLE
Task-ID: NONE
Base-branch: main
Base-SHA: NONE

This branch is a coordination mailbox, not a runtime branch. Only an explicit assignment with Status: READY and a unique Task-ID authorizes one bounded implementation run. Never infer work from old PRs, suggestions, or this IDLE template.

For a READY assignment include: human purpose, FLOW and D-decision references, prerequisites, exact scope and exclusions, acceptance tests, evidence required, and stop conditions. The assigned agent must read CLAUDE.md and the relevant canonical files. One implementation task at a time. Deliver a Draft PR and HANDOFF with exact SHA, then stop. No merge, deploy, production/NAS/Atlas writes, migration, secrets, or changes to business-locked FLOWs without Krum's separate explicit decision.

Codex reviews actual diff and evidence independently. Krum decides business changes and merge/deploy.
