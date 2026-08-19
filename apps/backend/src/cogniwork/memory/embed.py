"""Embedding 接入。维度写死 1024，换模型靠 embed_model + 后台重算（P0-02 §6）。"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

EMBED_DIM = 1024
STUB_MODEL = "stub-hash-1024"


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class StubEmbeddingProvider:
    """无密钥时的确定性向量。相同文本得到相同方向，便于单测与评测。"""

    model = STUB_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_vector(text) for text in texts]


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key)
        response = client.embeddings.create(model=self.model, input=texts, dimensions=EMBED_DIM)
        ordered = sorted(response.data, key=lambda row: row.index)
        return [_l2_normalize(list(row.embedding)) for row in ordered]


def build_embedding_provider(*, openai_api_key: str = "") -> EmbeddingProvider:
    if openai_api_key:
        return OpenAIEmbeddingProvider(openai_api_key)
    return StubEmbeddingProvider()


def cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    n = min(len(left), len(right))
    if n == 0:
        return 0.0
    dot = sum(left[i] * right[i] for i in range(n))
    return max(-1.0, min(1.0, dot))


def _hash_vector(text: str) -> list[float]:
    values: list[float] = []
    seed = 0
    while len(values) < EMBED_DIM:
        digest = hashlib.sha256(f"{text}\n{seed}".encode()).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == EMBED_DIM:
                break
        seed += 1
    return _l2_normalize(values)


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
