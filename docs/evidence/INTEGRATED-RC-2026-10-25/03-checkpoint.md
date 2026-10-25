# CODEX integration checkpoint — baseline, #53 and PC HANDOFF

## Published review packet

Draft PR #64: https://github.com/krumingo/BEG_Worck/pull/64

Evidence commit: `8a721a87a51ccdcbaa94ac1bb7ca56c40a26084d` (documentation/evidence only, not an app RC).

The scope matrix contains **153 traceable rows**: 59 Claude defect IDs, 15 Codex defect IDs, 29 missing/partial capability rows and 50 FLOW rows. Counts overlap by design and are NOT 153 distinct defects. It separates audited findings, fix/PR, verification, deployment and remaining work. Existing structural UI gaps retain the mockup/owner gate.

## Fresh Synology verification

- Source marker: `0b53bcd5b977ee27de8d4cee363fed41dd897482`.
- Git-object comparison: **1043/1043 source files byte-identical**, 0 missing, 0 different, 0 CRLF-only.
- Served JS: 3127898 bytes; SHA256 `0b2ff7788a62da4cfa2847277ee6a14e7af312694462fcc5c8e0b2cc0042fbf9`.
- Current main is **63 commits / 216 changed backend+frontend files** ahead.
- Current container image IDs remain unverified: source identity does not independently prove the running backend image.
- Today's backup: 800989 bytes; SHA256 `4153a69657c97a38a3063fa5666b1a7d61ca06154b214a530a520392ec68d598`; gzip CRC/decompression PASS, 2727448 uncompressed bytes. **Restore NOT RUN** in this cycle.

## #53 reconciled with current main

Applied the exact PR #53 diff (`e2a07ee66d5d6d59a95f6b17bb90996917790193`) onto an isolated source snapshot of main `c0e34e1f3037010311d352683d519c3c9d7dcbfa`; clean patch, no file overlap with intervening main changes.

- Real-Mongo `tests/test_live_ops_a_read_only.py --noconftest -q -p no:cacheprovider`: **21 passed / 0 failed / 0 skipped**, exit 0.
- Frontend `craco test --watchAll=false --runInBand --testPathPattern=LiveOpsControlCenterPage --no-cache`: **14 passed / 0 failed**, exit 0.
- Covers read-only no-write checks, colliding tenant IDs, stale/incomplete data, explicit errors, canonical-vs-legacy audit presentation and accepted-vs-pending custody.
- This is component compatibility with main, NOT a complete cumulative app/role/owner acceptance. Global coarse role navigation remains tracked.

## HANDOFF_SENT_TO_CLAUDE — PC delivery confirmed

Target: `https://claude.ai/chat/3d5713f4-54ad-4070-9e68-59363083016b` (Интеграция BEG_Work за Synology).

Two distinct messages sent once each: initial coordination and then the final independent findings from https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6395188427 . The second message supersedes initial priority: **#56 RC-AUTH-01/02 first, #55 C16 next, #54 mockup after**. Desktop screenshot confirmed the full message and Claude's acknowledgment: prioritizing #56 and #55 and reading the details. No inference from typing alone.

Additional source clue for C16: `service.py` appends the NEW `resolution_mv_id` to `resolved_discrepancy_mv_ids`, passes those via projection hints, while `_close_unresolved_discrepancies` unsets keys indexed by the ORIGINAL discrepancy movement IDs. Correct the identity contract while retaining resolution facts and rebuild parity; do not weaken assertions.

ГОТОВО: exact-head independent failure verdicts; #53+main 21 backend and 14 frontend passes; source/bundle identity; backup integrity; scope matrix and review packet; PC handoff delivered.
ОСТАВА: Claude corrections and independent re-review; #54 owner UX/access corrections; cumulative RC build SHA, isolated runtime workflows, current backup restore and exact-image rollback proof.
НА РЕД Е: CLAUDE bounded fixes; CODEX integration and re-review.
БЛОКЕР: reproduced AUTH/warehouse defects; authenticated Docker/SSH access for image identity and operational restore/rollback; owner acceptance of required structural mockups.

Existing production address remains http://192.168.1.112:8080/ . It is **not** the new RC. No usable integrated RC address or deploy-ready package is yet claimed. No merge, production write or deployment performed.
