#!/usr/bin/env python3
"""CI-01 — compare a JUnit report against the committed list of known failures.

Exit 1 when a test fails (or errors) that is not in the known list. Known
failures that now pass are printed, so the list can be shortened; they do not
fail the gate. The list is a ratchet: it may only shrink, never grow, without
an explicit decision recorded in docs/ops/DECISIONS.md.

usage: compare_failures.py <junit.xml> <known_failures.txt>
"""
import sys
import xml.etree.ElementTree as ET


def failed_ids(path):
    out = set()
    for case in ET.parse(path).getroot().iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            out.add(f"{case.get('classname')}::{case.get('name')}")
    return out


def known_ids(path):
    with open(path, encoding="utf-8") as fh:
        return {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}


def main(argv):
    report, known_path = argv
    failed, known = failed_ids(report), known_ids(known_path)
    new = sorted(failed - known)
    fixed = sorted(known - failed)
    print(f"failed={len(failed)} known={len(known)} new={len(new)} now_passing={len(fixed)}")
    for t in fixed:
        print(f"NOW PASSING (remove from known list): {t}")
    for t in new:
        print(f"NEW FAILURE: {t}")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
