"""Schema check for CONTROL_STATE.json.

This is an adaptation of the subset of JSON Schema that
``tools/control_engine.py:_check_schema`` implements -- the producer's own checker --
with two deliberate differences:

1. The schema is supplied by the caller rather than read from a path on disk. The
   dashboard fetches ``CONTROL_STATE.schema.json`` from the same branch and the same
   round as the state, so the state is checked against the schema it was actually
   published beside, not against whatever happens to sit in the container image.
2. Every violation is collected instead of raising on the first one, so an operator
   sees the whole picture in one refresh.

``tests/test_canonical_engine.py`` asserts that this module and the canonical engine
reach the same verdict on the real published snapshot and on mutated copies of it, so
the adaptation cannot silently drift from the producer.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urlparse

from .status import Finding, Status, Verdict

_TYPE_TESTS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    # `type(x) is int` on purpose: in Python a bool is an int, and a schema that
    # says "integer" must not accept True.
    "integer": lambda value: type(value) is int,
    "boolean": lambda value: type(value) is bool,
    "null": lambda value: value is None,
}


def validate(state: object, schema: dict) -> Verdict:
    """Check ``state`` against ``schema``, collecting every violation."""
    if not isinstance(schema, dict):
        return Verdict([Finding(Status.INVALID, "SCHEMA_UNUSABLE", "Schema is not a JSON object.")])
    findings: list[Finding] = []
    _check(state, schema, schema, "$state", findings, depth=0)
    return Verdict(findings)


def matches(value: object, rule: dict, root: dict) -> bool:
    """Whether ``value`` satisfies ``rule`` with no violations at all."""
    probe: list[Finding] = []
    _check(value, rule, root, "$probe", probe, depth=0)
    return not probe


def _fail(findings: list[Finding], location: str, message: str) -> None:
    findings.append(Finding(Status.INVALID, "SCHEMA_VIOLATION", f"{location}: {message}"))


def _check(
    value: object,
    rule: dict,
    root: dict,
    location: str,
    findings: list[Finding],
    depth: int,
) -> None:
    if depth > 64:  # Guards a malformed schema with a $ref cycle.
        _fail(findings, location, "schema nesting is too deep to check")
        return
    if not isinstance(rule, dict):
        return

    if "$ref" in rule:
        name = str(rule["$ref"]).removeprefix("#/$defs/")
        target = (root.get("$defs") or {}).get(name)
        if not isinstance(target, dict):
            _fail(findings, location, f"schema $ref {name!r} is not defined")
            return
        _check(value, target, root, location, findings, depth + 1)
        return

    if "anyOf" in rule:
        branches = rule["anyOf"] if isinstance(rule["anyOf"], list) else []
        if not any(matches(value, branch, root) for branch in branches):
            _fail(findings, location, "no anyOf branch matches")
        return

    if "const" in rule and value != rule["const"]:
        _fail(findings, location, f"expected {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        _fail(findings, location, f"invalid enum value {value!r}")

    kinds = rule.get("type")
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else list(kinds)
        if not any(_TYPE_TESTS[kind](value) for kind in kinds if kind in _TYPE_TESTS):
            _fail(findings, location, "wrong type")
            # Descending into a wrong-typed value would only produce noise.
            return

    if isinstance(value, dict):
        _check_object(value, rule, root, location, findings, depth)
    if isinstance(value, list):
        _check_array(value, rule, root, location, findings, depth)
    if isinstance(value, str):
        _check_string(value, rule, location, findings)
    if type(value) is int:
        if value < rule.get("minimum", -float("inf")) or value > rule.get("maximum", float("inf")):
            _fail(findings, location, "number outside range")


def _check_object(
    value: dict, rule: dict, root: dict, location: str, findings: list[Finding], depth: int
) -> None:
    missing = set(rule.get("required", [])) - set(value)
    if missing:
        _fail(findings, location, f"missing {sorted(missing)}")
    properties = rule.get("properties") or {}
    if rule.get("additionalProperties") is False:
        unknown = set(value) - set(properties)
        if unknown:
            _fail(findings, location, f"unknown fields {sorted(unknown)}")
    for key, child in value.items():
        if key in properties:
            _check(child, properties[key], root, f"{location}.{key}", findings, depth + 1)


def _check_array(
    value: list, rule: dict, root: dict, location: str, findings: list[Finding], depth: int
) -> None:
    if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", float("inf")):
        _fail(findings, location, "wrong item count")
    if rule.get("uniqueItems"):
        try:
            encoded = {json.dumps(item, sort_keys=True) for item in value}
        except TypeError:  # pragma: no cover - JSON input is always encodable
            encoded = set()
        if len(encoded) != len(value):
            _fail(findings, location, "duplicate items")
    items = rule.get("items") or {}
    for index, child in enumerate(value):
        _check(child, items, root, f"{location}[{index}]", findings, depth + 1)


def _check_string(value: str, rule: dict, location: str, findings: list[Finding]) -> None:
    pattern = rule.get("pattern")
    if pattern and not re.search(pattern, value):
        _fail(findings, location, "pattern mismatch")
    if len(value) < rule.get("minLength", 0):
        _fail(findings, location, "string too short")
    if len(value) > rule.get("maxLength", float("inf")):
        _fail(findings, location, "string too long")
    fmt = rule.get("format")
    if fmt == "date-time" and parse_timestamp(value) is None:
        _fail(findings, location, "invalid date-time")
    if fmt == "uri" and value and not urlparse(value).scheme:
        _fail(findings, location, "invalid URI")


def parse_timestamp(value: object) -> dt.datetime | None:
    """Parse an RFC 3339 timestamp, requiring an explicit offset. ``None`` if unusable.

    A timestamp without an offset is rejected rather than assumed to be UTC: guessing
    a zone would silently move an event by hours and the protocol forbids guessing.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
