from __future__ import annotations

import argparse
import bisect
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
META_ROOT = ROOT / "03_元数据台账"
INDEX_PATH = META_ROOT / "search.db"
RULES_INDEX_PATH = META_ROOT / "rules_index.json"

MAX_CHUNK_CHARS = 1400
CHUNK_OVERLAP_CHARS = 180
METADATA_ONLY_RECORD_ROLES = {"官方入口", "重要参考规则", "规则组索引"}

ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千万零〇两\d]+条")
SECTION_RE = re.compile(r"第[一二三四五六七八九十百千万零〇两\d]+[章节]")


def split_field(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def metadata_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("title", ""),
        row.get("category", ""),
        row.get("layer", ""),
        row.get("doc_type", ""),
        row.get("issuer", ""),
        row.get("rule_no", ""),
        row.get("product_tags", ""),
        row.get("business_line_tags", ""),
        row.get("market_tags", ""),
        row.get("business_tags", ""),
        row.get("catalog_paths", ""),
        row.get("key_obligations", ""),
        row.get("notes", ""),
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def relpath(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def clean_line(line: str) -> str:
    return re.sub(r"\s+", "", line.strip())


def line_map(lines: list[str]) -> tuple[str, list[int], list[int]]:
    parts: list[str] = []
    starts: list[int] = []
    line_numbers: list[int] = []
    pos = 0
    for line_no, line in enumerate(lines, start=1):
        text = clean_line(line)
        if not text:
            continue
        starts.append(pos)
        line_numbers.append(line_no)
        parts.append(text)
        pos += len(text)
    return "".join(parts), starts, line_numbers


def line_for_pos(pos: int, starts: list[int], line_numbers: list[int]) -> int:
    if not starts:
        return 1
    idx = bisect.bisect_right(starts, max(pos, 0)) - 1
    if idx < 0:
        idx = 0
    return line_numbers[idx]


def latest_section(pos: int, markers: list[tuple[int, str]]) -> str:
    if not markers:
        return ""
    marker_positions = [item[0] for item in markers]
    idx = bisect.bisect_right(marker_positions, pos) - 1
    return markers[idx][1] if idx >= 0 else ""


def fixed_ranges(start: int, end: int) -> Iterable[tuple[int, int]]:
    cursor = start
    while cursor < end:
        next_end = min(cursor + MAX_CHUNK_CHARS, end)
        yield cursor, next_end
        if next_end == end:
            break
        cursor = max(next_end - CHUNK_OVERLAP_CHARS, cursor + 1)


def chunk_text(text: str, starts: list[int], line_numbers: list[int]) -> list[dict[str, Any]]:
    markers = [(m.start(), m.group(0)) for m in SECTION_RE.finditer(text)]
    article_matches = list(ARTICLE_RE.finditer(text))
    ranges: list[tuple[int, int, str]] = []

    if article_matches:
        first_start = article_matches[0].start()
        if first_start > 80:
            ranges.append((0, first_start, ""))
        for idx, match in enumerate(article_matches):
            start = match.start()
            end = article_matches[idx + 1].start() if idx + 1 < len(article_matches) else len(text)
            ranges.append((start, end, match.group(0)))
    else:
        ranges.append((0, len(text), ""))

    chunks: list[dict[str, Any]] = []
    for start, end, article_no in ranges:
        if end <= start:
            continue
        for sub_start, sub_end in fixed_ranges(start, end):
            body = text[sub_start:sub_end].strip()
            if not body:
                continue
            chunks.append(
                {
                    "article_no": article_no,
                    "section_title": latest_section(sub_start, markers),
                    "line_start": line_for_pos(sub_start, starts, line_numbers),
                    "line_end": line_for_pos(max(sub_end - 1, sub_start), starts, line_numbers),
                    "text": body,
                }
            )
    return chunks


def ensure_fts5_trigram(con: sqlite3.Connection) -> str:
    try:
        con.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(x, tokenize='trigram')")
        con.execute("DROP TABLE fts_probe")
        return "trigram"
    except sqlite3.Error as exc:
        raise RuntimeError("当前 Python SQLite 不支持 FTS5 trigram，无法构建中文全文索引") from exc


def create_schema(con: sqlite3.Connection) -> str:
    tokenizer = ensure_fts5_trigram(con)
    con.executescript(
        """
        CREATE TABLE rules (
            rule_id TEXT PRIMARY KEY,
            legacy_id TEXT,
            title TEXT NOT NULL,
            category TEXT,
            layer TEXT,
            doc_type TEXT,
            issuer TEXT,
            rule_no TEXT,
            publish_date TEXT,
            effective_date TEXT,
            current_status TEXT,
            record_role TEXT,
            ingest_status TEXT,
            priority TEXT,
            is_core TEXT,
            product_tags TEXT,
            business_line_tags TEXT,
            market_tags TEXT,
            catalog_paths TEXT,
            key_obligations TEXT,
            business_tags TEXT,
            source_urls TEXT,
            notes TEXT,
            errors TEXT
        );

        CREATE TABLE documents (
            doc_id INTEGER PRIMARY KEY,
            rule_id TEXT NOT NULL,
            text_path TEXT NOT NULL,
            raw_path TEXT,
            file_type TEXT,
            source_type TEXT,
            line_count INTEGER NOT NULL,
            char_count INTEGER NOT NULL,
            UNIQUE(rule_id, text_path),
            FOREIGN KEY(rule_id) REFERENCES rules(rule_id)
        );

        CREATE TABLE chunks (
            chunk_id INTEGER PRIMARY KEY,
            doc_id INTEGER NOT NULL,
            rule_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            article_no TEXT,
            section_title TEXT,
            line_start INTEGER NOT NULL,
            line_end INTEGER NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(doc_id),
            FOREIGN KEY(rule_id) REFERENCES rules(rule_id)
        );

        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            title,
            business_tags,
            text,
            tokenize='trigram'
        );

        CREATE INDEX idx_documents_rule_id ON documents(rule_id);
        CREATE INDEX idx_chunks_rule_id ON chunks(rule_id);
        CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
        """
    )
    return tokenizer


def load_rules(root: Path) -> list[dict[str, Any]]:
    path = root / RULES_INDEX_PATH.relative_to(ROOT)
    return json.loads(path.read_text(encoding="utf-8"))


def insert_rule(con: sqlite3.Connection, row: dict[str, Any]) -> None:
    con.execute(
        """
        INSERT INTO rules (
            rule_id, legacy_id, title, category, layer, doc_type, issuer, rule_no,
            publish_date, effective_date, current_status, record_role, ingest_status, priority, is_core,
            product_tags, business_line_tags, market_tags, catalog_paths,
            key_obligations, business_tags, source_urls, notes, errors
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("id", ""),
            row.get("legacy_id", ""),
            row.get("title", ""),
            row.get("category", ""),
            row.get("layer", ""),
            row.get("doc_type", ""),
            row.get("issuer", ""),
            row.get("rule_no", ""),
            row.get("publish_date", ""),
            row.get("effective_date", ""),
            row.get("current_status", ""),
            row.get("record_role", ""),
            row.get("ingest_status", ""),
            row.get("priority", ""),
            row.get("is_core", ""),
            row.get("product_tags", ""),
            row.get("business_line_tags", ""),
            row.get("market_tags", ""),
            row.get("catalog_paths", ""),
            row.get("key_obligations", ""),
            row.get("business_tags", ""),
            row.get("source_url", ""),
            row.get("notes", ""),
            row.get("errors", ""),
        ),
    )


def build_index(root: Path = ROOT, index_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    index_path = (index_path or root / INDEX_PATH.relative_to(ROOT)).resolve()
    tmp_path = index_path.with_name(index_path.name + ".tmp")
    index_path.parent.mkdir(parents=True, exist_ok=True)

    for path in [tmp_path, tmp_path.with_suffix(tmp_path.suffix + "-wal"), tmp_path.with_suffix(tmp_path.suffix + "-shm")]:
        if path.exists():
            path.unlink()

    con = sqlite3.connect(tmp_path)
    con.execute("PRAGMA foreign_keys = ON")
    tokenizer = create_schema(con)

    rules = load_rules(root)
    document_count = 0
    chunk_count = 0
    missing_texts: list[str] = []

    for row in rules:
        insert_rule(con, row)
        text_paths = split_field(row.get("text_path", ""))
        raw_paths = split_field(row.get("local_path", ""))
        file_types = split_field(row.get("file_type", ""))
        has_document = False

        for idx, text_path_value in enumerate(text_paths):
            text_path = (root / text_path_value).resolve()
            if not text_path.is_file():
                missing_texts.append(text_path_value)
                continue
            raw_path = raw_paths[idx] if idx < len(raw_paths) else ""
            file_type = file_types[idx] if idx < len(file_types) else ""
            lines = text_path.read_text(encoding="utf-8", errors="replace").splitlines()
            normalized, starts, line_numbers = line_map(lines)
            if not normalized:
                continue

            cur = con.execute(
                """
                INSERT INTO documents (
                    rule_id, text_path, raw_path, file_type, source_type, line_count, char_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("id", ""),
                    relpath(text_path, root),
                    raw_path,
                    file_type,
                    row.get("source_type", ""),
                    len(lines),
                    len(normalized),
                ),
            )
            doc_id = int(cur.lastrowid)
            document_count += 1
            has_document = True

            for chunk_index, chunk in enumerate(chunk_text(normalized, starts, line_numbers), start=1):
                cur = con.execute(
                    """
                    INSERT INTO chunks (
                        doc_id, rule_id, chunk_index, article_no, section_title,
                        line_start, line_end, text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("id", ""),
                        chunk_index,
                        chunk["article_no"],
                        chunk["section_title"],
                        chunk["line_start"],
                        chunk["line_end"],
                        chunk["text"],
                    ),
                )
                chunk_id = int(cur.lastrowid)
                con.execute(
                    "INSERT INTO chunk_fts(rowid, title, business_tags, text) VALUES (?, ?, ?, ?)",
                    (chunk_id, row.get("title", ""), row.get("business_tags", ""), chunk["text"]),
                )
                chunk_count += 1

        if not has_document and row.get("record_role") in METADATA_ONLY_RECORD_ROLES:
            text = metadata_text(row)
            if text:
                cur = con.execute(
                    """
                    INSERT INTO documents (
                        rule_id, text_path, raw_path, file_type, source_type, line_count, char_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id", ""),
                        "",
                        "",
                        "metadata",
                        "metadata",
                        0,
                        len(text),
                    ),
                )
                doc_id = int(cur.lastrowid)
                document_count += 1
                cur = con.execute(
                    """
                    INSERT INTO chunks (
                        doc_id, rule_id, chunk_index, article_no, section_title,
                        line_start, line_end, text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (doc_id, row.get("id", ""), 1, "", "元数据", 0, 0, text),
                )
                chunk_id = int(cur.lastrowid)
                con.execute(
                    "INSERT INTO chunk_fts(rowid, title, business_tags, text) VALUES (?, ?, ?, ?)",
                    (chunk_id, row.get("title", ""), row.get("business_tags", ""), text),
                )
                chunk_count += 1

    con.commit()
    con.close()

    if index_path.exists():
        index_path.unlink()
    tmp_path.replace(index_path)

    return {
        "path": relpath(index_path, root),
        "rules": len(rules),
        "documents": document_count,
        "chunks": chunk_count,
        "missing_texts": len(missing_texts),
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sqlite_version": sqlite3.sqlite_version,
        "fts_tokenizer": tokenizer,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local regulatory knowledge-base search index.")
    parser.add_argument("--root", default=str(ROOT), help="Knowledge-base root directory.")
    parser.add_argument("--index", default="", help="Optional output SQLite index path.")
    args = parser.parse_args()

    root = Path(args.root)
    index = Path(args.index) if args.index else None
    summary = build_index(root=root, index_path=index)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
