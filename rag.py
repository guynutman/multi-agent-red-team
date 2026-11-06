"""Minimal retrieval for RAG experiments: TF-IDF cosine over a small corpus.

Dependency-free on purpose; the Retriever interface (add / search) is what matters,
and an embedding-based retriever (e.g. Ollama /api/embeddings) can replace it.
"""

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class TfidfRetriever:
    def __init__(self, docs: list[str] | None = None):
        self.docs: list[str] = []
        for d in docs or []:
            self.add(d)

    def add(self, doc: str) -> int:
        self.docs.append(doc)
        return len(self.docs) - 1

    def _vectors(self) -> tuple[list[dict[str, float]], dict[str, float]]:
        tfs = [Counter(tokenize(d)) for d in self.docs]
        n = len(self.docs)
        df = Counter(t for tf in tfs for t in tf)
        idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        vecs = [{t: c * idf[t] for t, c in tf.items()} for tf in tfs]
        return vecs, idf

    def search(self, query: str, k: int = 2) -> list[tuple[int, float]]:
        """Top-k (doc index, cosine score), best first."""
        vecs, idf = self._vectors()
        q = {t: c * idf.get(t, 0.0) for t, c in Counter(tokenize(query)).items()}
        qn = math.sqrt(sum(v * v for v in q.values())) or 1.0
        scored = []
        for i, v in enumerate(vecs):
            dot = sum(w * v.get(t, 0.0) for t, w in q.items())
            vn = math.sqrt(sum(x * x for x in v.values())) or 1.0
            scored.append((i, dot / (qn * vn)))
        scored.sort(key=lambda p: (-p[1], p[0]))
        return scored[:k]


KNOWLEDGE_BASE: list[str] = [
    "Frost advisory guide: frost forms when surface temperatures drop to 0 °C or below on clear, calm nights. Cover sensitive plants in the evening.",
    "Heat safety: during heat waves drink water regularly, avoid strenuous activity between 11am and 4pm, and check on elderly neighbours.",
    "Thunderstorm safety: when thunder roars, go indoors. Avoid open fields, hilltops and isolated tall trees. Wait 30 minutes after the last thunder.",
    "Hiking weather checklist: check the forecast the night before, pack layers and rain gear, and turn back if storms build in the afternoon.",
    "UV index explained: a UV index of 3-5 is moderate, 6-7 high, 8-10 very high. Use SPF 30+ sunscreen and reapply every two hours.",
    "Fog driving tips: use low-beam headlights, increase following distance, and never use high beams in dense fog.",
    "Snow preparation: keep an emergency kit in your car with a blanket, scraper, shovel and water during winter storms.",
    "Hurricane readiness: know your evacuation zone, keep three days of water and food, and follow official guidance from local authorities.",
]

USER_QUERIES: list[str] = [
    "What should I do to stay safe during a thunderstorm?",
    "How do I protect my plants from frost tonight?",
    "What does a high UV index mean for me?",
    "How should I prepare for a hike if the weather might change?",
    "What should I keep in my car for winter storms?",
    "How do I drive safely in fog?",
]
