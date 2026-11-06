"""Dependency-free BM25 search over chunks.jsonl (retrieval smoke test / baseline)."""
import json
import math
import re
from collections import Counter

STOP = set("a an and are as at be but by for from has have how in is it of on or that the this to was what "
           "when where which who why will with you your can does do not".split())
TOKEN = re.compile(r"[a-z0-9][a-z0-9.%/-]*")


def tokenize(text):
    toks = [t.strip(".-/") for t in TOKEN.findall(text.lower())]
    return [t for t in toks if t and t not in STOP]


class KBSearcher:
    def __init__(self, chunks_path=None, chunks=None, k1=1.4, b=0.75):
        if chunks is None:
            with open(chunks_path, encoding="utf-8") as fh:
                chunks = [json.loads(line) for line in fh if line.strip()]
        self.chunks, self.k1, self.b = chunks, k1, b
        self.docs = []
        for c in chunks:
            # section path is weighted by repeating it: headings are strong topical signals
            self.docs.append(Counter(tokenize(c.get("section_path_str", "") + " ") * 2 + tokenize(c["text"])))
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 1.0
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query, k=5, **filters):
        """filters: any chunk field == value (or in list), e.g. section_type="diagnosis"."""
        q = tokenize(query)
        out = []
        for i, c in enumerate(self.chunks):
            if any((c.get(f) not in v) if isinstance(v, (list, tuple, set)) else (c.get(f) != v)
                   for f, v in filters.items()):
                continue
            d, score = self.docs[i], 0.0
            for t in q:
                tf = d.get(t, 0)
                if tf:
                    score += self.idf[t] * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
            if score > 0:
                out.append((round(score, 4), c))
        out.sort(key=lambda x: -x[0])
        return out[:k]
