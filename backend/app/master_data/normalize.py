"""
W0-03C (minimal) — safe technical normalization.

Only Q7a from the contract: deterministic, reversible-in-meaning transforms
that no human has to approve. Unicode form, whitespace, case folding, noise
punctuation and the Bulgarian legal-form suffixes.

**Not here, deliberately:** transliteration between Cyrillic and Latin, fuzzy
matching and similarity thresholds. That is Q7b — a business policy Krum has
not decided — and the contract is explicit that no threshold justifies an
automatic merge.

The version is stored on every record that was normalized, so a future change
to these rules can be applied deliberately instead of silently changing what
"the same name" means.
"""
import re
import unicodedata
from typing import Optional

NORMALIZATION_VERSION = "1"

#: Bulgarian legal forms. Written with and without dots in the wild
#: ("ЕООД", "Е.О.О.Д.", "е о о д"), all of which mean the same company form.
LEGAL_SUFFIXES = ("еоод", "оод", "еад", "ад", "дззд", "сд", "ет", "ад-сд")

_ZERO_WIDTH = re.compile(r"[​-‏‪-‮﻿]")
_NOISE_PUNCT = re.compile(r"[\.\,\"'«»„“”`´;:]")
_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Zа-яА-Я]")

# "е о о д" -> "еоод" for the spaced/dotted spellings of the legal forms
_SPACED_SUFFIX = re.compile(r"\b(?:" + "|".join(
    r"\s*".join(list(s)) for s in ("еоод", "оод", "еад", "дззд")) + r")\b")


def normalize_name(value: Optional[str]) -> str:
    """Normalize a display name for comparison.

    Deterministic and idempotent: ``normalize_name(normalize_name(x)) == normalize_name(x)``.
    """
    if not value:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = s.replace(" ", " ")
    s = _ZERO_WIDTH.sub("", s)
    s = s.casefold()
    s = _NOISE_PUNCT.sub("", s)
    s = _WHITESPACE.sub(" ", s).strip()
    s = _collapse_legal_suffix(s)
    return s


def _collapse_legal_suffix(s: str) -> str:
    """"фирма е о о д" -> "фирма еоод". Only the known forms, nothing invented."""
    def _join(match):
        return match.group(0).replace(" ", "")
    return _SPACED_SUFFIX.sub(_join, s)


def normalize_identifier(value: Optional[str]) -> str:
    """Normalize an ЕИК / VAT / serial: keep alphanumerics, upper-case.

    Separators, spaces and dashes carry no identity, so ``BG 123 456 789`` and
    ``BG123456789`` are the same identifier.
    """
    if not value:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = _ZERO_WIDTH.sub("", s)
    s = _NON_ALNUM.sub("", s)
    return s.upper()


def strip_legal_suffix(normalized_name_value: str) -> str:
    """The name without its legal form, for *display* grouping only.

    Never used as an identity key: "Строй ЕООД" and "Строй АД" are two
    different companies and must not collapse into one.
    """
    parts = normalized_name_value.split()
    if parts and parts[-1] in LEGAL_SUFFIXES:
        return " ".join(parts[:-1])
    return normalized_name_value
