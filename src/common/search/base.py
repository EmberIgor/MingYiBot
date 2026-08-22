from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    published_date: str = ""
    author: str = ""
    highlights: tuple[str, ...] = ()

    def to_tool_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "published_date": self.published_date,
            "author": self.author,
            "highlights": list(self.highlights),
        }


@dataclass(frozen=True)
class SearchResponse:
    query: str
    results: tuple[SearchResult, ...]


class SearchError(RuntimeError):
    def __init__(self, code: str, public_message: str, *, status_code: int | None = None) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.status_code = status_code


class SearchProvider(Protocol):
    async def search(self, query: str) -> SearchResponse: ...
