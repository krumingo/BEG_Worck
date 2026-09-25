"""Compatibility CLI for the W0-03C migration adapter.

Generic state validation and rendering live in control_engine.py. This wrapper
preserves the Phase 2 command and test entry point without coupling the engine
to a particular task or pull request.
"""

from control_engine import ControlError, render_board, validate_board, validate_state
from w0_03c_migration import (ACTIVE_PATH, BOARD_PATH, PR_URL, REVIEW_PATH, STATE_PATH,
                              build_state, canonical_sources, main, validate_sources,
                              verify_remote_queue_sources)


if __name__ == "__main__":
    raise SystemExit(main())
