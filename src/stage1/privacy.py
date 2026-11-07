"""Redaction of personal data in free text.

Names are taken from the CRM student/parent name columns (first/last name tokens); phone numbers
and e-mail addresses are matched by pattern. Limitation: a person who is NOT in the CRM name
columns, or a name written in an unusual form, will not be detected. Raw files are never edited.
"""
from __future__ import annotations

import re

import pandas as pd

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE = re.compile(r"\+?\d[\d\s\-]{8,}\d")


def _tokens(series: pd.Series) -> set[str]:
    """Whitespace-separated name parts exactly as they appear in the CRM (may be partly masked, e.g. 'Aa***v')."""
    return {tok for v in series.dropna() for tok in v.split() if tok}


def _pattern(token: str) -> str:
    """Regex for one name part. A masked part 'Aa***v' matches any word that starts with 'Aa' and ends with 'v'
    (over-redaction is the safe direction); an unmasked part matches literally."""
    m = re.fullmatch(r"([^*]+)\*+(.)", token)
    if m:
        return re.escape(m.group(1)) + r"[A-Za-z\-]{1,20}" + re.escape(m.group(2))
    return re.escape(token)


def _rx(tokens: set[str]):
    if not tokens:
        return None
    alt = "|".join(_pattern(t) for t in sorted(tokens, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z])(?:{alt})(?![A-Za-z])", re.I)


class Redactor:
    def __init__(self, crm: pd.DataFrame):
        student, parent = _tokens(crm["student_name"]), _tokens(crm["parent_name"])
        shared = student & parent
        self.all_tokens = student | parent
        self._rules = [("name", "[NAME]", _rx(shared)), ("student name", "[STUDENT]", _rx(student - shared)),
                       ("parent name", "[PARENT]", _rx(parent - shared))]

    def redact(self, text, phone: bool = True):
        """Return (redacted_text, labels_found). Non-strings pass through unchanged."""
        if not isinstance(text, str):
            return text, []
        found = []
        for label, repl, rx in self._rules:
            if rx is not None and rx.search(text):
                text, found = rx.sub(repl, text), found + [label]
        if EMAIL.search(text):
            text, found = EMAIL.sub("[EMAIL]", text), found + ["email"]
        if phone and PHONE.search(text):
            text, found = PHONE.sub("[PHONE]", text), found + ["phone number"]
        return text, found

    def series(self, s: pd.Series, phone: bool = True) -> pd.Series:
        return s.map(lambda v: self.redact(v, phone)[0])

    def name_tokens(self) -> set[str]:
        return set(self.all_tokens)
