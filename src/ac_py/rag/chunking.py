"""按售后政策层级切分文档，并为父章节与条款生成稳定标识。"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ac_py.domain.enums import Scene
from ac_py.domain.schemas import PolicyChunk

HEADING_PATTERN = re.compile(
    r"^(#{1,6}\s+.+|第[一二三四五六七八九十百\d]+[章节条].+|\d+[.、]\s*.+)$"
)
SENTENCE_PATTERN = re.compile(r"(?<=[。！？；\n])")


@dataclass(slots=True)
class ParsedDocument:
    """表示文档解析后的统一标题与正文。"""

    title: str
    text: str


def stable_id(*parts: str) -> str:
    """根据稳定文本片段生成短哈希标识。"""

    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def parse_document(path: Path) -> ParsedDocument:
    """解析政策文件；结构化格式优先使用 Docling，纯文本直接读取。"""

    if path.suffix.lower() in {".txt", ".md"}:
        return ParsedDocument(title=path.stem, text=path.read_text(encoding="utf-8"))
    try:
        from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("解析 PDF/Word 需要安装 documents 依赖组") from exc
    result = DocumentConverter().convert(path)
    return ParsedDocument(title=path.stem, text=result.document.export_to_markdown())


def split_policy(
    document_id: str,
    version: str,
    title: str,
    text: str,
    scene: Scene,
    *,
    max_chars: int = 1200,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> list[PolicyChunk]:
    """按标题和条款边界切分政策，并对超长条款递归切分。"""

    normalized = _normalize(text)
    has_headings = any(HEADING_PATTERN.match(line) for line in normalized.splitlines())
    if len(normalized) <= max_chars and not has_headings:
        chunk_id = stable_id(document_id, version, "atomic")
        return [
            PolicyChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                version=version,
                title=title,
                level="atomic",
                scene=scene,
                content=normalized,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        ]

    sections = _sections(title, normalized)
    chunks: list[PolicyChunk] = []
    for section_index, (section_title, section_text) in enumerate(sections):
        parent_id = stable_id(document_id, version, "parent", str(section_index), section_title)
        chunks.append(
            PolicyChunk(
                chunk_id=parent_id,
                document_id=document_id,
                version=version,
                title=section_title,
                level="parent",
                scene=scene,
                content=section_text,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
        for child_index, child_text in enumerate(_split_long(section_text, max_chars)):
            child_id = stable_id(parent_id, "child", str(child_index), child_text[:80])
            chunks.append(
                PolicyChunk(
                    chunk_id=child_id,
                    document_id=document_id,
                    version=version,
                    title=section_title,
                    parent_id=parent_id,
                    level="child",
                    scene=scene,
                    content=child_text,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
            )
    return chunks


def _normalize(text: str) -> str:
    """统一换行和空白，同时保留标题及列表边界。"""

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _sections(default_title: str, text: str) -> list[tuple[str, str]]:
    """按标题行把政策正文划分为章节。"""

    sections: list[tuple[str, list[str]]] = []
    current_title = default_title
    current_lines: list[str] = []
    for line in text.splitlines():
        if HEADING_PATTERN.match(line) and current_lines:
            sections.append((current_title, current_lines))
            current_title = line.lstrip("# ").strip()
            current_lines = []
        elif HEADING_PATTERN.match(line):
            current_title = line.lstrip("# ").strip()
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))
    return [(section_title, "\n".join(lines)) for section_title, lines in sections]


def _split_long(text: str, max_chars: int) -> list[str]:
    """按句子边界切分超长章节，并保持句子完整。"""

    if len(text) <= max_chars:
        return [text]
    sentences = [sentence.strip() for sentence in SENTENCE_PATTERN.split(text) if sentence.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = ""
        if len(sentence) > max_chars:
            chunks.extend(
                sentence[index : index + max_chars] for index in range(0, len(sentence), max_chars)
            )
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks
