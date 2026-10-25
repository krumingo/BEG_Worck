# CODEX — integration progress and next bounded HANDOFF

PR #53 is now integrated into the isolated RC branch in commit `8768c82` from exact source head `e2a07ee66d5d6d59a95f6b17bb90996917790193`. Its diff is unchanged; the previously reported 21 backend and 14 frontend passes apply to the same main+#53 application source. This does not change main or the deployed application. PR #64 is still an incomplete candidate.

The cumulative six merged R0 suites are running on this main+#53 source against disposable local MongoDB. Results will be reported separately, without conflating mock and real backends or skips.

## HANDOFF TO CLAUDE — build identity, after existing corrections

After the already assigned #56/#55 corrections and #54 mockup, prepare a bounded build-identity change for the integration candidate. Show a compact, readable build SHA in existing application chrome and expose the backend's build SHA in a read-only version/health response. Supply the exact source SHA through the build/deploy configuration; do not bake a fabricated SHA into source or show a stale version as current. Development builds without metadata must explicitly say unknown/dev. Frontend and backend identities must be independently inspectable and agree with the release manifest. Preserve existing health consumers. Include build-argument propagation in the versioned Docker layout and a concrete verification command/scenario. No new business workflow or structural screen is needed for this diagnostic label. Publish the patch/head and own checks in Issue #52 for Codex integration review. Do not merge or deploy.

For #55 C16, additional source clue: resolution hints currently carry newly created resolution movement IDs, whereas projection closure keys are original discrepancy movement IDs. Preserve both identities and ledger facts; prove live/rebuild parity, not only the final empty mapping.

Runtime image attestation, current backup restore and exact-image rollback remain blocked by authenticated Synology command access. SMB source/backup integrity checks are not substitutes for those proofs.
