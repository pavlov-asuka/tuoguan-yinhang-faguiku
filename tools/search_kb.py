from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "03_元数据台账" / "search.db"

EXCLUDED_STATUSES = ("历史失效",)
EXCLUDED_RECORD_ROLES = ("官方入口",)


def query_terms(raw_query: str) -> list[str]:
    return [token for token in raw_query.split() if token.upper() not in {"AND", "OR", "NOT"}]


def match_query(raw_query: str) -> str:
    parts: list[str] = []
    has_boolean = any(token.upper() in {"AND", "OR", "NOT"} for token in raw_query.split())
    for token in raw_query.split():
        upper = token.upper()
        if upper in {"AND", "OR", "NOT"}:
            parts.append(upper)
            continue
        escaped = token.replace('"', '""')
        parts.append(f'"{escaped}"')
    return " ".join(parts) if has_boolean else " OR ".join(parts)


def snippet(text: str, width: int = 180) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def priority_rank_expr() -> str:
    return """
        CASE rules.priority
            WHEN 'P0' THEN 0
            WHEN 'P1' THEN 1
            WHEN 'P2' THEN 2
            WHEN 'P3' THEN 3
            ELSE 9
        END
    """


def status_rank_expr() -> str:
    return """
        CASE rules.current_status
            WHEN '现行有效' THEN 0
            WHEN '待核验' THEN 1
            WHEN '待扩展' THEN 2
            WHEN '不适用' THEN 4
            WHEN '历史失效' THEN 5
            ELSE 9
        END
    """


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def search(args: argparse.Namespace) -> list[sqlite3.Row]:
    if not INDEX_PATH.is_file():
        raise SystemExit("未找到 03_元数据台账/search.db，请先运行：python tools/build_search_index.py")

    con = sqlite3.connect(INDEX_PATH)
    con.row_factory = sqlite3.Row

    terms = query_terms(args.query)
    term_score_expr = "0"
    score_params: list[object] = []
    if terms:
        term_score_parts = []
        for term in terms:
            term_score_parts.append(
                """
                (
                    CASE WHEN instr(rules.title || rules.business_tags, ?) > 0 THEN 2 ELSE 0 END
                    + CASE WHEN instr(chunks.text, ?) > 0 THEN 1 ELSE 0 END
                )
                """
            )
            score_params.extend([term, term])
        term_score_expr = " + ".join(term_score_parts)

    where = ["chunk_fts MATCH ?"]
    params: list[object] = score_params + [match_query(args.query)]

    if args.status:
        placeholders = ", ".join("?" for _ in args.status)
        where.append(f"rules.current_status IN ({placeholders})")
        params.extend(args.status)
    elif not args.include_aux:
        placeholders = ", ".join("?" for _ in EXCLUDED_STATUSES)
        where.append(f"rules.current_status NOT IN ({placeholders})")
        params.extend(EXCLUDED_STATUSES)
        placeholders = ", ".join("?" for _ in EXCLUDED_RECORD_ROLES)
        where.append(f"COALESCE(rules.record_role, '') NOT IN ({placeholders})")
        params.extend(EXCLUDED_RECORD_ROLES)

    def add_like_filter(column: str, values: list[str] | None) -> None:
        if not values:
            return
        parts = []
        for value in values:
            parts.append(f"{column} LIKE ?")
            params.append(f"%{value}%")
        where.append("(" + " OR ".join(parts) + ")")

    add_like_filter("rules.business_tags", args.tag)
    add_like_filter("rules.category", args.category)
    add_like_filter("rules.issuer", args.issuer)
    add_like_filter("rules.title", args.title)
    add_like_filter("rules.product_tags", args.product)
    add_like_filter("rules.business_line_tags", args.line)
    add_like_filter("rules.market_tags", args.market)
    add_like_filter("rules.catalog_paths", args.catalog)
    add_like_filter("rules.record_role", args.role)
    add_like_filter("rules.ingest_status", args.ingest_status)
    if args.rule_id:
        placeholders = ", ".join("?" for _ in args.rule_id)
        where.append(f"rules.rule_id IN ({placeholders})")
        params.extend(args.rule_id)

    sql = f"""
        SELECT
            rules.rule_id,
            rules.title,
            rules.current_status,
            rules.record_role,
            rules.ingest_status,
            rules.priority,
            rules.product_tags,
            rules.business_line_tags,
            rules.market_tags,
            rules.business_tags,
            rules.source_urls,
            documents.text_path,
            chunks.article_no,
            chunks.section_title,
            chunks.line_start,
            chunks.line_end,
            chunks.text,
            {term_score_expr} AS term_score,
            bm25(chunk_fts) AS score
        FROM chunk_fts
        JOIN chunks ON chunks.chunk_id = chunk_fts.rowid
        JOIN rules ON rules.rule_id = chunks.rule_id
        JOIN documents ON documents.doc_id = chunks.doc_id
        WHERE {" AND ".join(where)}
        ORDER BY {status_rank_expr()}, {priority_rank_expr()}, term_score DESC, score
        LIMIT ?
    """
    params.append(args.limit)
    rows = list(con.execute(sql, params))
    con.close()
    return rows


def main() -> None:
    configure_output()
    parser = argparse.ArgumentParser(description="Search the local regulatory knowledge-base SQLite FTS index.")
    parser.add_argument("query", help="Search keywords. Space-separated terms use OR by default; OR/AND/NOT are supported.")
    parser.add_argument("--status", action="append", help="Filter by current_status. Can be repeated.")
    parser.add_argument("--tag", action="append", help="Filter by business_tags. Can be repeated.")
    parser.add_argument("--category", action="append", help="Filter by category. Can be repeated.")
    parser.add_argument("--issuer", action="append", help="Filter by issuer. Can be repeated.")
    parser.add_argument("--title", action="append", help="Filter by title. Can be repeated.")
    parser.add_argument("--rule-id", action="append", help="Filter by rule id. Can be repeated.")
    parser.add_argument("--product", action="append", help="Filter by product_tags. Can be repeated.")
    parser.add_argument("--line", action="append", help="Filter by business_line_tags. Can be repeated.")
    parser.add_argument("--market", action="append", help="Filter by market_tags. Can be repeated.")
    parser.add_argument("--catalog", action="append", help="Filter by catalog_paths. Can be repeated.")
    parser.add_argument("--role", action="append", help="Filter by record_role. Can be repeated.")
    parser.add_argument("--ingest-status", action="append", help="Filter by ingest_status. Can be repeated.")
    parser.add_argument(
        "--include-excluded",
        "--include-aux",
        dest="include_aux",
        action="store_true",
        help="Include 历史失效 and 官方入口 results.",
    )
    parser.add_argument("--limit", type=int, default=8, help="Maximum number of results.")
    args = parser.parse_args()

    rows = search(args)
    if not rows:
        print("未命中。可以尝试减少关键词，或使用 --include-excluded 查看官方入口/历史规则。")
        return

    for idx, row in enumerate(rows, start=1):
        heading = row["article_no"] or row["section_title"] or "片段"
        print(f"[{idx}] {row['rule_id']} {row['title']}")
        print(
            f"状态：{row['current_status']}｜角色：{row['record_role']}｜"
            f"入库：{row['ingest_status']}｜优先级：{row['priority']}｜命中：{heading}"
        )
        if row["business_tags"]:
            print(f"标签：{row['business_tags']}")
        scoped_tags = "｜".join(part for part in [row["product_tags"], row["business_line_tags"], row["market_tags"]] if part)
        if scoped_tags:
            print(f"范围：{scoped_tags}")
        if row["text_path"]:
            location = f"{row['text_path']}:{row['line_start']}"
            if row["line_end"] != row["line_start"]:
                location += f"-{row['line_end']}"
            print(f"本地文本：{location}")
        else:
            print("本地文本：未入库正文（元数据命中）")
        if row["source_urls"]:
            print(f"官方来源：{row['source_urls']}")
        print(f"片段：{snippet(row['text'])}")
        print()


if __name__ == "__main__":
    main()
