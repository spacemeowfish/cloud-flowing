"""Zero-download hashing embeddings and a small SQLite vector store."""

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from docx import Document

from agent_platform.core.interfaces import Embedder


class HashingEmbedder(Embedder):
    """Deterministic character n-gram vectors suitable for offline smoke use."""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 32:
            raise ValueError("dimensions must be at least 32")
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        normalized = re.sub(r"\s+", "", text.casefold())
        tokens = [normalized[index : index + 2] for index in range(max(1, len(normalized) - 1))]
        if len(normalized) == 1:
            tokens = [normalized]
        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimensions
            vector[index] += -1.0 if value & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class DocumentParser:
    def parse(self, path: Path) -> str:
        suffix = path.suffix.casefold()
        if suffix in {".txt", ".md"}:
            content = path.read_bytes()
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            raise UnicodeError(f"Unable to decode {path.name} as UTF-8 or GB18030")
        if suffix == ".docx":
            document = Document(path)
            return "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
        raise ValueError(f"Unsupported document format: {suffix}")


_FRONT_MATTER = re.compile(r"\A---\s*\r?\n(?P<body>.*?)\r?\n---", re.DOTALL)
_SCOPE_FIELD = re.compile(r"(?im)^\s*(?:scope|适用范围)\s*[:：]\s*(?P<value>\S.*)$")


def extract_document_scope(text: str, suffix: str) -> str:
    """Return only an explicitly declared scope from already-redacted document text."""

    candidates: list[str] = []
    if suffix.casefold() == ".md":
        front_matter = _FRONT_MATTER.match(text)
        if front_matter:
            candidates.append(front_matter.group("body"))
    candidates.append(text)
    for candidate in candidates:
        match = _SCOPE_FIELD.search(candidate)
        if match:
            value = " ".join(match.group("value").split())
            if value:
                return value[:120]
    return "未声明"


def chunk_text(text: str, *, max_chars: int = 1200, overlap_chars: int = 120) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + max_chars)
            chunks.append(paragraph[start:end])
            if end == len(paragraph):
                break
            start = max(start + 1, end - overlap_chars)
        current = ""
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class SearchHit:
    document: str
    position: int
    text: str
    score: float
    mtime: float
    scope: str
    path: str = ""


class SQLiteVectorStore:
    def __init__(self, path: Path, embedder: Embedder) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        # The admin reindex route opens a second connection against the same
        # database file; without WAL any concurrent read/write pair fails with
        # "database is locked" once the default 5s busy window is exhausted.
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._embedder = embedder
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents(
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                scope TEXT NOT NULL DEFAULT '未声明'
            );
            CREATE TABLE IF NOT EXISTS chunks(
                document TEXT NOT NULL,
                position INTEGER NOT NULL,
                text TEXT NOT NULL,
                vector TEXT NOT NULL,
                PRIMARY KEY(document, position)
            );
            """
        )
        columns = {str(row[1]) for row in self._connection.execute("PRAGMA table_info(documents)")}
        if "scope" not in columns:
            self._connection.execute("ALTER TABLE documents ADD COLUMN scope TEXT NOT NULL DEFAULT '未声明'")
            self._connection.commit()

    def indexed_mtime(self, path: Path) -> float | None:
        row = self._connection.execute("SELECT mtime FROM documents WHERE path = ?", (str(path),)).fetchone()
        return float(row[0]) if row else None

    def replace_document(self, path: Path, mtime: float, chunks: list[str], *, scope: str) -> None:
        vectors = self._embedder.embed(chunks)
        with self._connection:
            self._connection.execute("DELETE FROM chunks WHERE document = ?", (str(path),))
            self._connection.execute(
                """INSERT INTO documents(path, mtime, scope) VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, scope=excluded.scope""",
                (str(path), mtime, scope),
            )
            self._connection.executemany(
                "INSERT INTO chunks(document, position, text, vector) VALUES (?, ?, ?, ?)",
                [
                    (str(path), index, chunk, json.dumps(vector))
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        query_vector = self._embedder.embed([query])[0]
        rows = self._connection.execute(
            """SELECT chunks.document, chunks.position, chunks.text, chunks.vector, documents.mtime, documents.scope
            FROM chunks JOIN documents ON documents.path = chunks.document"""
        ).fetchall()
        hits = []
        for document, position, text, vector_json, mtime, scope in rows:
            vector = json.loads(vector_json)
            score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
            hits.append(
                SearchHit(
                    Path(document).name,
                    int(position),
                    text,
                    score,
                    float(mtime),
                    str(scope),
                    str(document),
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    def close(self) -> None:
        self._connection.close()


__all__ = [
    "DocumentParser",
    "HashingEmbedder",
    "SQLiteVectorStore",
    "SearchHit",
    "chunk_text",
    "extract_document_scope",
]
