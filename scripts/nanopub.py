#!/usr/bin/env python3
"""Source-index and validation helpers for scientific nanopublication extraction.

The tool deliberately does not generate scientific claims. It extracts source
text, recalls candidate sentences, verifies exact evidence quotes, computes
locations, and writes a deterministic result envelope.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html.parser
import json
import os
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterable


VERSION = "1.0.0"
SUPPORTED_TEXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".html",
                  ".htm", ".xml", ".docx", ".pdf"}
SKIP_NAMES = {
    "case.json", "task.md", "claims.json", "draft.json", "draft_claims.json",
    "result.json", "arm_manifest.json", "characterization.json",
}
EVIDENCE_RELATIONS = {"supports", "refutes", "qualifies", "contextualizes"}
EVIDENCE_TYPES = {"direct", "indirect", "contextual"}
STATUSES = {"success", "partial", "unable"}
QUALITY_FLAGS = {
    "overbroad", "causal_overreach", "numeric_mismatch", "negation_risk",
    "compound", "figure_only", "table_context", "ocr", "translation",
    "contradicted", "inferred",
}
RELATION_TYPES = {
    "increase", "decrease", "no_change", "positive_association",
    "negative_association", "association", "causal", "comparison",
    "prediction", "method", "definition", "limitation", "other",
}
CLAIM_CUES = {
    "result", "results", "found", "find", "show", "shows", "shown",
    "demonstrate", "demonstrates", "report", "reported", "observed",
    "observe", "suggest", "suggests", "indicate", "indicates", "increase",
    "increased", "decrease", "decreased", "reduce", "reduced", "higher",
    "lower", "associated", "correlat", "significant", "compared", "versus",
    "vs.", "p =", "p=", "95% ci", "hazard ratio", "odds ratio",
    "结果表明", "研究发现", "显著", "增加", "降低", "减少", "相关",
    "相比", "表明", "发现", "观察到",
}
CAUSAL_WORDS = {
    "cause", "caused", "causes", "because", "due to", "lead to", "leads to",
    "led to", "result in", "results in", "resulted in", "mechanism", "mediate",
    "mediates", "drive", "drives", "induced", "causal", "导致", "引起",
    "使得", "造成", "机制", "介导",
}
NEGATIONS = {
    "no", "not", "none", "never", "without", "neither", "nor", "n't",
    "未", "无", "不", "没有", "不能", "并非",
}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def append_log(path: Path, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"time": now_utc(), "event": event, **fields}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False))
        handle.write("\n")


def stable_id(prefix: str, value: str, length: int = 12) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:length]}"


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u0000", "")
    return text.strip("\n")


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace while retaining a map back into the raw string."""
    out: list[str] = []
    char_map: list[int] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            start = i
            while i < len(text) and text[i].isspace():
                i += 1
            out.append(" ")
            char_map.append(start)
        else:
            out.append(text[i])
            char_map.append(i)
            i += 1
    char_map.append(len(text))
    return "".join(out), char_map


def find_quote(text: str, quote: str) -> dict[str, int] | None:
    haystack, char_map = normalize_with_map(text)
    needle = normalize_ws(quote)
    if not needle:
        return None
    index = haystack.find(needle)
    if index < 0:
        return None
    end_index = index + len(needle)
    return {
        "normalized_start": index,
        "char_start": char_map[index],
        "char_end": char_map[end_index],
    }


def norm_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text)


def contains_word(text: str, words: set[str]) -> bool:
    lowered = text.casefold()
    for word in words:
        if word.isascii() and re.search(r"[A-Za-z0-9]", word):
            pattern = r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])"
            if re.search(pattern, lowered):
                return True
        elif word in lowered:
            return True
    return False


def detect_language(text: str) -> str:
    if re.search(r"[\u3400-\u9fff]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "und"


def infer_relation_type(text: str, relation: str, draft_value: Any = None) -> str:
    if isinstance(draft_value, str) and draft_value.casefold() in RELATION_TYPES:
        return draft_value.casefold()
    value = f"{relation} {text}".casefold()
    if re.search(
        r"\b(no|not|did not|unchanged|equivalent)\b.*\b(change|alter|differ|difference)\b"
        r"|无(?:显著)?变化|未见改变|不变|无差异",
        value,
    ):
        return "no_change"
    if contains_word(value, CAUSAL_WORDS):
        return "causal"
    if contains_word(value, {
        "associated with", "correlated with", "correlation", "相关", "关联",
    }):
        if contains_word(value, {
            "negative association", "inverse association", "negatively",
            "负相关", "反向相关",
        }):
            return "negative_association"
        if contains_word(value, {
            "positive association", "positively", "直接相关", "正相关",
        }):
            return "positive_association"
        return "association"
    if contains_word(value, {
        "increase", "increased", "higher", "greater", "rise", "rose",
        "enhance", "promote", "upregulate", "增加", "升高", "提高",
    }):
        return "increase"
    if contains_word(value, {
        "decrease", "decreased", "reduce", "reduced", "lower", "less",
        "inhibit", "downregulate", "降低", "减少", "抑制",
    }):
        return "decrease"
    if contains_word(value, {
        "predict", "model estimates", "forecast", "预计", "预测",
    }):
        return "prediction"
    if contains_word(value, {
        "we measured", "method", "assay", "protocol", "measured using",
        "方法", "检测", "测定",
    }):
        return "method"
    if contains_word(value, {
        "defined as", "definition", "refers to", "定义为", "是指",
    }):
        return "definition"
    if contains_word(value, {
        "limitation", "limited by", "may not", "局限", "限制",
    }):
        return "limitation"
    if contains_word(value, {
        "higher than", "lower than", "compared with", "versus", "较", "相比",
    }):
        return "comparison"
    return "other"


def slug_stem(path: Path) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-")
    return value or "source"


def discover_inputs(input_root: Path, case_path: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(input_root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        relative = path.relative_to(input_root)
        if any(part in {
            "out", "output", "outputs", ".git", "work", "traces",
            "solution", "solutions", "tests", "test", "gold", "answers",
        }
               for part in relative.parts[:-1]):
            continue
        if path.suffix.lower() in SUPPORTED_TEXT:
            if path.resolve() == case_path.resolve():
                continue
            files.append(path)
    return files


def paths_declared_in_case(case: dict[str, Any], case_path: Path,
                           input_root: Path) -> list[Path]:
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and len(value) < 4096:
            if Path(value).suffix.lower() in SUPPORTED_TEXT:
                strings.append(value)

    walk(case)
    paths: list[Path] = []
    for value in strings:
        direct = Path(value)
        candidates = [direct] if direct.is_absolute() else [
            case_path.parent / direct,
            input_root / direct,
            Path.cwd() / direct,
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in SUPPORTED_TEXT:
                paths.append(candidate.resolve())
                break
    return paths


def first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def extract_pdf_fitz(path: Path) -> tuple[list[str], dict[str, Any], str] | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    try:
        doc = fitz.open(path)
        pages = [page.get_text("text") or "" for page in doc]
        metadata = dict(doc.metadata or {})
        doc.close()
        return pages, metadata, "pymupdf"
    except Exception:
        return None


def extract_pdf_pypdf(path: Path) -> tuple[list[str], dict[str, Any], str] | None:
    reader_class = None
    try:
        from pypdf import PdfReader as reader_class  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader as reader_class  # type: ignore
        except Exception:
            return None
    try:
        reader = reader_class(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        raw_meta = getattr(reader, "metadata", None) or {}
        metadata = {str(key).lstrip("/"): str(value) for key, value in raw_meta.items()}
        return pages, metadata, "pypdf"
    except Exception:
        return None


def extract_pdf_poppler(path: Path) -> tuple[list[str], dict[str, Any], str] | None:
    command = ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
    except Exception:
        return None
    pages = result.stdout.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    metadata: dict[str, Any] = {}
    try:
        info = subprocess.run(
            ["pdfinfo", str(path)], check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        ).stdout
        for line in info.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
    except Exception:
        pass
    return pages, metadata, "pdftotext"


def extract_pdf(path: Path) -> tuple[list[str], dict[str, Any], str]:
    for extractor in (extract_pdf_fitz, extract_pdf_pypdf, extract_pdf_poppler):
        result = extractor(path)
        if result is not None and any(clean_text(page) for page in result[0]):
            return result
    return [], {}, "unavailable"


class VisibleHTML(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        elif tag.casefold() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3",
                                "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1
        elif tag.casefold() in {"p", "div", "li", "tr", "h1", "h2", "h3",
                                "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        try:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
        except KeyError:
            return ""
    xml = re.sub(r"</w:p\s*>", "\n\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return clean_text(html.unescape(xml))


def extract_plain(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix in {".html", ".htm", ".xml"}:
        parser = VisibleHTML()
        parser.feed(text)
        return parser.text()
    if suffix == ".json":
        try:
            value = json.loads(text)
        except Exception:
            return clean_text(text)
        strings: list[str] = []

        def walk(item: Any, key: str = "") -> None:
            if isinstance(item, dict):
                for child_key, child in item.items():
                    walk(child, str(child_key))
            elif isinstance(item, list):
                for child in item:
                    walk(child, key)
            elif isinstance(item, str) and len(item) >= 2:
                strings.append(f"{key}: {item}" if key else item)

        walk(value)
        return clean_text("\n\n".join(strings))
    return clean_text(text)


def infer_metadata(path: Path, pages: list[str], raw_meta: dict[str, Any]) -> dict[str, Any]:
    first = pages[0] if pages else ""
    lines = [normalize_ws(line) for line in first.splitlines() if normalize_ws(line)]
    title = (
        raw_meta.get("title")
        or raw_meta.get("Title")
        or raw_meta.get("dc:title")
        or raw_meta.get("DCTERMS.title")
    )
    author_value = (
        raw_meta.get("author")
        or raw_meta.get("Author")
        or raw_meta.get("dc:creator")
        or raw_meta.get("DCTERMS.creator")
    )
    authors: list[str] = []
    if isinstance(author_value, str) and author_value.strip():
        authors = [part.strip() for part in re.split(
            r"\s*(?:;|\band\b|,\s*(?=[A-Z]))\s*", author_value
        ) if part.strip()]
    year_value = (
        raw_meta.get("publicationDate")
        or raw_meta.get("date")
        or raw_meta.get("DCTERMS.issued")
    )
    year = None
    year_match = re.search(r"(?:19|20)\d{2}", str(year_value or ""))
    if year_match:
        year = int(year_match.group(0))
    if year is None:
        year_match = re.search(
            r"(?:published|accepted|copyright|©)\s*(?:online\s*)?(?:on\s*)?"
            r"(?:[A-Za-z]+\s+\d{1,2},\s*)?((?:19|20)\d{2})",
            first[:12000],
            re.I,
        )
        if year_match:
            year = int(year_match.group(1))
    doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", first[:12000])
    arxiv_match = re.search(
        r"\barXiv\s*:\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", first[:12000], re.I
    )
    identifier = None
    if doi_match:
        identifier = "doi:" + doi_match.group(0).rstrip(".,;)")
    elif arxiv_match:
        identifier = "arxiv:" + arxiv_match.group(1)
    return {
        "title": normalize_ws(title) if isinstance(title, str) else None,
        "authors": authors,
        "year": year,
        "version": str(raw_meta.get("version") or raw_meta.get("Version") or "") or None,
        "identifier": identifier,
    }


def split_blocks(text: str, page: int) -> list[dict[str, Any]]:
    text = clean_text(text)
    if not text:
        return []
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\S(?:[\s\S]*?\S)?(?=\n[ \t]*\n|\Z)", text):
        spans.append((match.start(), match.end(), text[match.start():match.end()]))
    if not spans:
        spans = [(0, len(text), text)]

    blocks: list[dict[str, Any]] = []
    for start, end, raw in spans:
        if len(normalize_ws(raw)) <= 2200:
            parts = [(start, end, raw)]
        else:
            parts = []
            sentence_matches = list(re.finditer(r".+?(?:[.!?。！？](?=\s|$)|$)", raw, re.S))
            cursor = 0
            buffer: list[re.Match[str]] = []
            for sentence in sentence_matches:
                candidate_len = len(normalize_ws(raw[cursor:sentence.end()]))
                if buffer and candidate_len > 1500:
                    part_start = start + buffer[0].start()
                    part_end = start + buffer[-1].end()
                    parts.append((part_start, part_end, text[part_start:part_end]))
                    cursor = buffer[-1].end()
                buffer.append(sentence)
            if buffer:
                part_start = start + buffer[0].start()
                part_end = start + buffer[-1].end()
                parts.append((part_start, part_end, text[part_start:part_end]))
        # Pull an explicit section-like heading forward into the next block.
        for start2, end2, raw2 in parts:
            compact = normalize_ws(raw2)
            section = compact if len(compact) <= 100 and (
                re.match(r"^(\d+(?:\.\d+)*\s+|[A-Z][A-Za-z ]+$)", compact)
                or re.search(r"^(摘要|引言|方法|结果|讨论|结论|参考文献)$", compact)
            ) else None
            blocks.append({
                "page": page,
                "paragraph": len(blocks) + 1,
                "section": section,
                "char_start": start2,
                "char_end": end2,
                "text": raw2,
                "is_heading": bool(section),
            })
    return blocks


def assign_sections(blocks: list[dict[str, Any]]) -> None:
    current: str | None = None
    for block in blocks:
        if block.get("is_heading"):
            current = block.get("section")
        else:
            block["section"] = current


def iter_sentences(text: str) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    pattern = re.compile(r".+?(?:[.!?。！？](?=\s|$)|$)", re.S)
    for match in pattern.finditer(text):
        raw = match.group(0).strip()
        if not raw:
            continue
        leading = len(match.group(0)) - len(match.group(0).lstrip())
        trailing = len(match.group(0)) - len(match.group(0).rstrip())
        result.append((
            match.start() + leading,
            match.end() - trailing,
            raw,
        ))
    return result


def case_identity(case: dict[str, Any], case_path: Path) -> str:
    value = case.get(
        "case_id", case.get("caseId", case.get("task_id", case.get("id")))
    )
    if value is not None:
        return str(value)
    return stable_id("case", str(case_path.resolve()), 16)


def output_contract_from_case(case: dict[str, Any]) -> Any:
    if "output_contract" in case:
        return case["output_contract"]
    for key in ("contract", "response_contract", "required_output"):
        value = case.get(key)
        if isinstance(value, dict) and isinstance(value.get("output_contract"), (dict, list)):
            return value["output_contract"]
    task = case.get("task")
    if isinstance(task, dict):
        if "output_contract" in task:
            return task["output_contract"]
        for key in ("contract", "response_contract"):
            value = task.get(key)
            if isinstance(value, dict) and isinstance(value.get("output_contract"), (dict, list)):
                return value["output_contract"]
    return None


def extract_task_text(case_path: Path) -> str:
    task_path = first_existing([
        case_path.parent / "task.md",
        Path("/input/task.md"),
    ])
    if task_path:
        return task_path.read_text(encoding="utf-8-sig", errors="replace")
    return ""


def inline_material(case: dict[str, Any]) -> list[tuple[str, str]]:
    preferred = {
        "paper_text", "material_text", "source_text", "document_text",
        "provided_material", "input_text", "raw_text",
    }
    found: list[tuple[str, str]] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{key}_{index + 1}")
        elif isinstance(value, str) and key.casefold() in preferred and len(value.strip()) >= 80:
            found.append((key, value))

    walk(case)
    return found


def make_source_index(case_path: Path, input_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]],
                                                                   list[dict[str, Any]], list[dict[str, Any]]]:
    case = read_json(case_path)
    paths = discover_inputs(input_root, case_path)
    for declared_path in paths_declared_in_case(case, case_path, input_root):
        if all(declared_path != existing.resolve() for existing in paths):
            paths.append(declared_path)
    paths.sort(key=lambda item: str(item))
    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    inventory_files: list[dict[str, Any]] = []

    source_specs: list[tuple[str, Path | None, list[str], dict[str, Any], str]] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages, meta, extractor = extract_pdf(path)
        else:
            text = extract_plain(path)
            pages = [text] if text else []
            meta = {}
            extractor = f"{suffix.lstrip('.')}-text"
        source_specs.append((str(path), path, pages, meta, extractor))
    for index, (name, text) in enumerate(inline_material(case), start=1):
        source_specs.append((f"inline:{name or index}", None, [text], {}, "case-inline"))

    for position, (label, path, pages, raw_meta, extractor) in enumerate(source_specs, start=1):
        display_file = str(path.resolve()) if path else label
        digest = sha256_file(path) if path else hashlib.sha256(
            "\n\f".join(pages).encode("utf-8")
        ).hexdigest()
        source_id = stable_id("src", digest + display_file, 12)
        meta = infer_metadata(path or Path(label.replace(":", "_") + ".txt"), pages, raw_meta)
        source = {
            "source_id": source_id,
            "file": display_file,
            "title": meta["title"] or (path.stem.replace("_", " ") if path else label),
            "authors": meta["authors"],
            "year": meta["year"],
            "version": meta["version"],
            "identifier": meta["identifier"],
            "sha256": digest,
            "page_count": len(pages) if pages else None,
            "retrieval": extractor,
            "pages": [
                {"page": page_number, "text": clean_text(page_text)}
                for page_number, page_text in enumerate(pages, start=1)
            ],
        }
        blocks: list[dict[str, Any]] = []
        for page_row in source["pages"]:
            page_blocks = split_blocks(page_row["text"], page_row["page"])
            assign_sections(page_blocks)
            blocks.extend(page_blocks)
        source["blocks"] = blocks
        sources.append(source)
        inventory_files.append({
            "file": display_file,
            "bytes": path.stat().st_size if path else len(display_file.encode("utf-8")),
            "sha256": digest,
            "extractor": extractor,
            "page_count": source["page_count"],
            "characters": sum(len(page["text"]) for page in source["pages"]),
            "empty_text_layer": not any(page["text"].strip() for page in source["pages"]),
        })

        for block_index, block in enumerate(blocks, start=1):
            block_id = f"{source_id}-p{block['page']}-b{block_index}"
            block["block_id"] = block_id
            evidence.append({
                "block_id": block_id,
                "source_id": source_id,
                "file": display_file,
                "page": block["page"],
                "section": block["section"],
                "paragraph": block["paragraph"],
                "char_start": block["char_start"],
                "char_end": block["char_end"],
                "quote": block["text"],
                "ocr": False,
            })
            if block.get("is_heading"):
                continue
            for sent_start, sent_end, sentence in iter_sentences(block["text"]):
                words = normalize_ws(sentence)
                if len(words) < 25:
                    continue
                lowered = words.casefold()
                reasons = [cue for cue in CLAIM_CUES if cue in lowered]
                number = bool(re.search(
                    r"(?<![A-Za-z])(?:\d+(?:\.\d+)?%?|p\s*[<=>]\s*0?\.\d+|"
                    r"(?:19|20)\d{2})(?![A-Za-z])",
                    words,
                ))
                if not reasons and not number:
                    continue
                score = min(1.0, 0.25 * len(reasons) + (0.2 if number else 0.0))
                candidates.append({
                    "candidate_id": stable_id("cand", block_id + sentence, 12),
                    "source_id": source_id,
                    "file": display_file,
                    "page": block["page"],
                    "section": block["section"],
                    "paragraph": block["paragraph"],
                    "block_id": block_id,
                    "relative_char_start": block["char_start"] + sent_start,
                    "relative_char_end": block["char_start"] + sent_end,
                    "sentence": sentence,
                    "reason": sorted(set(reasons)),
                    "contains_number": number,
                    "score": round(score, 3),
                })

    case_id = case_identity(case, case_path)
    index = {
        "schema_version": "1.0",
        "tool_version": VERSION,
        "generated_at": now_utc(),
        "case_id": case_id,
        "case_file": str(case_path.resolve()),
        "task_text": extract_task_text(case_path),
        "output_contract": output_contract_from_case(case),
        "sources": sources,
    }
    inventory = {
        "case_id": case_id,
        "case_file": str(case_path.resolve()),
        "input_root": str(input_root.resolve()),
        "files": inventory_files,
        "source_count": len(sources),
        "readable_source_count": sum(not row["empty_text_layer"] for row in inventory_files),
        "block_count": len(evidence),
        "candidate_count": len(candidates),
        "task_text_present": bool(index["task_text"]),
        "warnings": [],
    }
    if not sources:
        inventory["warnings"].append("No supported material files or inline material were found.")
    if any(row["empty_text_layer"] for row in inventory_files):
        inventory["warnings"].append(
            "At least one material has an empty text layer; inspect rendered pages or OCR."
        )
    return index, evidence, candidates, inventory


def load_index(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("sources"), list):
        raise ValueError(f"Invalid source index: {path}")
    return value


def source_by_id(index: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for source in index["sources"]:
        if source.get("source_id") == source_id:
            return source
    return None


def block_for_offset(source: dict[str, Any], page: int, char_start: int,
                     char_end: int) -> dict[str, Any] | None:
    exact = None
    for block in source.get("blocks", []):
        if block.get("page") != page:
            continue
        if block["char_start"] <= char_start and char_end <= block["char_end"]:
            exact = block
            if not block.get("is_heading"):
                break
    return exact


def locate_quote(index: dict[str, Any], quote: str, source_id: str | None = None,
                 page_hint: int | None = None, block_hint: str | None = None) -> dict[str, Any] | None:
    sources = index["sources"]
    if source_id:
        candidate_sources = [source for source in sources if source.get("source_id") == source_id]
    else:
        candidate_sources = sources
    matches: list[dict[str, Any]] = []
    for source in candidate_sources:
        for page_row in source.get("pages", []):
            if page_hint is not None and page_row.get("page") != page_hint:
                continue
            found = find_quote(page_row.get("text", ""), quote)
            if not found:
                continue
            block = block_for_offset(
                source, page_row["page"], found["char_start"], found["char_end"]
            )
            row = {
                "source_id": source["source_id"],
                "source": source,
                "page": page_row["page"],
                "section": block.get("section") if block else None,
                "paragraph": block.get("paragraph") if block else None,
                "char_start": found["char_start"],
                "char_end": found["char_end"],
                "verbatim_quote": page_row["text"][found["char_start"]:found["char_end"]],
                "block_id": block.get("block_id") if block else None,
            }
            matches.append(row)
    if not matches:
        return None
    if block_hint:
        preferred = [row for row in matches if row.get("block_id") == block_hint]
        if preferred:
            matches = preferred
    matches.sort(key=lambda row: (len(row["verbatim_quote"]), row["page"] or 0))
    chosen = dict(matches[0])
    chosen["match_count"] = len(matches)
    return chosen


def prepare_command(args: argparse.Namespace) -> int:
    case_path = Path(args.case).resolve()
    input_root = Path(args.input).resolve()
    out_root = Path(args.out).resolve()
    work_root = Path(args.work).resolve() if args.work else (
        out_root.parent / "work" if out_root.name == "output" else out_root / "work"
    )
    if not case_path.exists():
        raise FileNotFoundError(f"Case file not found: {case_path}")
    if not input_root.exists():
        raise FileNotFoundError(f"Input directory not found: {input_root}")
    index, evidence, candidates, inventory = make_source_index(case_path, input_root)
    work_root.mkdir(parents=True, exist_ok=True)
    write_json(work_root / "source_index.json", index)
    write_jsonl(work_root / "evidence.jsonl", evidence)
    write_jsonl(work_root / "candidates.jsonl", candidates)
    write_json(work_root / "inventory.json", inventory)
    append_log(
        work_root / "run.log", "prepare", case_id=inventory["case_id"],
        sources=inventory["source_count"], blocks=inventory["block_count"],
        candidates=inventory["candidate_count"], tool_version=VERSION,
    )
    print(json.dumps({
        "status": "ok",
        "work": str(work_root),
        "sources": inventory["source_count"],
        "blocks": inventory["block_count"],
        "candidates": inventory["candidate_count"],
        "warnings": inventory["warnings"],
    }, ensure_ascii=False, indent=2))
    return 0


def search_command(args: argparse.Namespace) -> int:
    index = load_index(Path(args.index).resolve())
    query = normalize_ws(args.query)
    if not query:
        raise ValueError("Query must not be empty.")
    tokens = [token.casefold() for token in re.findall(
        r"[\w%+-]+|[\u3400-\u9fff]{1,}", query, re.UNICODE
    ) if len(token) > 1]
    phrase = query.casefold()
    results: list[dict[str, Any]] = []
    for source in index["sources"]:
        source_hay = (
            f"{source.get('title') or ''} {source.get('identifier') or ''} "
            f"{' '.join(source.get('authors') or [])}"
        ).casefold()
        title_bonus = 1.0 if phrase in source_hay else 0.0
        for block in source.get("blocks", []):
            hay = normalize_ws(block.get("text", ""))
            lower = hay.casefold()
            exact_bonus = 4.0 if phrase in lower else 0.0
            hits = sum(1 for token in tokens if token in lower)
            if not exact_bonus and not hits:
                continue
            sections = []
            for start, end, sentence in iter_sentences(block.get("text", "")):
                sent_lower = sentence.casefold()
                if phrase in sent_lower or any(token in sent_lower for token in tokens):
                    context_start = max(0, start - 180)
                    context_end = min(len(block["text"]), end + 180)
                    sections.append({
                        "char_start": block["char_start"] + start,
                        "char_end": block["char_start"] + end,
                        "quote": sentence,
                        "context": block["text"][context_start:context_end],
                    })
            score = title_bonus + exact_bonus + hits / max(len(tokens), 1)
            results.append({
                "score": round(score, 4),
                "source_id": source["source_id"],
                "file": source["file"],
                "page": block["page"],
                "section": block.get("section"),
                "paragraph": block.get("paragraph"),
                "block_id": block.get("block_id"),
                "matches": sections[:8],
                "block_text": block["text"],
            })
    results.sort(key=lambda row: (-row["score"], row["page"] or 0))
    print(json.dumps(results[:max(1, args.limit)], ensure_ascii=False, indent=2))
    return 0 if results else 2


def read_draft(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if isinstance(value, list):
        value = {"assertions": value}
    if not isinstance(value, dict):
        raise ValueError("Draft must be a JSON object (or a bare assertion array).")
    return value


def evidence_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [{"quote": value}]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"quote": str(item)} for item in value]
    return [{"quote": str(value)}]


def assertion_text(record: dict[str, Any]) -> str:
    assertion = record.get("assertion", record.get("claim", record.get("text", "")))
    if isinstance(assertion, dict):
        assertion = assertion.get("text", assertion.get("value", ""))
    return normalize_ws(str(assertion or ""))


def numbers_in(text: str) -> list[str]:
    return re.findall(
        r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:\s*%|\s*[A-Za-zμµ°]+)?",
        unicodedata.normalize("NFKC", text),
    )


def number_core(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:%|[A-Za-zμµ°]+)?", value):
        value = value.replace(",", "")
    else:
        value = value.replace(",", ".")
    return value.casefold()


def audit_quality(text: str, evidence_text: str, flags: list[str]) -> list[str]:
    flags = list(dict.fromkeys(flags))
    ev_lower = evidence_text.casefold()
    claim_lower = text.casefold()
    claim_numbers = {number_core(value) for value in numbers_in(text)}
    evidence_numbers = {number_core(value) for value in numbers_in(evidence_text)}
    if claim_numbers - evidence_numbers and "numeric_mismatch" not in flags:
        flags.append("numeric_mismatch")
    if contains_word(claim_lower, CAUSAL_WORDS) and not contains_word(ev_lower, CAUSAL_WORDS):
        if "causal_overreach" not in flags:
            flags.append("causal_overreach")
    if contains_word(claim_lower, {"all", "every", "always", "never", "所有", "全部", "总是", "从不"}):
        if not contains_word(ev_lower, {"all", "every", "always", "never", "所有", "全部", "总是", "从不"}):
            if "overbroad" not in flags:
                flags.append("overbroad")
    neg_claim = contains_word(claim_lower, NEGATIONS)
    neg_evidence = contains_word(ev_lower, NEGATIONS)
    if neg_claim != neg_evidence and "negation_risk" not in flags:
        flags.append("negation_risk")
    if len(re.findall(r"\b(?:and|whereas|while)\b|[；;]", claim_lower)) >= 2:
        if "compound" not in flags:
            flags.append("compound")
    return flags


def make_source_ref(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "file": source.get("file"),
        "title": source.get("title"),
        "authors": source.get("authors") or [],
        "year": source.get("year"),
        "version": source.get("version"),
        "identifier": source.get("identifier"),
        "sha256": source.get("sha256"),
        "page_count": source.get("page_count"),
        "retrieval": source.get("retrieval"),
    }


def value_for_contract_key(key: str, draft: dict[str, Any], result: dict[str, Any]) -> Any:
    if key in result:
        return result[key]
    task = draft.get("task_output")
    if isinstance(task, dict) and key in task:
        return task[key]
    if key in draft:
        return draft[key]
    aliases = {
        "answer": draft.get("answer"),
        "response": draft.get("answer"),
        "claims": result.get("assertions"),
        "nanopublications": result.get("assertions"),
        "translation": draft.get("translation"),
        "summary": draft.get("summary"),
    }
    return aliases.get(key)


def finalize_command(args: argparse.Namespace) -> int:
    case_path = Path(args.case).resolve()
    draft_path = Path(args.draft).resolve()
    index_path = Path(args.index).resolve()
    out_root = Path(args.out).resolve()
    case = read_json(case_path)
    draft = read_draft(draft_path)
    index = load_index(index_path)
    case_id = case_identity(case, case_path)
    errors: list[str] = []
    warnings: list[str] = []
    uncertainties: list[dict[str, Any]] = []

    raw_assertions = draft.get("assertions", draft.get("claims", []))
    if not isinstance(raw_assertions, list):
        raise ValueError("draft.assertions must be an array")
    records: list[dict[str, Any]] = []
    seen_claims: dict[str, str] = {}
    used_source_ids: set[str] = set()

    for input_index, raw_record in enumerate(raw_assertions, start=1):
        if not isinstance(raw_record, dict):
            errors.append(f"assertion[{input_index}] must be an object")
            continue
        text = assertion_text(raw_record)
        if not text:
            errors.append(f"assertion[{input_index}] has no assertion text")
            continue
        key = norm_key(text)
        if key in seen_claims:
            warnings.append(
                f"assertion[{input_index}] duplicates {seen_claims[key]}; duplicate was not emitted"
            )
            uncertainties.append({
                "code": "DUPLICATE_ASSERTION",
                "message": f"Assertion {input_index} duplicates {seen_claims[key]}.",
                "handoff": "Merge the records or remove the duplicate.",
            })
            continue
        seen_claims[key] = f"A{len(records) + 1:03d}"

        raw_evidence = evidence_items(raw_record.get("evidence"))
        if not raw_evidence:
            errors.append(f"assertion[{input_index}] has no evidence")
            uncertainties.append({
                "code": "EVIDENCE_MISSING",
                "message": f"No evidence was supplied for assertion {input_index}.",
                "handoff": "Add a verbatim supporting span or omit the assertion.",
            })
            continue
        located_evidence: list[dict[str, Any]] = []
        evidence_text_parts: list[str] = []
        for evidence_index, raw_item in enumerate(raw_evidence, start=1):
            quote = normalize_ws(str(
                raw_item.get("quote", raw_item.get("text", raw_item.get("span", ""))) or ""
            ))
            if not quote:
                errors.append(
                    f"assertion[{input_index}] evidence[{evidence_index}] has no quote"
                )
                continue
            source_id = raw_item.get("source_id")
            page_hint = raw_item.get("page")
            if page_hint is not None:
                try:
                    page_hint = int(page_hint)
                except Exception:
                    page_hint = None
            block_hint = raw_item.get("block_id")
            located = locate_quote(index, quote, source_id, page_hint, block_hint)
            if located is None:
                errors.append(
                    f"assertion[{input_index}] evidence[{evidence_index}] quote was not found verbatim"
                )
                uncertainties.append({
                    "code": "EVIDENCE_QUOTE_NOT_FOUND",
                    "message": (
                        f"Evidence quote for assertion {input_index} was not found in the "
                        "indexed source text."
                    ),
                    "handoff": (
                        "Copy the exact source sentence after checking page breaks, ligatures, "
                        "and OCR."
                    ),
                })
                continue
            relation = str(raw_item.get("relation", "supports")).casefold()
            if relation not in EVIDENCE_RELATIONS:
                errors.append(
                    f"assertion[{input_index}] evidence[{evidence_index}] invalid relation: {relation}"
                )
                relation = "supports"
            evidence_type = str(raw_item.get("evidence_type", "direct")).casefold()
            if evidence_type not in EVIDENCE_TYPES:
                errors.append(
                    f"assertion[{input_index}] evidence[{evidence_index}] invalid evidence_type: "
                    f"{evidence_type}"
                )
                evidence_type = "direct"
            source = located["source"]
            used_source_ids.add(source["source_id"])
            evidence_record = {
                "quote": located["verbatim_quote"],
                "source_id": source["source_id"],
                "relation": relation,
                "evidence_type": evidence_type,
                "location": {
                    "page": located["page"],
                    "section": located["section"],
                    "paragraph": located["paragraph"],
                    "char_start": located["char_start"],
                    "char_end": located["char_end"],
                    "visual_anchor": raw_item.get("visual_anchor"),
                },
            }
            if raw_item.get("note"):
                evidence_record["note"] = str(raw_item["note"])
            located_evidence.append(evidence_record)
            evidence_text_parts.append(located["verbatim_quote"])
            if located.get("match_count", 1) > 1:
                warnings.append(
                    f"assertion[{input_index}] evidence[{evidence_index}] occurs in multiple "
                    "locations; verify that the selected page and section support the intended "
                    "context"
                )
                uncertainties.append({
                    "code": "EVIDENCE_LOCATION_AMBIGUOUS",
                    "message": (
                        f"The quoted text for assertion {input_index} occurs "
                        f"{located['match_count']} times."
                    ),
                    "handoff": "Add the source_id, page and block_id for the intended occurrence.",
                })
            sentence_count = len(re.findall(r"[.!?。！？](?=\s|$)", located["verbatim_quote"]))
            if len(located["verbatim_quote"]) > 1200 or sentence_count > 4:
                warnings.append(
                    f"assertion[{input_index}] evidence[{evidence_index}] is a large span; "
                    "prefer the smallest sufficient quote"
                )
                uncertainties.append({
                    "code": "EVIDENCE_SPAN_REVIEW",
                    "message": (
                        f"Evidence for assertion {input_index} spans more than four sentences "
                        "or 1,200 characters."
                    ),
                    "handoff": "Trim to the shortest contiguous passage that supports the claim.",
                })

        if not located_evidence:
            continue
        source = source_by_id(index, located_evidence[0]["source_id"])
        if source is None:
            errors.append(f"assertion[{input_index}] references an unknown source")
            continue
        raw_assertion_obj = raw_record.get("assertion")
        language = (
            raw_assertion_obj.get("language")
            if isinstance(raw_assertion_obj, dict) and raw_assertion_obj.get("language")
            else raw_record.get("language")
            or detect_language(text)
        )
        raw_flags = raw_record.get("quality_flags", raw_record.get("flags", []))
        if isinstance(raw_flags, str):
            raw_flags = [raw_flags]
        if not isinstance(raw_flags, list):
            raw_flags = []
        flags = [
            str(flag) for flag in raw_flags
            if str(flag) in QUALITY_FLAGS
        ]
        unknown_flags = [str(flag) for flag in raw_flags if str(flag) not in QUALITY_FLAGS]
        if unknown_flags:
            warnings.append(
                f"assertion[{input_index}] ignored non-controlled flags: {', '.join(unknown_flags)}"
            )
        flags = audit_quality(text, " ".join(evidence_text_parts), flags)
        confidence = raw_record.get("confidence", 0.8)
        if isinstance(confidence, (int, float)):
            confidence_obj = {
                "score": max(0.0, min(1.0, float(confidence))),
                "reason": "Draft confidence retained; evidence location was verified.",
            }
        elif isinstance(confidence, dict):
            try:
                score = max(0.0, min(1.0, float(confidence.get("score", 0.8))))
            except Exception:
                score = 0.8
            confidence_obj = {
                "score": score,
                "reason": str(confidence.get("reason") or "Evidence location was verified."),
            }
        else:
            confidence_obj = {
                "score": 0.8,
                "reason": "Evidence location was verified; no confidence explanation was supplied.",
            }
        assertion_id = f"A{len(records) + 1:03d}"
        np_id = raw_record.get("np_id") or (
            "urn:nanopub:" + stable_id(
                case_id, assertion_id + "\n" + text + "\n" + source["sha256"], 32
            ).split("-", 1)[1]
        )
        scope = raw_record.get("scope", {})
        if not isinstance(scope, dict):
            scope = {"raw": scope}
        record = {
            "assertion_id": assertion_id,
            "np_id": np_id,
            "assertion": {"text": text, "language": str(language)},
            "subject": str(raw_record.get("subject", "") or ""),
            "relation": str(raw_record.get("relation", "") or ""),
            "relation_type": infer_relation_type(
                text,
                str(raw_record.get("relation", "") or ""),
                raw_record.get("relation_type"),
            ),
            "object": str(raw_record.get("object", "") or ""),
            "scope": scope,
            "evidence": located_evidence,
            "provenance": {
                "source_id": source["source_id"],
                "file": source["file"],
                "identifier": source["identifier"],
                "title": source["title"],
                "authors": source.get("authors") or [],
                "year": source.get("year"),
                "version": source.get("version"),
                "sha256": source["sha256"],
                "sources": [
                    make_source_ref(linked_source)
                    for linked_source in (
                        source_by_id(index, evidence["source_id"])
                        for evidence in located_evidence
                    )
                    if linked_source is not None
                ],
            },
            "confidence": confidence_obj,
            "quality_flags": flags,
        }
        missing_triplet = [
            key for key in ("subject", "relation", "object")
            if not normalize_ws(record[key])
        ]
        if missing_triplet:
            warnings.append(
                f"{assertion_id} has an incomplete subject-relation-object triplet: "
                f"{', '.join(missing_triplet)}"
            )
            uncertainties.append({
                "code": "TRIPLET_INCOMPLETE",
                "message": (
                    f"{assertion_id} does not populate: {', '.join(missing_triplet)}."
                ),
                "handoff": (
                    "Populate the structured triple explicitly, or retain the assertion text "
                    "and mark the unavailable element as uncertain."
                ),
            })
        if flags:
            warnings.append(
                f"{assertion_id} has quality flags: {', '.join(flags)}"
            )
        if "compound" in flags:
            uncertainties.append({
                "code": "ATOMICITY_REVIEW",
                "message": f"{assertion_id} may still contain multiple propositions.",
                "handoff": "Split independent propositions and preserve shared scope.",
            })
        if "numeric_mismatch" in flags:
            errors.append(f"{assertion_id} contains a numeric value absent from its evidence")
        if "causal_overreach" in flags:
            uncertainties.append({
                "code": "CAUSAL_OVERREACH",
                "message": f"{assertion_id} uses causal language without matching evidence.",
                "handoff": "Use association language or add direct causal evidence.",
            })
        if "overbroad" in flags:
            uncertainties.append({
                "code": "SCOPE_OVERBROAD",
                "message": f"{assertion_id} uses universal scope not present in its evidence.",
                "handoff": "Add the sampled population/setting or remove the universal quantifier.",
            })
        if "negation_risk" in flags:
            uncertainties.append({
                "code": "POLARITY_RISK",
                "message": f"{assertion_id} may reverse the source's negation or effect direction.",
                "handoff": "Check the quote, including signs, comparators and negated verbs.",
            })
        if "figure_only" in flags and not any(
            evidence.get("location", {}).get("visual_anchor")
            for evidence in located_evidence
        ):
            uncertainties.append({
                "code": "VISUAL_ANCHOR_MISSING",
                "message": f"{assertion_id} is marked visual but has no panel/row anchor.",
                "handoff": "Name the figure panel or table row and retain a rendered-page check.",
            })
        records.append(record)

    draft_uncertainties = draft.get("uncertainties", [])
    if isinstance(draft_uncertainties, list):
        for item in draft_uncertainties:
            if isinstance(item, str):
                uncertainties.append({
                    "code": "AUTHOR_DECLARED",
                    "message": item,
                    "handoff": None,
                })
            elif isinstance(item, dict):
                uncertainties.append({
                    "code": str(item.get("code", "AUTHOR_DECLARED")),
                    "message": str(item.get("message", "")),
                    "handoff": item.get("handoff"),
                })
    uncertainties = [
        item for index_item, item in enumerate(uncertainties)
        if isinstance(item, dict)
        and not any(
            prior.get("code") == item.get("code")
            and prior.get("message") == item.get("message")
            for prior in uncertainties[:index_item]
        )
    ]

    if not records and raw_assertions:
        errors.append("No assertion had a verifiable evidence span.")
    if not index["sources"]:
        errors.append("No readable source material was indexed.")

    status = str(draft.get("status", "success")).casefold()
    if status not in STATUSES:
        warnings.append(f"Invalid draft status {status!r}; inferred status was used.")
        status = "partial"
    if errors and status == "success":
        status = "partial"
    if not records and index["sources"]:
        status = "unable"
    if uncertainties and status == "success" and any(
        item.get("code") in {
            "EVIDENCE_QUOTE_NOT_FOUND", "EVIDENCE_MISSING", "CAUSAL_OVERREACH",
            "ATOMICITY_REVIEW", "DUPLICATE_ASSERTION", "EVIDENCE_SPAN_REVIEW",
            "TRIPLET_INCOMPLETE", "SCOPE_OVERBROAD", "POLARITY_RISK",
            "VISUAL_ANCHOR_MISSING",
        }
        for item in uncertainties
    ):
        status = "partial"

    used_sources = [
        make_source_ref(source) for source in index["sources"]
        if source["source_id"] in used_source_ids
    ]
    if not used_sources:
        used_sources = [make_source_ref(source) for source in index["sources"]]
    task_output = draft.get("task_output")
    if task_output is None:
        task_output = {}
        for key in ("answer", "translation", "summary", "structured_output"):
            if key in draft:
                task_output[key] = draft[key]
    change_log: list[dict[str, Any]] = []
    draft_changes = draft.get("change_log", [])
    if isinstance(draft_changes, list):
        for item in draft_changes:
            if isinstance(item, dict):
                change_log.append({
                    "change_id": f"C{len(change_log) + 1:03d}",
                    "action": str(item.get("action", "author_revision")),
                    "detail": str(item.get("detail", item.get("message", ""))),
                    "timestamp": str(item.get("timestamp", now_utc())),
                })
            elif isinstance(item, str):
                change_log.append({
                    "change_id": f"C{len(change_log) + 1:03d}",
                    "action": "author_revision",
                    "detail": item,
                    "timestamp": now_utc(),
                })
    change_log.append({
        "change_id": f"C{len(change_log) + 1:03d}",
        "action": "evidence_locations_verified",
        "detail": (
            "Evidence quotes were matched against the indexed source text and exact "
            "page/paragraph/character locations were derived; quoted source text was "
            "not rewritten."
        ),
        "timestamp": now_utc(),
    })
    result: dict[str, Any] = {
        "case_id": case_id,
        "status": status,
        "task_output": task_output,
        "assertions": records,
        "sources": used_sources,
        "uncertainties": uncertainties,
        "change_log": change_log,
        "validation": {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
        },
        "generated_at": now_utc(),
        "generator": {
            "name": "nanopublication-extractor",
            "version": VERSION,
            "source_index": str(index_path),
        },
        "case_contract": {
            "output_contract": output_contract_from_case(case),
            "case_file": str(case_path),
        },
    }
    output_contract = output_contract_from_case(case)
    if isinstance(output_contract, str):
        try:
            output_contract = json.loads(output_contract)
        except Exception:
            output_contract = None
    if isinstance(output_contract, dict):
        for key in output_contract:
            value = value_for_contract_key(str(key), draft, result)
            if value is None and isinstance(task_output, dict):
                value = task_output.get(str(key))
            result[str(key)] = value
    elif isinstance(output_contract, list):
        for key in output_contract:
            if isinstance(key, str):
                result[key] = value_for_contract_key(key, draft, result)
    for key in ("answer", "translation", "summary", "structured_output"):
        if key in draft and key not in result:
            result[key] = draft[key]

    out_root.mkdir(parents=True, exist_ok=True)
    write_json(out_root / "result.json", result)
    write_jsonl(out_root / "assertions.jsonl", records)
    write_jsonl(out_root / "sources.jsonl", used_sources)
    write_json(out_root / "evidence_audit.json", {
        "case_id": case_id,
        "assertions": [
            {
                "assertion_id": record["assertion_id"],
                "np_id": record["np_id"],
                "claim": record["assertion"]["text"],
                "evidence_count": len(record["evidence"]),
                "locations": [
                    {
                        "source_id": evidence["source_id"],
                        "page": evidence["location"]["page"],
                        "section": evidence["location"]["section"],
                        "char_start": evidence["location"]["char_start"],
                        "char_end": evidence["location"]["char_end"],
                    }
                    for evidence in record["evidence"]
                ],
                "quality_flags": record["quality_flags"],
            }
            for record in records
        ],
        "validation": result["validation"],
    })
    append_log(
        out_root / "run.log", "finalize", case_id=case_id, status=status,
        assertions=len(records), valid=not errors, errors=len(errors),
    )
    print(json.dumps({
        "status": status,
        "case_id": case_id,
        "assertions": len(records),
        "valid": not errors,
        "errors": len(errors),
        "warnings": len(warnings),
        "result": str(out_root / "result.json"),
    }, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def validate_result_value(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("case_id", "status", "assertions", "sources", "uncertainties",
                "change_log", "validation"):
        if key not in result:
            errors.append(f"Missing top-level field: {key}")
    if result.get("status") not in STATUSES:
        errors.append(f"Invalid status: {result.get('status')!r}")
    assertions = result.get("assertions")
    if not isinstance(assertions, list):
        errors.append("assertions must be an array")
        assertions = []
    if not assertions and result.get("status") == "success":
        errors.append("status=success requires at least one assertion")
    seen_ids: set[str] = set()
    seen_np: set[str] = set()
    for index, record in enumerate(assertions, start=1):
        prefix = f"assertions[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        assertion_id = record.get("assertion_id")
        if not isinstance(assertion_id, str) or not assertion_id:
            errors.append(f"{prefix}.assertion_id is required")
        elif assertion_id in seen_ids:
            errors.append(f"Duplicate assertion_id: {assertion_id}")
        else:
            seen_ids.add(assertion_id)
        np_id = record.get("np_id")
        if not isinstance(np_id, str) or not np_id:
            errors.append(f"{prefix}.np_id is required")
        elif np_id in seen_np:
            errors.append(f"Duplicate np_id: {np_id}")
        else:
            seen_np.add(np_id)
        assertion = record.get("assertion")
        if not isinstance(assertion, dict) or not normalize_ws(str(assertion.get("text", ""))):
            errors.append(f"{prefix}.assertion.text is required")
        for key in ("subject", "relation", "relation_type", "object", "scope", "provenance",
                    "confidence", "quality_flags"):
            if key not in record:
                errors.append(f"{prefix}.{key} is required")
        if record.get("relation_type") not in RELATION_TYPES:
            errors.append(f"{prefix}.relation_type is invalid")
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{prefix}.evidence must be a non-empty array")
            continue
        supports = False
        for evidence_index, item in enumerate(evidence, start=1):
            ep = f"{prefix}.evidence[{evidence_index}]"
            if not isinstance(item, dict):
                errors.append(f"{ep} must be an object")
                continue
            if not normalize_ws(str(item.get("quote", ""))):
                errors.append(f"{ep}.quote is required")
            if item.get("relation") not in EVIDENCE_RELATIONS:
                errors.append(f"{ep}.relation is invalid")
            if item.get("evidence_type") not in EVIDENCE_TYPES:
                errors.append(f"{ep}.evidence_type is invalid")
            if item.get("relation") in {"supports", "qualifies", "contextualizes"}:
                supports = True
            location = item.get("location")
            if not isinstance(location, dict):
                errors.append(f"{ep}.location is required")
                continue
            start = location.get("char_start")
            end = location.get("char_end")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                errors.append(f"{ep}.location has invalid character offsets")
            if location.get("page") is not None and not isinstance(location.get("page"), int):
                errors.append(f"{ep}.location.page must be an integer or null")
        if not supports:
            warnings.append(f"{prefix} has no non-refuting evidence")
        confidence = record.get("confidence")
        if not isinstance(confidence, dict):
            errors.append(f"{prefix}.confidence must be an object")
        else:
            score = confidence.get("score")
            if not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
                errors.append(f"{prefix}.confidence.score must be in [0, 1]")
            if not normalize_ws(str(confidence.get("reason", ""))):
                errors.append(f"{prefix}.confidence.reason is required")
        flags = record.get("quality_flags")
        if not isinstance(flags, list):
            errors.append(f"{prefix}.quality_flags must be an array")
        else:
            unknown = sorted(set(map(str, flags)) - QUALITY_FLAGS)
            if unknown:
                warnings.append(f"{prefix} has non-controlled flags: {', '.join(unknown)}")
    sources = result.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be an array")
        sources = []
    source_ids = set()
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"sources[{index}].source_id is required")
        else:
            source_ids.add(source_id)
    for index, record in enumerate(assertions, start=1):
        if not isinstance(record, dict):
            continue
        for evidence in record.get("evidence") or []:
            if isinstance(evidence, dict) and evidence.get("source_id") not in source_ids:
                errors.append(
                    f"assertions[{index}] references source not listed in sources: "
                    f"{evidence.get('source_id')}"
                )
    uncertainties = result.get("uncertainties")
    if not isinstance(uncertainties, list):
        errors.append("uncertainties must be an array")
    else:
        for index, item in enumerate(uncertainties, start=1):
            if not isinstance(item, dict):
                errors.append(f"uncertainties[{index}] must be an object")
                continue
            for key in ("code", "message", "handoff"):
                if key not in item:
                    errors.append(f"uncertainties[{index}].{key} is required")
    change_log = result.get("change_log")
    if not isinstance(change_log, list):
        errors.append("change_log must be an array")
    else:
        for index, item in enumerate(change_log, start=1):
            if not isinstance(item, dict):
                errors.append(f"change_log[{index}] must be an object")
                continue
            for key in ("change_id", "action", "detail", "timestamp"):
                if not item.get(key):
                    errors.append(f"change_log[{index}].{key} is required")
    validation = result.get("validation")
    if not isinstance(validation, dict):
        errors.append("validation must be an object")
    else:
        for key in ("valid", "errors", "warnings"):
            if key not in validation:
                errors.append(f"validation.{key} is required")
    return errors, warnings


def validate_command(args: argparse.Namespace) -> int:
    path = Path(args.result).resolve()
    result = read_json(path)
    if not isinstance(result, dict):
        raise ValueError("result.json must contain an object")
    errors, warnings = validate_result_value(result)
    summary = {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "status": result.get("status"),
        "assertions": len(result.get("assertions", []))
        if isinstance(result.get("assertions"), list) else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def inspect_command(args: argparse.Namespace) -> int:
    index = load_index(Path(args.index).resolve())
    rows = []
    for source in index["sources"]:
        rows.append({
            "source_id": source["source_id"],
            "file": source["file"],
            "title": source["title"],
            "authors": source.get("authors"),
            "year": source.get("year"),
            "identifier": source.get("identifier"),
            "retrieval": source.get("retrieval"),
            "page_count": source.get("page_count"),
            "characters": sum(len(page.get("text", "")) for page in source.get("pages", [])),
            "block_count": len(source.get("blocks", [])),
        })
    print(json.dumps({
        "case_id": index.get("case_id"),
        "task_text": index.get("task_text", "")[:2000],
        "output_contract": index.get("output_contract"),
        "sources": rows,
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index scientific material and verify nanopublication evidence."
    )
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Extract source pages and evidence blocks.")
    prepare.add_argument("--case", default="/input/case.json")
    prepare.add_argument("--input", default="/input")
    prepare.add_argument("--out", default="/app/output")
    prepare.add_argument("--work", default=None)
    prepare.set_defaults(handler=prepare_command)

    inspect = subparsers.add_parser("inspect", help="Summarise the source index.")
    inspect.add_argument("--index", required=True)
    inspect.set_defaults(handler=inspect_command)

    search = subparsers.add_parser("search", help="Search source blocks and return exact sentences.")
    search.add_argument("--index", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=8)
    search.set_defaults(handler=search_command)

    finalize = subparsers.add_parser("finalize", help="Verify draft claims and write result.json.")
    finalize.add_argument("--case", default="/input/case.json")
    finalize.add_argument("--draft", required=True)
    finalize.add_argument("--index", required=True)
    finalize.add_argument("--out", default="/app/output")
    finalize.set_defaults(handler=finalize_command)

    validate = subparsers.add_parser("validate", help="Validate the final result envelope.")
    validate.add_argument("--result", default="/app/output/result.json")
    validate.set_defaults(handler=validate_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
