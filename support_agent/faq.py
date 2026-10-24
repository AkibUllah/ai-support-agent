"""Help-centre articles with BM25 search (English + Bangla aware tokenisation)."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u0980-\u09f1\u09f4-\u09ff]+")
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_STOP = frozenset(
    "a an the is are am do does did i my me you your we our of to in on for and or it can "
    "how what when where which who will would should could be with at by from this that "
    "কি কী কত কোন কীভাবে আমার আমি আপনার এবং ও হবে করে".split()
)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).translate(_BN_DIGITS).lower()
    out = []
    for tok in _TOKEN_RE.findall(text):
        if tok in _STOP:
            continue
        if tok.isascii() and len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    answer: str
    lang: str


class FAQIndex:
    def __init__(self, articles: list[Article], k1: float = 1.2, b: float = 0.75) -> None:
        if not articles:
            raise ValueError("FAQ index needs at least one article")
        self.articles = articles
        self.k1, self.b = k1, b
        self._docs = [Counter(tokenize(f"{a.title} {a.title} {a.answer}")) for a in articles]
        self._len = [sum(d.values()) for d in self._docs]
        self._avg = sum(self._len) / len(self._len)
        n = len(articles)
        df = Counter(t for d in self._docs for t in d)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def load(cls, path: str | Path) -> FAQIndex:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Article(r["id"], r["title"], r["answer"], r.get("lang", "en")) for r in raw])

    def search(self, query: str, k: int = 3) -> list[tuple[Article, float]]:
        terms = set(tokenize(query))
        scored = []
        for i, doc in enumerate(self._docs):
            s = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    norm = 1 - self.b + self.b * self._len[i] / self._avg
                    s += self._idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * norm)
            if s > 0:
                scored.append((self.articles[i], round(s, 4)))
        scored.sort(key=lambda x: (-x[1], x[0].id))
        return scored[:k]
