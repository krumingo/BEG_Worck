#!/usr/bin/env python3
"""Read-only snapshot check. Heuristic secret scan is NOT a security guarantee."""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

ALLOW_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "mongo-credential": re.compile(r"mongodb(?:\+srv)?://[^\s/@:]+:[^\s/@]+@"),
}


def inspect_snapshot(parent, sha):
    parent = Path(parent).resolve()
    code = parent / "code"
    errors = []
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Full commit SHA is required")
    if (parent / "COMMIT").read_text().strip() != sha:
        raise ValueError("Exported COMMIT does not match requested SHA")
    archive = parent / "snapshot.tar"
    got_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    receipt = (parent / "snapshot.sha256").read_text().split()[0]
    if receipt != got_hash:
        raise ValueError("Snapshot archive checksum mismatch")
    expected = {}
    with tarfile.open(archive) as tf:
        for member in tf:
            p = PurePosixPath(member.name)
            if p.is_absolute() or ".." in p.parts or not member.isdir() and not member.isfile():
                errors.append("unsafe archive member: " + member.name)
                continue
            if member.isfile():
                expected[member.name] = hashlib.sha256(tf.extractfile(member).read()).hexdigest()
    actual = {}
    for p in sorted(code.rglob("*")):
        rel = p.relative_to(code).as_posix()
        if p.is_symlink():
            errors.append("symlink not allowed: " + rel)
            continue
        if not p.is_file():
            continue
        raw = p.read_bytes()
        actual[rel] = hashlib.sha256(raw).hexdigest()
        name = p.name.lower()
        if ((name == ".env" or name.startswith(".env.")) and name not in ALLOW_ENV_EXAMPLES) or name.endswith((".pem", ".p12", ".pfx", ".key")):
            errors.append("secret-like file name: " + rel)
        if b"\0" not in raw:
            text = raw.decode("utf-8", "replace")
            for label, pattern in PATTERNS.items():
                if pattern.search(text):
                    errors.append("possible " + label + " in " + rel)  # never echo values
    if expected != actual:
        errors.append("Extracted code differs from archive (missing/extra/modified files)")
    return {"commit": sha, "archive_sha256": got_hash, "files": len(actual),
            "heuristic_scan": "FAIL" if errors else "PASS", "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent")
    parser.add_argument("sha")
    args = parser.parse_args()
    try:
        result = inspect_snapshot(args.parent, args.sha)
    except Exception as exc:
        result = {"errors": [str(exc)]}
    print(json.dumps(result, indent=2))
    raise SystemExit(2 if result["errors"] else 0)
