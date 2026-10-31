"""Mask personal identifiers before text leaves the Mac.

Email addresses, phone numbers and card numbers in anything sent to a
cloud model (the system prompt with your memories, what you say, tool
results such as emails) are swapped for stable placeholders like
[EMAIL_1]. The model works with the placeholders; tool arguments and the
final reply are unmasked locally, so "draft a reply to [EMAIL_1]" still
reaches the right person and you hear the real address. The mapping lives
only in this process's memory for the session.
"""
import re

_PATTERNS = (
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("CARD", re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")),
    ("PHONE", re.compile(
        r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?|\d{2,4}[\s.-]?)"
        r"\d{3,4}[\s.-]?\d{3,4}(?![\w-])"
    )),
)
_TOKEN = re.compile(r"\[?\b(EMAIL|CARD|PHONE)_(\d+)\b\]?")


def _luhn(digits):
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _keep(kind, value):
    digits = re.sub(r"\D", "", value)
    if kind == "CARD":
        return _luhn(digits)
    if kind == "PHONE":
        return 8 <= len(digits) <= 15
    return True


class Vault:
    def __init__(self):
        self._token_for = {}
        self._value_for = {}
        self._counts = {}
        self.used = set()   # tokens produced since the last reset_used()

    def _token(self, kind, value):
        if value not in self._token_for:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            token = "[{}_{}]".format(kind, self._counts[kind])
            self._token_for[value] = token
            self._value_for[token] = value
        token = self._token_for[value]
        self.used.add(token)
        return token

    def mask(self, text):
        if not text:
            return text
        for kind, pattern in _PATTERNS:
            text = pattern.sub(
                lambda m, k=kind: self._token(k, m.group(0)) if _keep(k, m.group(0)) else m.group(0),
                text,
            )
        return text

    def unmask(self, value):
        """Real values back into a string, or every string in a dict/list."""
        if isinstance(value, str):
            return _TOKEN.sub(
                lambda m: self._value_for.get("[{}_{}]".format(m.group(1), m.group(2)), m.group(0)),
                value,
            )
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        return value

    def reset_used(self):
        self.used = set()


class Off:
    """Drop-in Vault that changes nothing (NEBIUS_PRIVACY=off)."""

    used = frozenset()

    def mask(self, text):
        return text

    def unmask(self, value):
        return value

    def reset_used(self):
        pass
