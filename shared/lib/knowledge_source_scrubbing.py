"""Bounded, ordered redaction of normalized Knowledge Source bodies."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from typing import TYPE_CHECKING

import regex

if TYPE_CHECKING:
    from shared.lib.knowledge_source_confluence import NormalizedDocument

MAX_SCRUB_RULES = 100
MAX_SCRUB_PATTERN_CHARS = 2000
SCRUB_TIMEOUT_SEC = 1.0
REPLACEMENT = "[REDACTED]"


def compile_scrub_rules(patterns: list[str]) -> tuple[regex.Pattern, ...]:
    if not isinstance(patterns, list) or any(not isinstance(pattern, str) for pattern in patterns):
        raise ValueError("Scrub patterns must be a list of strings")
    if len(patterns) > MAX_SCRUB_RULES:
        raise ValueError(f"At most {MAX_SCRUB_RULES} scrub patterns are supported")
    compiled = []
    for line, pattern in enumerate(patterns, 1):
        if not pattern.strip():
            continue
        if len(pattern) > MAX_SCRUB_PATTERN_CHARS or "\n" in pattern or "\r" in pattern:
            raise ValueError(f"Scrub rule line {line} must be one line of at most {MAX_SCRUB_PATTERN_CHARS} characters")
        try:
            compiled.append(regex.compile(pattern, regex.VERSION0))
        except regex.error:
            raise ValueError(f"Invalid regex on scrub rule line {line}") from None
    return tuple(compiled)


def scrub_document(document: NormalizedDocument, rules: tuple[regex.Pattern, ...]) -> NormalizedDocument:
    from shared.lib.knowledge_source_confluence import normalized_text

    deadline = monotonic() + SCRUB_TIMEOUT_SEC
    blocks = document.blocks
    for line, rule in enumerate(rules, 1):
        content = normalized_text(blocks)
        spans = []
        offset = 0
        for block in blocks:
            prefix = len(block.heading_path) + 1 if block.kind == "heading" else 4 if block.kind == "code" else 0
            start = offset + prefix
            spans.append((start, start + len(block.text)))
            offset = start + len(block.text) + (4 if block.kind == "code" else 0) + 2
        edits: list[list[tuple[int, int, str]]] = [[] for _ in blocks]
        try:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            for match in rule.finditer(content, timeout=remaining):
                inserted = False
                for index, (start, end) in enumerate(spans):
                    if (
                        match.start() < end
                        and match.end() > start
                        or match.start() == match.end()
                        and start <= match.start() <= end
                    ):
                        edits[index].append(
                            (
                                max(0, match.start() - start),
                                min(end - start, match.end() - start),
                                "" if inserted else REPLACEMENT,
                            )
                        )
                        inserted = True
                if monotonic() >= deadline:
                    raise TimeoutError
        except TimeoutError:
            raise ValueError(f"Scrub rule line {line} exceeded the body execution budget") from None
        updated = []
        headings = {}
        for block, changes in zip(blocks, edits, strict=True):
            text = block.text
            for start, end, replacement in reversed(changes):
                text = text[:start] + replacement + text[end:]
            if block.kind == "heading":
                headings[block.heading_path] = text
            path = tuple(headings[block.heading_path[:depth]] for depth in range(1, len(block.heading_path) + 1))
            updated.append(replace(block, text=text, heading_path=path))
        blocks = tuple(updated)
    return replace(document, blocks=blocks, content=normalized_text(blocks)) if rules else document
