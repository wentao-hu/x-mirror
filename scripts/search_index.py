"""从已渲染正文生成完整、轻量的首页全文搜索数据。"""
from __future__ import annotations

from collections import Counter
import re

from bs4 import BeautifulSoup


# 行内标签不加空格，避免把“付费<strong>转化</strong>率”拆开。
BLOCK_TAGS = (
    "p", "div", "section", "article", "aside", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
    "table", "tr", "th", "td", "details", "summary", "figure", "figcaption", "br",
)


def extract_text(body_html: str) -> str:
    soup = BeautifulSoup(body_html, "html.parser")
    for node in soup.select(
        "script, style, .chat-avatar, .chat-appendix > summary, .chat-note, .img-missing"
    ):
        node.decompose()
    for node in soup.find_all(BLOCK_TAGS):
        node.insert_before(" ")
        node.insert_after(" ")
    return re.sub(r"\s+", " ", soup.get_text()).strip()


def build_index(documents: list[dict], expected_slugs: list[str]) -> dict:
    slugs = [doc["slug"] for doc in documents]
    for label, values in (("全文索引", slugs), ("文章清单", expected_slugs)):
        repeated = [slug for slug, count in Counter(values).items() if count > 1]
        if repeated:
            raise ValueError(f"{label} slug 重复: {', '.join(repeated)}")
    if set(slugs) != set(expected_slugs):
        missing = sorted(set(expected_slugs) - set(slugs))
        extra = sorted(set(slugs) - set(expected_slugs))
        raise ValueError(f"全文索引与文章清单不一致，遗漏: {missing}，多出: {extra}")
    return {"version": 1, "documents": documents}
