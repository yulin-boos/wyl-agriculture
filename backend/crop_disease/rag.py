from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer


REQUIRED_ENTRY_FIELDS = {
    "id",
    "label",
    "crop",
    "crop_zh",
    "disease_zh",
    "title",
    "source_org",
    "source_url",
    "content",
    "tags",
}


class KnowledgeBaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class RagSettings:
    enabled: bool = True
    corpus_path: Path = Path("knowledge/corpus/disease_guidance.jsonl")
    top_k: int = 1
    chunk_size_chars: int = 480

    @classmethod
    def from_yaml(cls, path: Path, project_root: Path) -> "RagSettings":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        values = payload.get("rag", {})
        corpus = Path(
            str(values.get("corpus", "knowledge/corpus/disease_guidance.jsonl"))
        )
        if not corpus.is_absolute():
            corpus = project_root / corpus
        return cls(
            enabled=bool(values.get("enabled", True)),
            corpus_path=corpus.resolve(),
            top_k=max(1, int(values.get("top_k", 1))),
            chunk_size_chars=max(40, int(values.get("chunk_size_chars", 480))),
        )


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    label: str
    crop: str
    crop_zh: str
    disease_zh: str
    title: str
    source_org: str
    source_url: str
    source_updated: str
    content: str
    tags: list[str]

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.crop,
                self.crop_zh,
                self.disease_zh,
                self.title,
                *self.tags,
                self.content,
            ]
        )


@dataclass(frozen=True)
class KnowledgeHit:
    entry: KnowledgeEntry
    score: float

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.entry.id,
            "title": self.entry.title,
            "source_org": self.entry.source_org,
            "source_url": self.entry.source_url,
            "content": self.entry.content,
            "retrieval_score": round(self.score, 6),
        }

    def to_public_source(self) -> dict[str, Any]:
        return {
            "source_id": self.entry.id,
            "title": self.entry.title,
            "source_org": self.entry.source_org,
            "source_url": self.entry.source_url,
            "retrieval_score": round(self.score, 6),
        }


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    entry: KnowledgeEntry
    content: str

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.entry.crop,
                self.entry.crop_zh,
                self.entry.disease_zh,
                self.entry.title,
                *self.entry.tags,
                self.content,
            ]
        )


@dataclass(frozen=True)
class KnowledgeChunkHit:
    chunk: KnowledgeChunk
    score: float

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.chunk.entry.id,
            "chunk_id": self.chunk.chunk_id,
            "title": self.chunk.entry.title,
            "source_org": self.chunk.entry.source_org,
            "source_url": self.chunk.entry.source_url,
            "content": self.chunk.content,
            "retrieval_score": round(self.score, 6),
        }


def split_content_into_chunks(content: str, chunk_size_chars: int) -> list[str]:
    if chunk_size_chars < 40:
        raise ValueError("分块长度不能小于40个字符。")
    text = content.strip()
    if not text:
        return []
    sentences = [
        sentence.strip()
        for sentence in re.findall(r"[^。！？；]+[。！？；]?", text)
        if sentence.strip()
    ]
    pieces: list[str] = []
    for sentence in sentences:
        if len(sentence) <= chunk_size_chars:
            pieces.append(sentence)
            continue
        pieces.extend(
            sentence[start : start + chunk_size_chars]
            for start in range(0, len(sentence), chunk_size_chars)
        )

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + len(piece) <= chunk_size_chars:
            current += piece
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def build_diagnosis_query(diagnosis: dict[str, Any]) -> tuple[str, str, str] | None:
    predictions = diagnosis.get("predictions") or []
    if not predictions:
        return None
    prediction = predictions[0]
    label = str(prediction.get("label", ""))
    crop = str(prediction.get("crop", ""))
    user_context = diagnosis.get("user_context") or {}
    symptom_description = str(user_context.get("symptom_description", "")).strip()
    context_terms: list[str] = []
    if symptom_description:
        context_terms.append(f"用户描述症状 {symptom_description}")
    query = " ".join(
        [
            str(prediction.get("crop_zh", crop)),
            str(prediction.get("disease_zh", label)),
            *context_terms,
            "症状 传播条件 解决方案 预防 观察 人工复核",
        ]
    )
    return query, label, crop


class LocalKnowledgeBase:
    def __init__(self, entries: list[KnowledgeEntry]) -> None:
        if not entries:
            raise KnowledgeBaseError("知识库中没有可用条目。")
        ids = [entry.id for entry in entries]
        if len(ids) != len(set(ids)):
            raise KnowledgeBaseError("知识库存在重复的来源ID。")
        self.entries = entries
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=1,
            sublinear_tf=True,
            norm="l2",
        )
        self.matrix = self.vectorizer.fit_transform(
            entry.searchable_text() for entry in entries
        )

    @classmethod
    def from_jsonl(cls, path: Path) -> "LocalKnowledgeBase":
        if not path.is_file():
            raise KnowledgeBaseError(f"找不到知识库文件：{path}")
        entries: list[KnowledgeEntry] = []
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise KnowledgeBaseError(
                    f"知识库第 {line_number} 行不是有效JSON。"
                ) from error
            missing = REQUIRED_ENTRY_FIELDS - payload.keys()
            if missing:
                raise KnowledgeBaseError(
                    f"知识库第 {line_number} 行缺少字段：{', '.join(sorted(missing))}"
                )
            if not isinstance(payload["tags"], list):
                raise KnowledgeBaseError(f"知识库第 {line_number} 行的tags必须是数组。")
            entries.append(
                KnowledgeEntry(
                    id=str(payload["id"]),
                    label=str(payload["label"]),
                    crop=str(payload["crop"]),
                    crop_zh=str(payload["crop_zh"]),
                    disease_zh=str(payload["disease_zh"]),
                    title=str(payload["title"]),
                    source_org=str(payload["source_org"]),
                    source_url=str(payload["source_url"]),
                    source_updated=str(payload.get("source_updated", "")),
                    content=str(payload["content"]),
                    tags=[str(tag) for tag in payload["tags"]],
                )
            )
        return cls(entries)

    def retrieve(
        self,
        query: str,
        *,
        label: str | None = None,
        crop: str | None = None,
        top_k: int = 3,
    ) -> list[KnowledgeHit]:
        if top_k <= 0:
            return []
        candidates = list(range(len(self.entries)))
        if label:
            exact = [index for index in candidates if self.entries[index].label == label]
            # 严格标签模式避免把同一作物的其他病害证据错误交给大模型。
            if not exact:
                return []
            candidates = exact
        elif crop:
            candidates = [index for index in candidates if self.entries[index].crop == crop]
        if not candidates:
            return []

        query_vector = self.vectorizer.transform([query])
        scores = (self.matrix @ query_vector.T).toarray().ravel()
        ranked = sorted(candidates, key=lambda index: (-scores[index], self.entries[index].id))
        return [
            KnowledgeHit(entry=self.entries[index], score=float(scores[index]))
            for index in ranked[:top_k]
        ]

    def retrieve_for_diagnosis(
        self, diagnosis: dict[str, Any], top_k: int = 3
    ) -> list[KnowledgeHit]:
        query_parts = build_diagnosis_query(diagnosis)
        if query_parts is None:
            return []
        query, label, crop = query_parts
        return self.retrieve(query, label=label, crop=crop, top_k=top_k)

    def coverage_labels(self) -> list[str]:
        return sorted({entry.label for entry in self.entries})


class ChunkedKnowledgeBase:
    def __init__(self, entries: list[KnowledgeEntry], chunk_size_chars: int) -> None:
        self.entries = list(entries)
        self.chunk_size_chars = chunk_size_chars
        self.chunks = [
            KnowledgeChunk(
                chunk_id=f"{entry.id}-CHUNK-{index:03d}",
                entry=entry,
                content=content,
            )
            for entry in entries
            for index, content in enumerate(
                split_content_into_chunks(entry.content, chunk_size_chars), start=1
            )
        ]
        if not self.chunks:
            raise KnowledgeBaseError("知识库分块后没有可用内容。")
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=1,
            sublinear_tf=True,
            norm="l2",
        )
        self.matrix = self.vectorizer.fit_transform(
            chunk.searchable_text() for chunk in self.chunks
        )

    def coverage_labels(self) -> list[str]:
        return sorted({entry.label for entry in self.entries})

    def coverage_crops(self) -> list[str]:
        return sorted({entry.crop for entry in self.entries})

    @classmethod
    def from_jsonl(cls, path: Path, chunk_size_chars: int) -> "ChunkedKnowledgeBase":
        base = LocalKnowledgeBase.from_jsonl(path)
        return cls(base.entries, chunk_size_chars)

    def retrieve_for_diagnosis(
        self, diagnosis: dict[str, Any], top_k: int = 3
    ) -> list[KnowledgeChunkHit]:
        if top_k <= 0:
            return []
        query_parts = build_diagnosis_query(diagnosis)
        if query_parts is None:
            return []
        query, label, _ = query_parts
        candidates = [
            index
            for index, chunk in enumerate(self.chunks)
            if chunk.entry.label == label
        ]
        if not candidates:
            return []
        query_vector = self.vectorizer.transform([query])
        scores = (self.matrix @ query_vector.T).toarray().ravel()
        ranked = sorted(
            candidates,
            key=lambda index: (-scores[index], self.chunks[index].chunk_id),
        )
        return [
            KnowledgeChunkHit(chunk=self.chunks[index], score=float(scores[index]))
            for index in ranked[:top_k]
        ]
