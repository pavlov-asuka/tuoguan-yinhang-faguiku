from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree
from pypdf import PdfReader

from build_search_index import build_index


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "中国商业银行托管业务条线大法规库总目录.md"
RAW_ROOT = ROOT / "01_法规原文库"
TEXT_ROOT = ROOT / "02_文本抽取库"
META_ROOT = ROOT / "03_元数据台账"
TOPIC_ROOT = ROOT / "04_托管业务专题地图"
ENTRY_ROOT = ROOT / "00_入口与索引"
UNRESOLVED_ROOT = ROOT / "99_unresolved"
ARCHIVE_ROOT = ROOT / "98_历史归档" / "2026-06-12_公募基金托管库"
ARCHIVE_MARKER = ARCHIVE_ROOT / ".archived"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

INTERNAL_KEYWORDS = (
    "内部落库位",
    "内部模板",
    "内部制度",
    "样表",
    "流程图",
    "知识运营",
    "制度模板",
)

TAG_PRODUCTS = (
    "公募基金",
    "私募基金",
    "证券期货资管",
    "银行理财",
    "信托",
    "保险资金",
    "保险资管",
    "养老金",
    "社保",
    "年金",
    "QDII",
    "QFII",
    "REITs",
    "衍生品",
    "客户资金",
)

TAG_LINES = (
    "准入",
    "前台",
    "账户保管",
    "账户",
    "保管",
    "核算估值",
    "估值",
    "核算",
    "清算交收",
    "清算",
    "交收",
    "投资监督",
    "披露报送",
    "披露",
    "报送",
    "IT数据",
    "数据",
    "合同法务",
    "合同",
    "法务",
    "风控内审",
    "风控",
    "内控",
    "审计",
    "税务",
    "反洗钱",
    "销售",
)

TAG_MARKETS = (
    "交易所",
    "银行间",
    "场外",
    "跨境",
    "港股通",
    "债券通",
    "外汇",
    "期货",
    "衍生品",
)

TITLE_ALIASES = {
    "证券投资基金法": "中华人民共和国证券投资基金法",
    "证券法": "中华人民共和国证券法",
    "商业银行法": "中华人民共和国商业银行法",
    "银行业监督管理法": "中华人民共和国银行业监督管理法",
    "信托法": "中华人民共和国信托法",
    "期货和衍生品法": "中华人民共和国期货和衍生品法",
    "中国人民银行法": "中华人民共和国中国人民银行法",
    "保险法": "中华人民共和国保险法",
    "公司法": "中华人民共和国公司法",
    "合伙企业法": "中华人民共和国合伙企业法",
    "企业破产法": "中华人民共和国企业破产法",
    "民法典": "中华人民共和国民法典",
    "电子签名法": "中华人民共和国电子签名法",
    "仲裁法": "中华人民共和国仲裁法",
    "民事诉讼法": "中华人民共和国民事诉讼法",
    "反洗钱法": "中华人民共和国反洗钱法",
    "网络安全法": "中华人民共和国网络安全法",
    "数据安全法": "中华人民共和国数据安全法",
    "个人信息保护法": "中华人民共和国个人信息保护法",
    "消费者权益保护法": "中华人民共和国消费者权益保护法",
    "密码法": "中华人民共和国密码法",
    "国家安全法": "中华人民共和国国家安全法",
    "反恐怖主义法": "中华人民共和国反恐怖主义法",
    "增值税法": "中华人民共和国增值税法",
    "企业所得税法": "中华人民共和国企业所得税法",
    "个人所得税法": "中华人民共和国个人所得税法",
    "印花税法": "中华人民共和国印花税法",
    "税收征收管理法": "中华人民共和国税收征收管理法",
}

ISSUER_BY_HINT = {
    "全国人大": "全国人民代表大会常务委员会",
    "法律": "全国人民代表大会常务委员会",
    "行政法规": "国务院",
    "司法解释": "最高人民法院",
    "证监会": "中国证监会",
    "人民银行": "中国人民银行",
    "外汇局": "国家外汇管理局",
    "财政部": "财政部",
    "税务总局": "国家税务总局",
    "交易所": "证券交易所",
    "中登": "中国证券登记结算有限责任公司",
    "基础设施": "市场基础设施",
    "自律规则": "行业自律组织",
    "自律入口": "行业自律组织",
}

FIELDS = [
    "id",
    "legacy_id",
    "priority",
    "category",
    "title",
    "layer",
    "doc_type",
    "issuer",
    "rule_no",
    "publish_date",
    "effective_date",
    "current_status",
    "is_core",
    "source_type",
    "product_tags",
    "business_line_tags",
    "market_tags",
    "business_tags",
    "catalog_paths",
    "key_obligations",
    "source_url",
    "local_path",
    "text_path",
    "file_type",
    "downloaded_count",
    "notes",
    "errors",
]


@dataclass
class CatalogItem:
    title: str
    priority: str
    doc_type: str
    body: str
    category: str
    catalog_path: str
    top_code: str
    line_no: int


@dataclass
class RuleRecord:
    key: str
    id: str = ""
    legacy_id: str = ""
    title: str = ""
    priority: str = "P2"
    category: str = ""
    layer: str = ""
    doc_type: str = ""
    issuer: str = ""
    rule_no: str = ""
    publish_date: str = ""
    effective_date: str = ""
    current_status: str = "待扩展"
    is_core: str = "否"
    source_type: str = ""
    product_tags: list[str] = field(default_factory=list)
    business_line_tags: list[str] = field(default_factory=list)
    market_tags: list[str] = field(default_factory=list)
    business_tags: list[str] = field(default_factory=list)
    catalog_paths: list[str] = field(default_factory=list)
    key_obligations: str = ""
    source_url: str = ""
    local_path: str = ""
    text_path: str = ""
    file_type: str = ""
    downloaded_count: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    legacy_row: dict[str, Any] | None = None
    first_line: int = 0


def split_field(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def join_unique(values: list[str]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return "; ".join(out)


def safe_name(value: str, max_len: int = 90) -> str:
    value = html.unescape(value)
    value = re.sub(r"[<>:\"/\\|?*\r\n\t]", "_", value)
    value = re.sub(r"\s+", "", value)
    value = value.strip(" ._")
    return value[:max_len] or "untitled"


def relpath(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def ensure_under(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    base = parent.resolve()
    if resolved != base and not resolved.is_relative_to(base):
        raise RuntimeError(f"拒绝操作工作区之外的路径：{resolved}")


def normalize_title(value: str) -> str:
    value = TITLE_ALIASES.get(value.strip(), value.strip())
    value = re.sub(r"[《》〈〉“”\"'（）()、，,。；;：:\s·—_\-/]", "", value)
    value = value.replace("中华人民共和国", "")
    return value


def canonical_title(value: str) -> str:
    value = value.strip()
    return TITLE_ALIASES.get(value, value)


def title_candidates(value: str) -> list[str]:
    title = canonical_title(value)
    candidates = [title, value]
    if title.startswith("中华人民共和国"):
        candidates.append(title.removeprefix("中华人民共和国"))
    else:
        candidates.append("中华人民共和国" + title)
    return [normalize_title(item) for item in candidates if item]


def priority_rank(value: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(value, 9)


def stronger_priority(a: str, b: str) -> str:
    return a if priority_rank(a) <= priority_rank(b) else b


def extract_title(body: str) -> str:
    quoted = re.search(r"《([^》]+)》", body)
    if quoted:
        return canonical_title(quoted.group(1).strip())
    body = re.sub(r"（[^）]*(待核验|待补齐|现行状态待核验)[^）]*）", "", body)
    body = body.strip(" ；;。")
    return canonical_title(body)


def category_from_stack(stack: dict[int, str]) -> str:
    parts: list[str] = []
    for level in [1, 2, 3]:
        if level in stack:
            parts.append(safe_name(stack[level], max_len=60))
    return "/".join(parts)


def parse_catalog() -> tuple[list[CatalogItem], dict[str, Any]]:
    lines = CATALOG_PATH.read_text(encoding="utf-8").splitlines()
    stack: dict[int, str] = {}
    top_code = ""
    items: list[CatalogItem] = []
    skipped_internal = 0

    for line_no, line in enumerate(lines, start=1):
        top = re.match(r"^# ([A-G])\. (.+)$", line)
        if top:
            top_code = top.group(1)
            stack = {1: f"{top.group(1)}_{top.group(2).strip()}"}
            continue

        heading = re.match(r"^(#{2,4})\s+(.+)$", line)
        if heading and top_code:
            level = len(heading.group(1))
            stack[level] = heading.group(2).strip()
            for stale in [k for k in stack if k > level]:
                stack.pop(stale, None)
            continue

        bullet = re.match(r"^- 【(?P<priority>P[012])｜(?P<doc_type>[^】]+)】(?P<body>.+)$", line)
        if not bullet or not top_code:
            continue

        raw = line.strip()
        second_level = stack.get(2, "")
        if second_level.startswith("G-02") or second_level.startswith("G-03"):
            skipped_internal += 1
            continue
        if any(keyword in raw for keyword in INTERNAL_KEYWORDS):
            skipped_internal += 1
            continue

        body = bullet.group("body").strip()
        title = extract_title(body)
        if not title:
            continue

        path = " > ".join(stack[level] for level in sorted(stack))
        items.append(
            CatalogItem(
                title=title,
                priority=bullet.group("priority"),
                doc_type=bullet.group("doc_type").strip(),
                body=body,
                category=category_from_stack(stack),
                catalog_path=path,
                top_code=top_code,
                line_no=line_no,
            )
        )

    summary = {
        "catalog_items": len(items),
        "skipped_internal_items": skipped_internal,
        "source": CATALOG_PATH.name,
    }
    return items, summary


def load_legacy_rows() -> list[dict[str, Any]]:
    candidates = [
        ARCHIVE_ROOT / "03_元数据台账" / "rules_index.json",
        META_ROOT / "rules_index.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return []


def legacy_maps(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        title = row.get("title", "")
        for candidate in title_candidates(title):
            by_key.setdefault(candidate, row)
    return by_key


def infer_tags(text: str, vocabulary: tuple[str, ...]) -> list[str]:
    tags = []
    for tag in vocabulary:
        if tag in text:
            normalized = {
                "保险资管": "保险资金",
                "社保": "养老金社保年金",
                "养老金": "养老金社保年金",
                "年金": "养老金社保年金",
                "账户": "账户保管",
                "保管": "账户保管",
                "估值": "核算估值",
                "核算": "核算估值",
                "清算": "清算交收",
                "交收": "清算交收",
                "披露": "披露报送",
                "报送": "披露报送",
                "数据": "IT数据",
                "合同": "合同法务",
                "法务": "合同法务",
                "风控": "风控内审",
                "内控": "风控内审",
                "审计": "风控内审",
            }.get(tag, tag)
            tags.append(normalized)
    return tags


def infer_issuer(doc_type: str, title: str) -> str:
    text = f"{doc_type} {title}"
    for hint, issuer in ISSUER_BY_HINT.items():
        if hint in text:
            return issuer
    return ""


def merge_catalog_items(items: list[CatalogItem], legacy_by_key: dict[str, dict[str, Any]]) -> list[RuleRecord]:
    records: dict[str, RuleRecord] = {}
    for item in items:
        key = normalize_title(item.title)
        record = records.get(key)
        if not record:
            record = RuleRecord(key=key)
            record.title = item.title
            record.first_line = item.line_no
            record.priority = item.priority
            record.category = item.category
            record.layer = item.doc_type
            record.doc_type = item.doc_type
            record.issuer = infer_issuer(item.doc_type, item.title)
            record.current_status = "待核验" if item.priority == "P0" else "待扩展"
            records[key] = record

        record.priority = stronger_priority(record.priority, item.priority)
        record.is_core = "是" if record.priority == "P0" else "否"
        record.category = record.category or item.category
        record.layer = join_unique([record.layer, item.doc_type])
        record.doc_type = join_unique([record.doc_type, item.doc_type])
        record.catalog_paths.append(item.catalog_path)

        tag_text = " ".join([item.title, item.doc_type, item.body, item.catalog_path])
        record.product_tags.extend(infer_tags(tag_text, TAG_PRODUCTS))
        record.business_line_tags.extend(infer_tags(tag_text, TAG_LINES))
        record.market_tags.extend(infer_tags(tag_text, TAG_MARKETS))
        record.business_tags.extend([item.doc_type, item.top_code])
        if "关于" in item.body or "职责" in item.body or "规则" in item.body:
            record.key_obligations = record.key_obligations or item.body.strip("。")

    for record in records.values():
        legacy_row = None
        for candidate in title_candidates(record.title):
            legacy_row = legacy_by_key.get(candidate)
            if legacy_row:
                break
        if legacy_row:
            record.legacy_row = legacy_row
            record.legacy_id = legacy_row.get("id", "")
            record.title = legacy_row.get("title") or record.title
            record.issuer = legacy_row.get("issuer") or record.issuer
            record.rule_no = legacy_row.get("rule_no", "")
            record.publish_date = legacy_row.get("publish_date", "")
            record.effective_date = legacy_row.get("effective_date", "")
            record.current_status = legacy_row.get("current_status") or record.current_status
            record.source_type = legacy_row.get("source_type", "")
            record.source_url = legacy_row.get("source_url", "")
            record.business_tags.extend(split_field(legacy_row.get("business_tags", "")))
            if legacy_row.get("notes"):
                record.notes.append(legacy_row["notes"])

    ordered = list(records.values())
    ordered.sort(key=lambda rec: rec.first_line)
    for idx, record in enumerate(ordered, start=1):
        record.id = f"TB{idx:03d}"
    return ordered


def archive_legacy_repository() -> None:
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_under(ARCHIVE_ROOT, ROOT)
    if ARCHIVE_MARKER.exists():
        return

    for name in ["00_入口与索引", "03_元数据台账", "04_托管业务专题地图", "99_unresolved"]:
        src = ROOT / name
        dst = ARCHIVE_ROOT / name
        if src.exists() and not dst.exists():
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    for name in ["01_法规原文库", "02_文本抽取库"]:
        src_root = ROOT / name
        dst_root = ARCHIVE_ROOT / name
        dst_root.mkdir(parents=True, exist_ok=True)
        if not src_root.exists():
            continue
        ensure_under(src_root, ROOT)
        for child in list(src_root.iterdir()):
            dst = dst_root / child.name
            if dst.exists():
                continue
            shutil.move(str(child), str(dst))

    ARCHIVE_MARKER.write_text(
        f"Archived legacy public-fund custody library at {time.strftime('%Y-%m-%d %H:%M:%S')}.\n",
        encoding="utf-8",
        newline="\n",
    )


def reset_generated_dirs() -> None:
    for path in [RAW_ROOT, TEXT_ROOT]:
        ensure_under(path, ROOT)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    for path in [META_ROOT, TOPIC_ROOT, ENTRY_ROOT, UNRESOLVED_ROOT]:
        path.mkdir(parents=True, exist_ok=True)


def ensure_category_dirs(records: list[RuleRecord]) -> None:
    for record in records:
        (RAW_ROOT / record.category).mkdir(parents=True, exist_ok=True)
        (TEXT_ROOT / record.category).mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_for_legacy_path(path_value: str) -> Path | None:
    for base in [ROOT, ARCHIVE_ROOT]:
        candidate = base / path_value
        if candidate.is_file():
            return candidate
    return None


def copy_legacy_files(record: RuleRecord) -> list[dict[str, str]]:
    if not record.legacy_row:
        return []

    raw_dir = RAW_ROOT / record.category / f"{record.id}_{safe_name(record.title)}"
    text_dir = TEXT_ROOT / record.category / f"{record.id}_{safe_name(record.title)}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, str]] = []
    raw_paths: list[str] = []
    text_paths: list[str] = []

    for path_value in split_field(record.legacy_row.get("local_path", "")):
        src = source_for_legacy_path(path_value)
        if not src:
            record.errors.append(f"旧原文不存在：{path_value}")
            continue
        dst = raw_dir / src.name
        shutil.copy2(src, dst)
        raw_paths.append(relpath(dst))
        copied.append(
            {
                "legacy_id": record.legacy_id,
                "new_id": record.id,
                "kind": "raw",
                "old_path": path_value,
                "new_path": relpath(dst),
                "sha256": sha256(dst),
            }
        )

    for path_value in split_field(record.legacy_row.get("text_path", "")):
        src = source_for_legacy_path(path_value)
        if not src:
            record.errors.append(f"旧文本不存在：{path_value}")
            continue
        dst = text_dir / src.name
        shutil.copy2(src, dst)
        text_paths.append(relpath(dst))
        copied.append(
            {
                "legacy_id": record.legacy_id,
                "new_id": record.id,
                "kind": "text",
                "old_path": path_value,
                "new_path": relpath(dst),
                "sha256": sha256(dst),
            }
        )

    for raw_path in list(raw_paths):
        raw_file = ROOT / raw_path
        if raw_file.suffix.lower() not in [".pdf", ".docx"]:
            continue
        target = text_dir / f"{raw_file.stem}.txt"
        if text_file_has_meaningful_content(target):
            continue
        regenerated = write_text_for_raw(raw_file, text_dir)
        if regenerated:
            text_paths.append(relpath(regenerated))
            copied.append(
                {
                    "legacy_id": record.legacy_id,
                    "new_id": record.id,
                    "kind": "text-regenerated",
                    "old_path": raw_path,
                    "new_path": relpath(regenerated),
                    "sha256": sha256(regenerated),
                }
            )
            record.notes.append("空文本已从原文重新抽取")

    if raw_paths or text_paths:
        record.notes.append("复用旧公募基金托管库原文/文本")
    record.local_path = join_unique(raw_paths)
    record.text_path = join_unique(text_paths)
    record.file_type = join_unique(sorted({Path(path).suffix.lower().lstrip(".") for path in raw_paths if Path(path).suffix}))
    record.downloaded_count = len(raw_paths)
    return copied


def request_bytes(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[bytes, dict[str, str]]:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=35) as resp:
        return resp.read(), dict(resp.headers)


def npc_lookup(title: str) -> dict[str, Any] | None:
    payload = {
        "searchRange": 1,
        "sxrq": [],
        "gbrq": [],
        "searchType": 1,
        "sxx": [],
        "gbrqYear": [],
        "flfgCodeId": [],
        "zdjgCodeId": [],
        "searchContent": title,
        "pageNum": 1,
        "pageSize": 10,
    }
    data, _ = request_bytes(
        "https://flk.npc.gov.cn/law-search/search/list",
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json;charset=utf-8", "Accept": "application/json"},
    )
    result = json.loads(data.decode("utf-8"))
    rows = result.get("rows") or []
    plain = lambda s: re.sub(r"<[^>]+>", "", s or "")
    for row in rows:
        if plain(row.get("title")) == title:
            return row
    return rows[0] if rows else None


def npc_detail(bbbs: str) -> dict[str, Any] | None:
    url = "https://flk.npc.gov.cn/law-search/search/flfgDetails?" + urllib.parse.urlencode({"bbbs": bbbs})
    data, _ = request_bytes(url, headers={"Accept": "application/json"})
    return json.loads(data.decode("utf-8")).get("data")


def extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        return f"[PDF文本抽取失败] {exc}"


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        doc = etree.fromstring(xml)
        texts = doc.xpath("//*[local-name()='t']/text()")
        return "\n".join(t.strip() for t in texts if t.strip())
    except Exception as exc:
        return f"[DOCX文本抽取失败] {exc}"


def has_meaningful_text(text: str, min_chars: int = 80) -> bool:
    if text.startswith("[PDF文本抽取失败]") or text.startswith("[DOCX文本抽取失败]"):
        return False
    return len(re.sub(r"\s+", "", text)) >= min_chars


def text_file_has_meaningful_content(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return has_meaningful_text(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return False


def write_text_for_raw(raw_file: Path, text_dir: Path) -> Path | None:
    if raw_file.suffix.lower() == ".pdf":
        text = extract_pdf_text(raw_file)
    elif raw_file.suffix.lower() == ".docx":
        text = extract_docx_text(raw_file)
    else:
        return None
    if not has_meaningful_text(text):
        return None
    text_dir.mkdir(parents=True, exist_ok=True)
    target = text_dir / f"{raw_file.stem}.txt"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def should_try_npc(record: RuleRecord) -> bool:
    if record.local_path:
        return False
    if record.priority != "P0":
        return False
    title = canonical_title(record.title)
    if not title.startswith("中华人民共和国"):
        return False
    if any(word in record.title for word in ["关于", "规则", "案例", "入口", "相关", "合同编", "、", "及"]):
        return False
    return True


def download_npc(record: RuleRecord) -> None:
    title = canonical_title(record.title)
    raw_dir = RAW_ROOT / record.category / f"{record.id}_{safe_name(record.title)}"
    text_dir = TEXT_ROOT / record.category / f"{record.id}_{safe_name(record.title)}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    try:
        row = npc_lookup(title)
        if not row:
            record.errors.append(f"国家法律法规数据库未检索到：{title}")
            return
        bbbs = row["bbbs"]
        detail = npc_detail(bbbs) or {}
        meta_path = raw_dir / f"{record.id}_{safe_name(record.title)}_npc_detail.json"
        meta_path.write_text(json.dumps({"search_row": row, "detail": detail}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        raw_paths = [relpath(meta_path)]
        text_paths: list[str] = []
        for fmt in ["pdf", "docx"]:
            url = f"https://flk.npc.gov.cn/law-search/download/mobile?format={fmt}&bbbs={bbbs}&fileId="
            data, _ = request_bytes(url)
            target = raw_dir / f"{record.id}_{safe_name(record.title)}_国家法律法规数据库.{fmt}"
            target.write_bytes(data)
            raw_paths.append(relpath(target))
            text_target = write_text_for_raw(target, text_dir)
            if text_target:
                text_paths.append(relpath(text_target))
            time.sleep(0.2)
        record.source_url = join_unique([record.source_url, "https://flk.npc.gov.cn/"])
        record.source_type = join_unique([record.source_type, "国家法律法规数据库"])
        record.local_path = join_unique(split_field(record.local_path) + raw_paths)
        record.text_path = join_unique(split_field(record.text_path) + text_paths)
        record.file_type = join_unique(sorted({Path(path).suffix.lower().lstrip(".") for path in split_field(record.local_path)}))
        record.downloaded_count = len(split_field(record.local_path))
        record.current_status = "现行有效"
        record.notes.append("从国家法律法规数据库下载")
    except Exception as exc:
        record.errors.append(f"国家法律法规数据库下载失败：{exc}")


def record_to_row(record: RuleRecord) -> dict[str, Any]:
    if record.priority == "P0" and not record.local_path and record.current_status not in ["历史失效", "辅助资料"]:
        if "待月度巡检" not in record.notes:
            record.notes.append("P0规则尚无本地正式原文，待月度巡检")
    if record.priority == "P0" and not record.source_url and record.current_status not in ["历史失效", "辅助资料"]:
        record.current_status = "待核验"
    if "flk.npc.gov.cn" in record.source_url and not record.source_type:
        record.source_type = "国家法律法规数据库"

    return {
        "id": record.id,
        "legacy_id": record.legacy_id,
        "priority": record.priority,
        "category": record.category,
        "title": record.title,
        "layer": record.layer,
        "doc_type": record.doc_type,
        "issuer": record.issuer,
        "rule_no": record.rule_no,
        "publish_date": record.publish_date,
        "effective_date": record.effective_date,
        "current_status": record.current_status,
        "is_core": "是" if record.priority == "P0" else "否",
        "source_type": record.source_type,
        "product_tags": join_unique(record.product_tags),
        "business_line_tags": join_unique(record.business_line_tags),
        "market_tags": join_unique(record.market_tags),
        "business_tags": join_unique(record.business_tags + record.product_tags + record.business_line_tags + record.market_tags),
        "catalog_paths": join_unique(record.catalog_paths),
        "key_obligations": record.key_obligations,
        "source_url": record.source_url,
        "local_path": record.local_path,
        "text_path": record.text_path,
        "file_type": record.file_type,
        "downloaded_count": record.downloaded_count,
        "notes": join_unique(record.notes),
        "errors": join_unique(record.errors),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def html_anchor(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-") or "item"


def local_file_href(path: str) -> str:
    href = "../" + path.replace("\\", "/")
    return urllib.parse.quote(href, safe="/._-~%()（）《》【】[];：:—+")


def write_html_index(rows: list[dict[str, Any]], now: str) -> None:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    sections = []
    nav = []
    for idx, (category, items) in enumerate(by_category.items(), start=1):
        cat_id = f"cat-{idx:02d}-{html_anchor(category)}"
        nav.append(f'<a href="#{cat_id}"><span>{html.escape(category)}</span><strong>{len(items)}</strong></a>')
        cards = []
        for item in items:
            rule_id = f"rule-{html_anchor(item['id'])}"
            files = split_field(item.get("local_path", ""))
            file_links = "".join(
                f'<a href="{local_file_href(path)}" target="_blank" rel="noopener">{html.escape(Path(path).name)}</a>'
                for path in files
            ) or '<span class="empty">暂无本地正式原文</span>'
            source_links = "".join(
                f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(url)}</a>'
                for url in split_field(item.get("source_url", ""))
                if url.startswith("http")
            ) or '<span class="empty">暂无官方来源链接</span>'
            cards.append(
                f"""
                <article id="{rule_id}" class="card">
                  <h3><span>{html.escape(item['id'])}</span>{html.escape(item['title'])}</h3>
                  <p class="badges">{html.escape(item['priority'])}｜{html.escape(item['current_status'])}｜{html.escape(item['doc_type'])}</p>
                  <dl>
                    <div><dt>目录挂接</dt><dd>{html.escape(item['catalog_paths'])}</dd></div>
                    <div><dt>产品标签</dt><dd>{html.escape(item['product_tags'] or '未标注')}</dd></div>
                    <div><dt>条线标签</dt><dd>{html.escape(item['business_line_tags'] or '未标注')}</dd></div>
                    <div><dt>市场标签</dt><dd>{html.escape(item['market_tags'] or '未标注')}</dd></div>
                    <div><dt>发布机构</dt><dd>{html.escape(item['issuer'] or '待核验')}</dd></div>
                    <div><dt>文号</dt><dd>{html.escape(item['rule_no'] or '待核验')}</dd></div>
                  </dl>
                  <h4>本地原文</h4><div class="links">{file_links}</div>
                  <h4>官方来源</h4><div class="links">{source_links}</div>
                </article>
                """
            )
        sections.append(f'<section id="{cat_id}"><h2>{html.escape(category)} <span>{len(items)}条</span></h2>{"".join(cards)}</section>')

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>商业银行托管业务法规库总目录</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; background:#f5f7f8; color:#20242a; }}
    .layout {{ display:grid; grid-template-columns:320px 1fr; min-height:100vh; }}
    aside {{ position:sticky; top:0; height:100vh; overflow:auto; padding:20px; background:#eef3f4; border-right:1px solid #d8dde5; }}
    main {{ padding:28px min(5vw,56px) 64px; }}
    a {{ color:#145a63; text-decoration:none; }}
    nav a {{ display:flex; justify-content:space-between; gap:12px; padding:8px 10px; border-radius:6px; }}
    nav a:hover, .links a:hover {{ background:#e2f1f1; }}
    .hero {{ border-bottom:1px solid #d8dde5; margin-bottom:24px; padding-bottom:18px; }}
    .stats {{ display:flex; flex-wrap:wrap; gap:10px; }}
    .stats span, .badges {{ border:1px solid #d8dde5; border-radius:6px; background:white; padding:6px 10px; color:#59636f; }}
    section {{ margin-top:32px; }}
    h2 span {{ color:#687481; font-size:15px; }}
    .card {{ background:white; border:1px solid #d8dde5; border-radius:8px; padding:16px; margin:12px 0; }}
    .card h3 {{ margin:0; font-size:18px; }}
    .card h3 span {{ display:inline-block; min-width:62px; margin-right:10px; color:#fff; background:#1f6f78; border-radius:6px; padding:2px 8px; text-align:center; }}
    dl {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 18px; }}
    dt {{ color:#687481; font-size:12px; }}
    dd {{ margin:0; overflow-wrap:anywhere; }}
    .links {{ display:grid; gap:7px; }}
    .links a {{ display:block; border:1px solid #d8dde5; border-radius:6px; padding:8px 10px; overflow-wrap:anywhere; }}
    .empty {{ color:#8a5b16; }}
    @media (max-width:860px) {{ .layout {{ display:block; }} aside {{ position:relative; height:auto; max-height:50vh; }} dl {{ grid-template-columns:1fr; }} main {{ padding:20px 16px 48px; }} }}
  </style>
</head>
<body>
  <div class="layout">
    <aside><h1>总目录</h1><p>生成时间：{html.escape(now)}</p><nav>{"".join(nav)}</nav></aside>
    <main>
      <header class="hero">
        <h1>商业银行托管业务法规库总目录</h1>
        <p>同一法规原文只保存一份，通过产品、条线、市场和目录挂接复用。</p>
        <div class="stats">
          <span>{len(rows)} 条台账记录</span>
          <span>{sum(1 for r in rows if r['priority'] == 'P0')} 条 P0</span>
          <span>{sum(1 for r in rows if r.get('local_path'))} 条已有本地原文</span>
          <span>{sum(1 for r in rows if r['current_status'] in ['待核验','待扩展'])} 条待核验/待扩展</span>
        </div>
      </header>
      {"".join(sections)}
    </main>
  </div>
</body>
</html>
"""
    (ENTRY_ROOT / "总目录.html").write_text(html_doc, encoding="utf-8", newline="\n")


def write_markdown_indexes(rows: list[dict[str, Any]]) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    table = "\n".join(
        f"| {r['id']} | {r['legacy_id']} | {r['priority']} | {r['category']} | {r['title']} | {r['current_status']} | {r['product_tags']} | {r['business_line_tags']} | {r['market_tags']} |"
        for r in rows
    )
    (META_ROOT / "rules_index.md").write_text(
        "# 法规元数据台账\n\n"
        f"生成时间：{now}\n\n"
        "| ID | 旧ID | 优先级 | 分类 | 文件名称 | 状态 | 产品标签 | 条线标签 | 市场标签 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        f"{table}\n",
        encoding="utf-8",
        newline="\n",
    )
    write_html_index(rows, now)
    (ENTRY_ROOT / "更新记录.md").write_text(
        "# 更新记录\n\n"
        f"- {now}：按《中国商业银行托管业务条线大法规库总目录》重构商业银行托管业务法规库；旧公募基金托管库归档至 `98_历史归档/2026-06-12_公募基金托管库/`，并复用已核验原文和文本。\n",
        encoding="utf-8",
        newline="\n",
    )


def write_topic_map(rows: list[dict[str, Any]]) -> None:
    lines = ["# 托管业务专题地图", "", "本专题地图由大法规库目录、产品标签、条线标签和市场标签自动生成。", ""]

    by_catalog: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        first_path = split_field(row.get("catalog_paths", ""))[0] if row.get("catalog_paths") else row["category"]
        by_catalog.setdefault(first_path, []).append(row)

    lines.extend(["## 按大目录导航", ""])
    for catalog_path, items in by_catalog.items():
        lines.extend([f"### {catalog_path}", ""])
        for row in items:
            lines.append(f"- `{row['id']}` {row['title']}（{row['priority']}，{row['current_status']}）")
        lines.append("")

    for field, heading in [
        ("product_tags", "按适用产品"),
        ("business_line_tags", "按适用条线"),
        ("market_tags", "按适用市场"),
    ]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            for tag in split_field(row.get(field, "")):
                grouped.setdefault(tag, []).append(row)
        lines.extend([f"## {heading}", ""])
        for tag in sorted(grouped):
            lines.extend([f"### {tag}", ""])
            for row in grouped[tag]:
                lines.append(f"- `{row['id']}` {row['title']}（{row['priority']}，{row['current_status']}）")
            lines.append("")

    (TOPIC_ROOT / "托管业务专题地图.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_unresolved(rows: list[dict[str, Any]]) -> None:
    selected = [
        r
        for r in rows
        if r["current_status"] in ["待核验", "待扩展"]
        or r["errors"]
        or (r["priority"] == "P0" and not r["local_path"])
    ]
    lines = ["# 待核验与未完成项目", "", "以下项目均标注“待月度巡检”。", ""]
    for row in selected:
        source_state = "已联网或本地定位到官方来源但尚未完整入库" if row.get("source_url") else "仅有目录线索，尚待核验"
        if row.get("source_type") in ["辅助资料", "政策解读", "起草说明", "答记者问"]:
            source_state = "可先作为辅助资料但不能作为现行正式依据"
        lines.append(f"## {row['id']} {row['title']}")
        lines.append(f"- 状态：{row['current_status']}")
        lines.append(f"- 优先级：{row['priority']}")
        lines.append(f"- 目录挂接：{row['catalog_paths']}")
        lines.append(f"- 缺口类型：{source_state}")
        lines.append("- 巡检标记：待月度巡检")
        lines.append(f"- 来源：{row['source_url'] or '待检索'}")
        if row["notes"]:
            lines.append(f"- 备注：{row['notes']}")
        if row["errors"]:
            lines.append(f"- 错误/提示：{row['errors']}")
        lines.append("")
    (UNRESOLVED_ROOT / "unresolved.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    legacy_rows = load_legacy_rows()
    legacy_by_key = legacy_maps(legacy_rows)
    catalog_items, catalog_summary = parse_catalog()
    records = merge_catalog_items(catalog_items, legacy_by_key)

    archive_legacy_repository()
    reset_generated_dirs()
    ensure_category_dirs(records)

    legacy_manifest: list[dict[str, str]] = []
    for record in records:
        legacy_manifest.extend(copy_legacy_files(record))
        if should_try_npc(record):
            download_npc(record)

    rows = [record_to_row(record) for record in records]

    META_ROOT.mkdir(parents=True, exist_ok=True)
    write_csv(META_ROOT / "rules_index.csv", rows, FIELDS)
    write_csv(META_ROOT / "download_log.csv", rows, FIELDS)
    write_csv(META_ROOT / "legacy_manifest.csv", legacy_manifest, ["legacy_id", "new_id", "kind", "old_path", "new_path", "sha256"])
    (META_ROOT / "rules_index.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (META_ROOT / "master_rules.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (META_ROOT / "catalog_staging.json").write_text(json.dumps([item.__dict__ for item in catalog_items], ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    write_markdown_indexes(rows)
    write_topic_map(rows)
    write_unresolved(rows)
    search_index_summary = build_index(ROOT)

    summary = {
        **catalog_summary,
        "total_rules": len(rows),
        "p0_rules": sum(1 for row in rows if row["priority"] == "P0"),
        "rules_with_files": sum(1 for row in rows if row["local_path"]),
        "p0_without_files": sum(1 for row in rows if row["priority"] == "P0" and not row["local_path"]),
        "rules_waiting": sum(1 for row in rows if row["current_status"] in ["待核验", "待扩展"]),
        "legacy_reused_records": sum(1 for row in rows if row["legacy_id"]),
        "legacy_manifest_entries": len(legacy_manifest),
        "search_index": search_index_summary,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (META_ROOT / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
