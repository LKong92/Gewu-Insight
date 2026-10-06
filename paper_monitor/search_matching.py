"""Local fuzzy text matching, mirrored by the workspace JS and parity-tested.

Scores: exact phrase/identifier 3, token/word-ending match 2, typo match 1.
No providers, model calls, synonym expansion or writes are involved.
"""
import math
import re
import unicodedata
from functools import lru_cache

SUFFIXES = ('ations', 'ation', 'ments', 'ment', 'ities', 'ity', 'ions', 'ion', 'tion', 'ing', 'ed', 'es', 's')


def normalize(value):
    text = unicodedata.normalize('NFD', str(value or '')).lower()
    text = re.sub(r'[\u0300-\u036f]', '', text)
    return re.sub(r'[\W_]+', ' ', text).strip()


def compact(value):
    text = re.sub(r'https?://(dx\.)?doi\.org/', '', str(value or '').lower())
    return re.sub(r'[^a-z0-9]', '', text)


@lru_cache(maxsize=8192)
def variants(token):
    return tuple(dict.fromkeys([token] + [token[:-len(s)] for s in SUFFIXES
                                         if len(token) > len(s) + 3 and token.endswith(s)]))


def within(left, right, limit):
    if abs(len(left) - len(right)) > limit:
        return False
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j-1] + 1, previous[j-1] + (a != b)))
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


def scorer(query):
    query = str(query or '')[:300]
    normalized = normalize(query)
    key = compact(query)
    tokens = [t for t in normalized.split() if len(t) > 1]
    long_count = sum(len(t) >= 4 for t in tokens)
    required = len(tokens) if len(tokens) <= 2 else max(2, math.ceil(len(tokens) * .66))

    def score(haystack):
        text = normalize(haystack)
        if not normalized or normalized in text or (key and key in compact(haystack)):
            return 3
        if not tokens:
            return 0
        words = text.split()
        word_set = {v for word in words for v in variants(word)}
        direct = matched = 0
        for token in tokens:
            forms = variants(token)
            if any(v in text or v in word_set for v in forms):
                direct += 1
                matched += 1
                continue
            if len(token) < 4 or long_count > 8:
                continue
            comparable = [w for w in words if len(w) >= 4 and abs(len(w)-len(token)) <= 3 and w[0] == token[0]][:80]
            if any(((w in v or v in w) and min(len(w), len(v)) >= 4)
                   or within(v, w, 1 if len(v) <= 4 else (2 if len(v) <= 8 else 3))
                   for v in forms for w in comparable):
                matched += 1
        return 2 if direct >= required else (1 if matched >= required else 0)
    return score
