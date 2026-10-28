#!/usr/bin/env python3
"""Extract X Articles from saved page.html + API metadata, download media, build static mirror."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from category_taxonomy import (
    CategoryTaxonomyError,
    definitions,
    load_taxonomy,
    official_names,
    validate_post_category,
)
from generate_webp import generate_all, image_width


def sniff_ext(path: Path) -> str:
    data = path.read_bytes()[:32]
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[4:8] == b"ftyp":
        return "mp4"
    return "jpg"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
POSTS = ROOT / "posts"
TZ8 = timezone(timedelta(hours=8))
CATEGORY_TAXONOMY = load_taxonomy()
CATEGORY_ORDER = official_names(CATEGORY_TAXONOMY)
CATEGORY_DEFINITIONS = definitions(CATEGORY_TAXONOMY)

# workdir -> post id
WORKDIRS = {
    "2110669876482203775": "/tmp/webpage-work",
    "2112216903150436383": "/tmp/webpage-work2",
    "2112129349071831259": "/tmp/webpage-work3",
    "2111268767342997847": "/tmp/webpage-work4",
    "2112061360708403397": "/tmp/webpage-work5",
    "2111826068017717314": "/tmp/webpage-work6b",
    "2109883678897909932": "/tmp/webpage-work7",
}

# 网站收藏：数据在根目录 sites.json，站点页在 sites.html
SITES_FILE = ROOT / "sites.json"
SITE_CATEGORY_ORDER = ["SEO 内容站", "工具站", "域名注册", "支付"]

CATEGORIES = {
    "2110669876482203775": "实战复盘",
    "2112216903150436383": "实战复盘",
    "2112129349071831259": "实战复盘",
    "2111826068017717314": "实战复盘",
    "2111268767342997847": "SEO获客",
    "2109883678897909932": "建站开发",
    "2112061360708403397": "SEO获客",
}

_legacy_unknown_categories = sorted(set(CATEGORIES.values()) - set(CATEGORY_ORDER))
if _legacy_unknown_categories:
    raise CategoryTaxonomyError(
        "旧抽取流程包含未知分类: " + ", ".join(_legacy_unknown_categories)
    )

CATEGORY_NAMES_MODULE = ROOT / "functions" / "_lib" / "category-names.js"


def validate_post_meta(meta: dict, source: str = "post") -> str:
    return validate_post_category(meta, CATEGORY_TAXONOMY, source=source)


def render_category_names_module() -> str:
    aliases = {}
    for category in CATEGORY_TAXONOMY["categories"]:
        for alias in category["aliases"]:
            aliases[alias] = category["name"]
    names_json = json.dumps(CATEGORY_ORDER, ensure_ascii=False, indent=2)
    aliases_json = json.dumps(aliases, ensure_ascii=False, indent=2)
    return (
        "/**\n"
        " * 由 category-taxonomy.json 自动生成，请勿手工编辑。\n"
        " * 生成命令：python3 scripts/rebuild_from_data.py\n"
        " */\n"
        f"export const CATEGORY_NAMES = Object.freeze({names_json});\n\n"
        f"export const CATEGORY_ALIASES = Object.freeze({aliases_json});\n"
    )


def write_category_names_module() -> None:
    CATEGORY_NAMES_MODULE.parent.mkdir(parents=True, exist_ok=True)
    CATEGORY_NAMES_MODULE.write_text(render_category_names_module(), encoding="utf-8")


SLUGS = {
    "2110669876482203775": "echo99-ai-site-5days-1500",
    "2112216903150436383": "kristoff-new-keyword-1100",
    "2112129349071831259": "xuxuan-72h-5480",
    "2111826068017717314": "jiangk-new-keyword-1000",
    "2111268767342997847": "qianshuixia-seo-foundation",
    "2109883678897909932": "cloudhu-ai-site-tutorial",
    "2112061360708403397": "sagasu-grokbot-backlinks",
}

DESCS = {
    "2110669876482203775": "新手 AI 付费工具站 5 天收入约 1500 刀的完整复盘",
    "2112216903150436383": "出海小白靠新词半个月破千刀的经验复盘",
    "2112129349071831259": "没投流没买外链，新词站 72 小时流水 $5480",
    "2111826068017717314": "副业出海小白首日破百、5 天破千的新词经验",
    "2111268767342997847": "整理哥飞干货：SEO 地基与新手出关指南",
    "2109883678897909932": "小白可跟做的 AI 出海建站全流程教程（含截图）",
    "2112061360708403397": "用 Grok Bot 一天筛提 4000+ 站的外链自动化流程",
}

JUNK_HEADINGS = {
    "Article",
    "Log in or sign up for X",
    "Relevant people",
    "Trending now",
}


def slugify_media(url: str) -> str:
    m = re.search(r"/media/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:12]


def orig_url(src: str) -> str:
    """Force highest-res download URL for pbs.twimg media."""
    if "profile_images" in src:
        # upgrade avatar
        src = re.sub(r"_normal(\.|$)", r"_400x400\1", src)
        src = re.sub(r"_bigger(\.|$)", r"_400x400\1", src)
        return src
    if "/media/" not in src:
        return src
    # strip query, add orig
    base = src.split("?")[0]
    # remove extension if present in path (sometimes .jpg appended)
    # pbs URLs like .../HUp2sOla4AACug8.jpg or .../HUp2sOla4AACug8
    base = re.sub(r"\.(jpg|jpeg|png|webp)$", "", base, flags=re.I)
    return base + "?format=jpg&name=orig"


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    # try orig first, then large, then as-is
    candidates = [url]
    if "name=orig" in url:
        candidates.append(url.replace("name=orig", "name=large"))
        candidates.append(url.replace("name=orig", "name=medium"))
    for u in candidates:
        try:
            r = subprocess.run(
                [
                    "curl",
                    "-fsSL",
                    "-A",
                    "Mozilla/5.0 (compatible; XMirror/1.0)",
                    "--max-time",
                    "60",
                    "-o",
                    str(dest),
                    u,
                ],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0 and dest.exists() and dest.stat().st_size > 500:
                # magic-byte sniff
                try:
                    ext = sniff_ext(dest)
                    if ext in ("jpg", "png", "webp", "gif", "mp4") or dest.stat().st_size > 5000:
                        return True
                except Exception:
                    if dest.stat().st_size > 5000:
                        return True
            if dest.exists():
                dest.unlink()
        except Exception as e:
            print("download err", u, e)
    return False


def find_article_container(soup: BeautifulSoup) -> tuple[Tag, str, list]:
    """Return (body_node, title, cover_imgs). Prefer .x-article-body."""
    h1 = None
    for h in soup.find_all("h1"):
        t = h.get_text(strip=True)
        if t and len(t) > 8 and t not in JUNK_HEADINGS and "sign up" not in t.lower():
            h1 = h
            break
    if not h1:
        raise RuntimeError("no h1")
    title = h1.get_text(strip=True)

    body = soup.select_one(".x-article-body")
    if body is None:
        # fallback: h1 parent flex-col
        body = h1.parent
        for _ in range(3):
            if body and body.select_one(".x-article-body"):
                body = body.select_one(".x-article-body")
                break
            body = body.parent if body else None
        if body is None:
            body = h1.parent

    # cover: media images that appear before the body in the post column
    cover_imgs = []
    # look in h1.parent for media imgs not inside body
    col = h1.parent
    if col:
        for img in col.find_all("img"):
            src = img.get("src") or ""
            if "/media/" not in src:
                continue
            if body and img in body.find_all("img"):
                continue
            # only those before body in document order
            cover_imgs.append(img)
            break  # typically one cover

    return body, title, cover_imgs


def normalize_media_src(src: str) -> str | None:
    if not src or "pbs.twimg.com" not in src:
        return None
    if "/media/" not in src and "profile_images" not in src and "amplify_video" not in src:
        return None
    if "profile_images" in src:
        return None  # handled separately as avatar
    return src


def walk_blocks(container: Tag) -> list[dict]:
    """Walk article container into ordered blocks, preserving image positions."""
    blocks: list[dict] = []
    seen_media: set[str] = set()
    seen_heading_text: set[str] = set()

    def media_key(src: str) -> str:
        m = re.search(r"/media/([A-Za-z0-9_-]+)", src)
        return m.group(1) if m else src.split("?")[0]

    def add_image(img: Tag):
        src = img.get("src") or img.get("data-src") or ""
        n = normalize_media_src(src)
        if not n:
            return
        key = media_key(n)
        if key in seen_media:
            return
        seen_media.add(key)
        alt = (img.get("alt") or "").strip()
        blocks.append(
            {
                "type": "image",
                "src": n,
                "orig_url": orig_url(n),
                "alt": alt,
                "key": key,
            }
        )

    def add_text_from(el: Tag):
        # Collect inline structure somewhat faithfully
        name = el.name.lower()
        text = el.get_text("\n", strip=False)
        # collapse excessive blank lines later
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            t = el.get_text(strip=True)
            if not t or t in JUNK_HEADINGS:
                return
            # skip duplicate headings from double-render
            if t in seen_heading_text and name == "h1":
                return
            if t in seen_heading_text and blocks and blocks[-1].get("text") == t:
                return
            seen_heading_text.add(t)
            level = int(name[1])
            blocks.append({"type": "heading", "level": level, "text": t})
            return
        if name in ("pre",):
            code = el.get_text()
            blocks.append({"type": "code", "text": code})
            return
        if name == "blockquote":
            blocks.append({"type": "quote", "text": el.get_text("\n", strip=True)})
            return
        if name in ("ul", "ol"):
            items = []
            for li in el.find_all("li", recursive=False):
                items.append(li.get_text(" ", strip=True))
            if items:
                blocks.append({"type": "list", "ordered": name == "ol", "items": items})
            return
        if name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})
            return
        if name == "a" and el.get("href"):
            # standalone link paragraphs handled at p level
            pass
        if name in ("p", "div", "span", "section"):
            # if this element directly contains media images, process children
            pass

    # Prefer iterating descendants in order but only emit at meaningful nodes
    # Strategy: get all direct structural elements in document order via recursive walk
    def visit(el: Tag, depth=0):
        if not isinstance(el, Tag):
            return
        name = (el.name or "").lower()
        # images
        if name == "img":
            add_image(el)
            return
        # headings
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            add_text_from(el)
            return
        if name in ("pre", "blockquote", "table", "ul", "ol"):
            add_text_from(el)
            return
        if name == "p":
            # check for images inside
            imgs = el.find_all("img")
            if imgs and not el.get_text(strip=True):
                for img in imgs:
                    add_image(img)
                return
            # mixed: process children in order
            if imgs:
                for child in el.children:
                    if isinstance(child, Tag):
                        visit(child, depth + 1)
                    elif isinstance(child, NavigableString):
                        t = str(child).strip()
                        if t:
                            blocks.append({"type": "paragraph", "text": t})
                return
            t = el.get_text("\n", strip=True)
            if t:
                # skip pure junk
                if t in JUNK_HEADINGS:
                    return
                blocks.append({"type": "paragraph", "text": t})
            return
        if name in ("a",) and el.find("img"):
            for img in el.find_all("img"):
                add_image(img)
            return
        # generic container: visit children
        if name in ("div", "section", "article", "main", "li", "figure", "picture", "span", "button"):
            # if it's a leaf-ish text div with no block children
            child_tags = [c for c in el.children if isinstance(c, Tag)]
            has_block = any(
                (c.name or "").lower()
                in (
                    "p",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "div",
                    "ul",
                    "ol",
                    "pre",
                    "blockquote",
                    "table",
                    "figure",
                    "img",
                    "section",
                    "article",
                )
                for c in child_tags
            )
            if not has_block and not el.find("img"):
                t = el.get_text("\n", strip=True)
                # only emit short leaf texts if they look like paragraphs (avoid UI chrome)
                if t and len(t) > 40 and t not in JUNK_HEADINGS:
                    # avoid duplicating if already captured via parent
                    pass
                return
            for child in el.children:
                if isinstance(child, Tag):
                    visit(child, depth + 1)
            return
        # other tags: descend
        for child in el.children:
            if isinstance(child, Tag):
                visit(child, depth + 1)

    visit(container)

    # Deduplicate consecutive identical paragraphs
    cleaned: list[dict] = []
    for b in blocks:
        if cleaned:
            prev = cleaned[-1]
            if (
                b.get("type") == prev.get("type")
                and b.get("text") == prev.get("text")
                and b.get("type") in ("paragraph", "heading")
            ):
                continue
            if b.get("type") == "image" and prev.get("type") == "image" and b.get("key") == prev.get("key"):
                continue
        cleaned.append(b)
    return cleaned


def enrich_from_plain_text(blocks: list[dict], plain: str, entities: dict) -> list[dict]:
    """If HTML extraction lost structure (e.g. CloudHu has few headings),
    rebuild paragraphs from plain_text while keeping image order interleaved
    by inserting images at blank-line gaps proportional to media count.
    Only used when HTML blocks have very few paragraphs relative to plain_text.
    """
    html_paras = [b for b in blocks if b["type"] == "paragraph"]
    html_imgs = [b for b in blocks if b["type"] == "image"]
    plain_paras = [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
    # If HTML already has substantial text, keep HTML order (better for image placement)
    html_text_len = sum(len(b.get("text") or "") for b in blocks if b["type"] in ("paragraph", "heading"))
    html_headings = [b for b in blocks if b["type"] == "heading" and b.get("level", 0) > 1]
    # Prefer HTML structure whenever it has real section headings or enough paragraphs
    if html_headings or (html_text_len >= len(plain) * 0.55 and len(html_paras) >= max(3, len(plain_paras) // 4)):
        return blocks

    # Rebuild: split plain into lines/paras; distribute images at blank lines
    # Heuristic: place images after paragraphs that are followed by blank lines in original,
    # spreading images evenly through the article.
    lines = plain.split("\n")
    para_chunks: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.strip() == "":
            if buf:
                para_chunks.append("\n".join(buf).strip())
                buf = []
            para_chunks.append("")  # marker for potential image slot
        else:
            buf.append(line)
    if buf:
        para_chunks.append("\n".join(buf).strip())

    slots = [i for i, c in enumerate(para_chunks) if c == ""]
    imgs = html_imgs[:]
    # assign images to blank slots evenly
    assignment: dict[int, list[dict]] = {}
    if slots and imgs:
        # put cover-like first image early, rest distributed
        n = len(imgs)
        # use first n blank slots spaced across
        if len(slots) >= n:
            step = len(slots) / n
            chosen = [slots[int(i * step)] for i in range(n)]
        else:
            chosen = slots + [slots[-1]] * (n - len(slots))
        for img, slot in zip(imgs, chosen):
            assignment.setdefault(slot, []).append(img)

    new_blocks: list[dict] = []
    # Keep title heading if present
    for b in blocks:
        if b["type"] == "heading" and b.get("level") == 1:
            new_blocks.append(b)
            break

    used_img_keys = set()
    img_iter = iter(imgs)
    for i, chunk in enumerate(para_chunks):
        if chunk == "":
            for img in assignment.get(i, []):
                if img["key"] not in used_img_keys:
                    new_blocks.append(img)
                    used_img_keys.add(img["key"])
            continue
        # detect markdown-ish headings: short line without period?
        # keep as paragraph; headings from HTML preferred
        # detect code fences
        if chunk.startswith("```"):
            new_blocks.append({"type": "code", "text": chunk.strip("`").strip()})
            continue
        new_blocks.append({"type": "paragraph", "text": chunk})

    # append any unused images at end
    for img in imgs:
        if img["key"] not in used_img_keys:
            new_blocks.append(img)
            used_img_keys.add(img["key"])
    return new_blocks


def apply_entities_links(text: str, entities: dict) -> str:
    """Return plain text; links rendered separately in HTML builder via regex URLs."""
    return text


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_HEADING_PATH_CHARS = re.compile(r"[/\\]")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def clean_heading_text(text: str) -> str:
    """标题里去掉 / 和 \\，避免像路径或乱码；替换为空格并合并空白。"""
    return re.sub(r"\s+", " ", _HEADING_PATH_CHARS.sub(" ", text)).strip()


def plain_heading_text(text: str) -> str:
    """目录标题只保留链接文字，避免嵌套 <a>。"""
    return clean_heading_text(_MARKDOWN_LINK.sub(r"\1", text).replace("**", ""))


def render_heading_text(text: str) -> str:
    """渲染标题内的链接和强调；无链接时仍清理路径字符。"""
    safe = re.sub(r"\s+", " ", text).strip() if _MARKDOWN_LINK.search(text) else clean_heading_text(text)
    return linkify(safe)


SOURCE_TYPE_LABELS = {
    "x_post": "帖子",
    "x_article": "长文",
    "talk": "演讲展示",
    "web_article": "网页",
    "webcafe": "web.cafe",
    "wechat": "微信",
    "reddit": "Reddit",
    "note": "自建笔记",
}

X_ICON = '<span class="src-icon" aria-hidden="true">𝕏</span>'
GLOBE_ICON = (
    '<svg class="src-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<circle cx="8" cy="8" r="6.5"></circle>'
    '<ellipse cx="8" cy="8" rx="3" ry="6.5"></ellipse>'
    '<path d="M1.5 8h13"></path></svg>'
)
CAFE_ICON = (
    '<svg class="src-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<path d="M3.2 5.5h7.3v4.2a2.9 2.9 0 0 1-2.9 2.9H6.1a2.9 2.9 0 0 1-2.9-2.9V5.5Z"></path>'
    '<path d="M10.5 6.6h1.2a1.9 1.9 0 1 1 0 3.8h-1.2"></path>'
    '<path d="M5.2 2.2c0 .7-.7.7-.7 1.4M7.7 2.2c0 .7-.7.7-.7 1.4"></path></svg>'
)
WECHAT_ICON = (
    '<svg class="src-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<path d="M6.4 3C3.7 3 1.8 4.6 1.8 6.6c0 1.1.6 2 1.6 2.7l-.3 1.5 1.7-.9c.5.1 1 .2 1.6.2 2.7 0 4.6-1.6 4.6-3.6S9.1 3 6.4 3Z"></path>'
    '<path d="M10.2 6.4c2 0 3.6 1.3 3.6 2.9 0 .9-.5 1.7-1.3 2.3l.3 1.2-1.4-.7c-.4.1-.8.1-1.2.1-2 0-3.6-1.3-3.6-2.9s1.6-2.9 3.6-2.9Z"></path></svg>'
)
REDDIT_ICON = (
    '<svg class="src-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<circle cx="8" cy="9" r="5.2"></circle>'
    '<circle cx="6.1" cy="8.6" r="0.7" fill="currentColor" stroke="none"></circle>'
    '<circle cx="9.9" cy="8.6" r="0.7" fill="currentColor" stroke="none"></circle>'
    '<path d="M5.9 11c1.2.9 3 .9 4.2 0"></path>'
    '<path d="M8 3.9V2.5"></path><circle cx="8" cy="2.2" r=".55"></circle>'
    '<path d="M8 2.5 10.2 3"></path></svg>'
)
NOTE_ICON = (
    '<svg class="src-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<path d="M4 2.5h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1Z"></path>'
    '<path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3"></path></svg>'
)
TALK_ICON = (
    '<svg class="src-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<rect x="2" y="2.8" width="12" height="7.8" rx="1.3"></rect>'
    '<path d="M8 10.6v2.2M5.6 13.4h4.8"></path>'
    '<path d="M4.8 5.2h6.4M4.8 7.2h4.2"></path></svg>'
)


def source_type_of(meta: dict) -> str:
    """来源类型；旧数据缺失时按 entry_type 推断，legacy webcafe_link 归一到 webcafe。"""
    st = meta.get("source_type") or (
        "webcafe" if meta.get("entry_type") == "link_only" else "x_post"
    )
    # link_only 是条目形态，不是独立类型；旧值 webcafe_link 一并归一
    return "webcafe" if st in ("link_only", "webcafe_link") else st


ORIGIN_LABELS = {
    "x_article": "X",
    "x_post": "X",
    "webcafe": "web.cafe",
    "wechat": "微信公众号",
    "web_article": "网页",
    "reddit": "Reddit",
    "talk": "演讲",
}


def author_handle(meta: dict) -> str:
    """作者 handle：Reddit 用 u/；笔记是站内原创，无 handle；其余用 @。"""
    if source_type_of(meta) == "note":
        return ""
    username = esc(meta.get("author_username", ""))
    if not username:
        return ""
    return f"u/{username}" if source_type_of(meta) == "reddit" else f"@{username}"


def original_link_text(meta: dict) -> str:
    """原文链接文案：括号内按来源类型标注，非 X 内容不要冒充 X。"""
    origin = ORIGIN_LABELS.get(source_type_of(meta))
    return f"查看原文（{origin}）↗" if origin else "查看原文↗"


def source_badge(meta: dict) -> str:
    """标题旁的来源徽标；类型名与筛选按钮保持一致。"""
    st = source_type_of(meta)
    label = SOURCE_TYPE_LABELS.get(st)
    if not label:
        return ""
    icon = {
        "webcafe": CAFE_ICON,
        "wechat": WECHAT_ICON,
        "web_article": GLOBE_ICON,
        "reddit": REDDIT_ICON,
        "note": NOTE_ICON,
        "talk": TALK_ICON,
    }.get(st, X_ICON)
    return (
        f'<span class="source-badge" data-source-type="{esc(st)}">'
        f'{icon}<span class="src-label">{label}</span></span>'
    )


def meta_tags(meta: dict) -> list[str]:
    """返回清洗后的相关关键词，忽略空值和非法类型。"""
    return [
        tag.strip()
        for tag in (meta.get("tags") or [])
        if isinstance(tag, str) and tag.strip()
    ]


def tags_html(meta: dict, *, compact: bool = False, show_label: bool = False) -> str:
    """关键词徽章（页面 UI 已停用；保留函数供必要时内部复用）。目录搜索仍可用 meta_tags。"""
    tags = meta_tags(meta)
    if not tags:
        return ""
    classes = "tag-list tag-list--compact" if compact else "tag-list"
    label = '<span class="tag-list__label">关键词</span>' if show_label else ""
    badges = "".join(
        f'<span class="tag-badge" data-tag="{esc(tag)}">{esc(tag)}</span>'
        for tag in tags
    )
    return f'<div class="{classes}" aria-label="关键词">{label}{badges}</div>'


_INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")


def protect_inline_code(s: str, code_spans: dict[str, str]) -> str:
    """把行内代码替换为占位符，避免后续链接和强调规则改写代码内容。"""

    def repl(match: re.Match) -> str:
        key = f"\x00code{len(code_spans)}\x00"
        code_spans[key] = f'<code class="inline-code">{match.group(1)}</code>'
        return key

    return _INLINE_CODE_RE.sub(repl, s)


def restore_inline_code(s: str, code_spans: dict[str, str]) -> str:
    for key, html in code_spans.items():
        s = s.replace(key, html)
    return s


def render_inline_text(text: str) -> str:
    """渲染不自动链接的行内 Markdown，目前用于标题和表格。"""
    code_spans: dict[str, str] = {}
    s = protect_inline_code(esc(text), code_spans)
    return restore_inline_code(s, code_spans)


def linkify(text: str, *, link_mentions: bool = True) -> str:
    """Escape then render inline code, links, emphasis, URLs and @handles."""
    code_spans: dict[str, str] = {}
    s = protect_inline_code(esc(text), code_spans)

    # 《标题》 + 同段唯一裸 URL → 标题本身成为链接，不再显示一行裸网址。
    # 典型：微信文末「《某篇标题》\nhttps://mp.weixin.qq.com/s?…」
    urls = re.findall(r"https?://[^\s<>\"']+", s)
    titles = re.findall(r"《[^》\n]+》", s)
    if len(urls) == 1 and len(titles) == 1:
        url, title = urls[0], titles[0]
        url_line = re.compile(r"\n[ \t]*" + re.escape(url) + r"[ \t]*\s*$")
        if url_line.search(s):
            s = s.replace(title, f"[{title}]({url})", 1)
            s = url_line.sub("", s).rstrip()

    # [文字](https://…) → <a>；先换成占位符，避免裸 URL 规则二次命中
    md_links: dict[str, str] = {}

    def repl_md(m):
        label, url = m.group(1), m.group(2)
        label = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", label)
        key = f"\x00md{len(md_links)}\x00"
        md_links[key] = (
            f'<a href="{url}" rel="noopener noreferrer" target="_blank">{label}</a>'
        )
        return key

    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", repl_md, s)

    # **强调** → <strong>（网页/Reddit 原文的加粗）
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    def repl_url(m):
        u = m.group(0)
        return f'<a href="{u}" rel="noopener noreferrer" target="_blank">{u}</a>'

    s = re.sub(r"https?://[^\s<>\"']+", repl_url, s)
    if link_mentions:
        s = re.sub(
            r"(?<!\w)@([A-Za-z0-9_]{1,15})",
            r'<a class="mention" href="https://x.com/\1" rel="noopener noreferrer" target="_blank">@\1</a>',
            s,
        )
    for key, html in md_links.items():
        s = s.replace(key, html)
    s = restore_inline_code(s, code_spans)
    # 不要在 <br> 后再保留源码换行；聊天区使用 pre-wrap，否则同一换行会渲染两次。
    s = s.replace("\n", "<br>")
    return s


def asset_version(rel_path: str) -> str:
    """返回资产内容 sha256 前 8 位，用于 ?v= 缓存版本。"""
    return hashlib.sha256((ROOT / rel_path).read_bytes()).hexdigest()[:8]


def image_html(
    rel_src: str,
    alt: str,
    assets_dir: Path | None = None,
    lazy: bool = False,
    responsive: bool = False,
) -> str:
    """输出 <img>；若同目录已有 webp，则包一层 <picture> 提供 WebP 源。

    responsive=True 时输出 640/960/原尺寸三档 srcset，交给浏览器按视口选择。
    """
    attrs = f'src="{rel_src}" alt="{alt}"'
    if lazy:
        attrs += ' loading="lazy" decoding="async"'
    img = f"<img {attrs} />"

    if assets_dir is not None:
        webp_path = Path(rel_src).with_suffix(".webp")
        if (assets_dir / webp_path.name).exists():
            if responsive:
                candidates = []
                for w in (640, 960, 1280):
                    cand = assets_dir / f"{webp_path.stem}-{w}.webp"
                    if cand.exists():
                        candidates.append(
                            f"{webp_path.with_name(cand.name).as_posix()} {w}w"
                        )
                width = image_width(assets_dir / Path(rel_src).name)
                if width:
                    candidates.append(f"{webp_path.as_posix()} {width}w")
                if len(candidates) > 1:
                    sizes = "(max-width: 760px) calc(100vw - 32px), 835px"
                    return (
                        f'<picture><source srcset="{", ".join(candidates)}" '
                        f'sizes="{sizes}" type="image/webp">{img}</picture>'
                    )
            return (
                f'<picture><source srcset="{webp_path.as_posix()}" '
                f'type="image/webp">{img}</picture>'
            )
    return img


_X_STATUS_URL_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/"
    r"[^\s<>\"']+/status/\d+(?:\?[^\s<>\"']*)?",
    re.I,
)
_CHAT_AVATAR_COLORS = (
    "#2f855a",
    "#2b6cb0",
    "#c05621",
    "#975a16",
    "#9b2c2c",
    "#6b46c1",
    "#2c7a7b",
    "#4a5568",
)


def clean_chat_text(text: str) -> str:
    """Remove X status URLs that would otherwise dominate a chat bubble."""
    cleaned = _X_STATUS_URL_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def chat_avatar_html(
    msg: dict,
    assets_rel: str,
    assets_dir: Path | None,
) -> str:
    """Render a local avatar when present, otherwise a stable initial."""
    user = str(msg.get("user") or "").strip()
    avatar = str(msg.get("avatar") or "").strip()
    if avatar:
        if re.match(r"^https?://", avatar):
            inner = (
                f'<img src="{esc(avatar)}" alt="" loading="lazy" decoding="async" />'
            )
        else:
            rel = avatar.lstrip("/")
            src = rel if rel.startswith(f"{assets_rel}/") else f"{assets_rel}/{rel}"
            inner = image_html(src, "", assets_dir=assets_dir, lazy=True)
    else:
        initial = user[:1].upper() if user else "?"
        color = _CHAT_AVATAR_COLORS[
            sum(ord(char) for char in user) % len(_CHAT_AVATAR_COLORS)
        ]
        inner = (
            '<span class="chat-avatar__initial" '
            f'style="--chat-avatar-bg:{color}">{esc(initial)}</span>'
        )
    return f'<span class="chat-avatar" aria-hidden="true">{inner}</span>'


def chat_message_html(
    msg: dict,
    assets_rel: str = "assets",
    assets_dir: Path | None = None,
) -> str:
    """Render one left-aligned WeChat-style message."""
    user = str(msg.get("user") or "匿名").strip()
    sent_at = str(msg.get("time") or "").strip()
    time_html = (
        f'<span class="chat-time">{esc(sent_at)}</span>' if sent_at else ""
    )
    text = clean_chat_text(str(msg.get("text") or ""))
    return (
        '<div class="chat-msg" role="listitem">'
        f'{chat_avatar_html(msg, assets_rel, assets_dir)}'
        '<div class="chat-message">'
        '<div class="chat-meta">'
        f'<span class="chat-user">{esc(user)}</span>{time_html}'
        '</div>'
        f'<div class="chat-bubble"><div class="chat-text">{linkify(text, link_mentions=False)}</div></div>'
        "</div>"
        "</div>"
    )


def render_chat_html(
    b: dict,
    assets_rel: str = "assets",
    assets_dir: Path | None = None,
) -> str:
    """Render a chat log as one collapsed, expandable bubble list."""
    messages = b["messages"]
    if not messages:
        return ""
    people = list(dict.fromkeys(str(m.get("user") or "匿名") for m in messages))
    raw = b.get("raw_count", len(messages))
    removed = b.get("removed_count", 0)
    removed_note = b.get("removed_note", "纯表情")
    times = [str(m.get("time") or "").strip() for m in messages]
    times = [value for value in times if value]
    span = ""
    if times:
        span = f"{times[0]} 至 {times[-1]}" if times[0] != times[-1] else times[0]
    note_parts = [f"参与者 {len(people)} 人：{esc('、'.join(people))}"]
    if span:
        note_parts.append(f"时间范围 {esc(span)}")
    note_parts.append(
        f"原始 {raw} 条，保留 {len(messages)} 条"
        + (f"，删除 {removed} 条{esc(removed_note)}" if removed else "")
    )
    note = " · ".join(note_parts)
    log_html = "\n".join(
        chat_message_html(m, assets_rel, assets_dir) for m in messages
    )
    return (
        '<div class="chat-block">'
        '<details class="chat-appendix">'
        f'<summary>聊天记录（{len(messages)} 条）</summary>'
        f'<div class="chat-note">{note}</div>'
        f'<div class="chat-log" role="list">{log_html}</div>'
        "</details></div>"
    )


def assign_heading_ids(blocks: list[dict]) -> None:
    n = 0
    for b in blocks:
        if b["type"] == "heading" and b.get("level") in (2, 3):
            n += 1
            b["_id"] = f"sec-{n}"


def render_toc_html(blocks: list[dict]) -> str:
    """右侧目录：h2 为一级、h3 为其下的二级；少于两条标题不生成。"""
    blocks = [dict(b) for b in blocks]  # 内部 id 不回写到数据
    assign_heading_ids(blocks)
    entries = [
        (b["level"], b["_id"], b["text"])
        for b in blocks
        if b["type"] == "heading" and b.get("level") in (2, 3)
    ]
    if len(entries) < 2:
        return ""
    tree: list[dict] = []
    for level, hid, text in entries:
        node = {"level": level, "id": hid, "text": text, "children": []}
        # 没有 h2 兜底时 h3 也作为一级，不能挂到前一个 h3 下面
        if level == 3 and tree and tree[-1]["level"] == 2:
            tree[-1]["children"].append(node)
        else:
            tree.append(node)

    def render_nodes(nodes: list[dict], depth: int = 0) -> str:
        out = []
        for node in nodes:
            link = (
                f'<a class="toc-link toc-l{min(depth, 1) + 1}" '
                f'href="#{node["id"]}">{render_inline_text(plain_heading_text(node["text"]))}</a>'
            )
            children = ""
            if node["children"]:
                children = (
                    '<ul class="toc-l2-list">'
                    + render_nodes(node["children"], depth + 1)
                    + "</ul>"
                )
            out.append(f"<li>{link}{children}</li>")
        return "".join(out)

    has_children = any(node["children"] for node in tree)
    fold_btn = (
        '<button type="button" class="toc-fold" aria-expanded="true">全折叠</button>'
        if has_children
        else ""
    )
    return (
        '<aside class="toc" id="toc-panel" hidden aria-label="文章目录">'
        '<div class="toc-head"><span class="toc-title">目录</span>'
        f'{fold_btn}<button type="button" class="toc-close" aria-label="隐藏目录">×</button>'
        '</div><nav class="toc-nav"><ul class="toc-l1-list">'
        + render_nodes(tree)
        + "</ul></nav></aside>"
        '<button type="button" class="toc-open" aria-label="展开目录" title="目录" '
        'aria-controls="toc-panel" hidden>'
        '<svg class="toc-open-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M4 6h.01M8 6h12M4 12h.01M8 12h12M4 18h.01M8 18h12"/>'
        "</svg></button>"
    )


def render_blocks_html(
    blocks: list[dict], assets_rel: str, assets_dir: Path | None = None
) -> str:
    blocks = [dict(b) for b in blocks]  # 内部 id 不回写到数据
    assign_heading_ids(blocks)
    parts = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            level = min(max(b.get("level", 2), 1), 4)
            if level == 1:
                continue  # title rendered in header
            hid = f' id="{esc(b["_id"])}"' if b.get("_id") else ""
            parts.append(
                f"<h{level}{hid}>{render_heading_text(b['text'])}</h{level}>"
            )
        elif t == "paragraph":
            parts.append(f"<p>{linkify(b['text'])}</p>")
        elif t == "image":
            local = b.get("local")
            if not local:
                parts.append(
                    f'<p class="img-missing">[图片未能下载: {esc(b.get("key",""))}]</p>'
                )
                continue
            alt = esc(b.get("alt") or "")
            img = image_html(
                f"{assets_rel}/{local}", alt, assets_dir=assets_dir, lazy=True,
                responsive=True,
            )
            # 手机上正文图片只有屏宽，点开可在新标签查看原图
            parts.append(
                f'<figure class="media"><a class="media-link" href="{assets_rel}/{esc(local)}" '
                f'target="_blank" rel="noopener" aria-label="查看大图">{img}</a></figure>'
            )
        elif t == "video":
            # Legacy video blocks are links only. Never emit a player.
            src = b.get("src") or b.get("url") or b.get("local")
            if not src:
                parts.append('<p class="img-missing">[视频链接缺失]</p>')
                continue
            href = (
                esc(src)
                if re.match(r"^https?://", src)
                else f"{assets_rel}/{esc(src)}"
            )
            parts.append(
                f'<p>观看原视频：<a href="{href}" rel="noopener noreferrer" '
                f'target="_blank">{href}</a></p>'
            )
        elif t == "code":
            parts.append(f"<pre><code>{esc(b['text'])}</code></pre>")
        elif t == "quote":
            parts.append(f"<blockquote>{linkify(b['text'])}</blockquote>")
        elif t == "callout":
            title_html = (
                f'<div class="callout__title">{esc(b["title"])}</div>'
                if b.get("title")
                else ""
            )
            items_html = "".join(
                f"<li>{linkify(i)}</li>" for i in b.get("items", [])
            )
            text_html = f"<p>{linkify(b['text'])}</p>" if b.get("text") else ""
            parts.append(
                f'<aside class="callout">{title_html}<ul>{items_html}</ul>{text_html}</aside>'
            )
        elif t == "list":
            tag = "ol" if b.get("ordered") else "ul"
            items = "".join(f"<li>{linkify(i)}</li>" for i in b["items"])
            parts.append(f"<{tag}>{items}</{tag}>")
        elif t == "chat":
            parts.append(render_chat_html(b, assets_rel, assets_dir))
        elif t == "table":
            rows_html = []
            for ri, row in enumerate(b["rows"]):
                cells = "".join(
                    f"<{'th' if ri==0 else 'td'}>{linkify(c)}</{'th' if ri==0 else 'td'}>"
                    for c in row
                )
                rows_html.append(f"<tr>{cells}</tr>")
            parts.append(
                "<div class='table-wrap'><table>" + "".join(rows_html) + "</table></div>"
            )
    return "\n".join(parts)


CSS = r"""
:root {
  --bg: #ffffff;
  --fg: #0f1419;
  --muted: #536471;
  --muted-2: #7a8b98;
  --border: #e9eef2;
  --border-strong: #d3dce2;
  --link: #1d9bf0;
  --card: #f7f9fa;
  --card-hover: #f0f4f6;
  --star: #f5a524;
  --ok: #0f7b45;
  --ok-soft: #e8f5ee;
  --radius: 14px;
  --pad-x: 20px;
  --header-h: 56px;
  /* 阅读设置：读者可调的正文缩放（1 = 默认） */
  --reader-fs: 1;
  --reader-lh: 1;
  --reader-w: 1;
}
* { box-sizing: border-box; }
html {
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}
html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  line-height: 1.75;
  font-size: 17px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
/* 兜底：任何漏网的长串（网址、代码、表格）都不让整页横向滚动 */
body { overflow-x: clip; }
::selection { background: color-mix(in srgb, var(--link) 20%, transparent); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 2px; }
button { font-family: inherit; }
picture { display: contents; }
a:focus-visible, button:focus-visible {
  outline: 2px solid var(--link); outline-offset: 2px; border-radius: 6px;
}
.wrap { max-width: 875px; margin: 0 auto; padding: 0 var(--pad-x) 72px; }
.index-wrap { max-width: 1000px; }
/* 行宽只在桌面生效：移动端视口本身比 875px 窄，max-width 不起作用 */
.post-page .wrap { max-width: calc(875px * var(--reader-w)); }

/* 顶部导航：不吸顶，随页面滚动离开视口 */
.site-header {
  display: flex; align-items: center; justify-content: space-between;
  height: var(--header-h);
  margin: 0 calc(var(--pad-x) * -1) 24px;
  padding: 0 var(--pad-x);
  border-bottom: 1px solid var(--border);
}
.post-header { justify-content: flex-start; }
.back-link {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: -10px; padding: 8px 10px;
  color: var(--muted); font-size: 14px; border-radius: 8px;
}
.back-link:hover { color: var(--fg); background: var(--card); text-decoration: none; }
.site-header .brand {
  display: inline-flex; align-items: center; gap: 8px;
  font-weight: 800; font-size: 17px; letter-spacing: -.01em; color: var(--fg);
}
.site-header .brand:hover { text-decoration: none; }
.site-header .brand-mark {
  display: block; width: 26px; height: 26px; border-radius: 6px;
}
.site-header nav { display: flex; align-items: center; gap: 2px; }
.site-header nav a {
  display: inline-block; padding: 7px 12px;
  color: var(--muted); font-size: 14px; border-radius: 999px;
  -webkit-tap-highlight-color: transparent;
}
.site-header nav a:hover { color: var(--fg); background: var(--card); text-decoration: none; }
.site-header nav a.active { background: var(--fg); color: #fff; }
.site-header nav a.active:hover { background: var(--fg); color: #fff; }
.site-header nav .gh-link { margin-left: 4px; }
/* 阅读设置入口：Aa 小按钮，视觉上不抢正文 */
.reader-settings { position: relative; display: inline-flex; align-items: center; }
.post-header .reader-settings { margin-left: auto; }
.reader-toggle {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 34px; height: 30px; padding: 0 8px;
  border: 0; border-radius: 999px; background: transparent;
  color: var(--muted); font-family: inherit; font-size: 13.5px; font-weight: 700;
  letter-spacing: .01em; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.reader-toggle:hover, .reader-toggle[aria-expanded="true"] {
  color: var(--fg); background: var(--card);
}
/* 目录页导航全是文字 tab，这里跟随导航的字号与内边距，避免视觉突兀 */
.site-header nav .reader-toggle {
  height: auto; padding: 7px 12px; line-height: 1.75;
  font-size: 14px; font-weight: 400; letter-spacing: 0;
}
.reader-panel {
  position: absolute; top: calc(100% + 8px); right: 0; z-index: 30;
  width: min(268px, calc(100vw - 32px));
  padding: 12px 16px;
  background: var(--bg); border: 1px solid var(--border-strong);
  border-radius: 12px; box-shadow: 0 12px 32px rgba(15, 20, 25, .12);
}
.reader-panel[hidden] { display: none; }
.reader-panel-title {
  margin: 0 0 6px; font-size: 11.5px; font-weight: 700;
  letter-spacing: .05em; color: var(--muted-2);
}
.reader-field {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 6px 0; font-size: 13.5px; color: var(--fg);
}
.reader-field input {
  width: 82px; padding: 5px 8px;
  border: 1px solid var(--border-strong); border-radius: 8px;
  background: var(--bg); color: var(--fg);
  font: inherit; font-size: 13px; text-align: right;
  font-variant-numeric: tabular-nums;
}
.reader-field input:focus {
  outline: 2px solid var(--link); outline-offset: 1px; border-color: transparent;
}
.reader-reset {
  width: 100%; margin-top: 8px; padding: 7px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--card); color: var(--muted);
  font: inherit; font-size: 12.5px; cursor: pointer;
}
.reader-reset:hover { background: var(--card-hover); color: var(--fg); }

/* 作者与标题 */
.author { display: flex; gap: 12px; align-items: center; margin: 2px 0 18px; }
.author img, .author .avatar-empty {
  flex: none; width: 46px; height: 46px; border-radius: 50%;
  object-fit: cover; background: var(--card);
}
.author .name { font-weight: 700; font-size: 16px; line-height: 1.45; }
.author .meta {
  color: var(--muted); font-size: 13.5px; line-height: 1.55; overflow-wrap: anywhere;
}
h1.title {
  font-size: clamp(26px, 4vw, 32px);
  line-height: 1.32; font-weight: 800; letter-spacing: -.012em;
  margin: 4px 0 16px;
  text-wrap: wrap;
  overflow-wrap: anywhere;
}

/* 正文：中文阅读以行高和段距为主，链接加淡淡下划线便于识别 */
.article {
  overflow-wrap: anywhere;
  font-size: calc(17px * var(--reader-fs));
  line-height: calc(1.75 * var(--reader-lh));
}
.article p { margin: 0 0 1.1em; white-space: normal; }
.article a {
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--link) 32%, transparent);
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}
.article a:hover { text-decoration-color: currentColor; }
.article h2 {
  font-size: calc(23px * var(--reader-fs)); line-height: 1.4; margin: 38px 0 14px;
  font-weight: 800; letter-spacing: -.008em;
}
.article h3 { font-size: calc(19.5px * var(--reader-fs)); line-height: 1.45; margin: 30px 0 10px; font-weight: 700; }
.article h4 { font-size: calc(17px * var(--reader-fs)); line-height: 1.5; margin: 24px 0 8px; font-weight: 700; }
.article ul, .article ol { padding-left: 1.35em; margin: 0 0 1.1em; }
.article li { margin: 4px 0; }
.article li::marker { color: var(--muted-2); }
.article figure.media { position: relative; margin: 20px 0; }
.article figure.media .media-link {
  display: block; overflow-x: auto; -webkit-overflow-scrolling: touch;
}
.article figure.media img {
  display: block; width: calc(100% * var(--img-zoom, 1)); max-width: none; height: auto;
  margin: 0 auto; border-radius: 12px;
  border: 1px solid var(--border); background: var(--card);
}
.article img { max-width: 100%; height: auto; }
.media-link { display: block; }
/* 正文图片缩放控件：按需出现在右下角，状态跨设备同步 */
.img-zoom-controls {
  position: absolute; right: 8px; bottom: 8px; z-index: 2;
  display: inline-flex; align-items: center; gap: 2px;
  padding: 2px; border-radius: 999px;
  background: rgba(15, 20, 25, .58);
  -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
  opacity: 0; visibility: hidden; pointer-events: none;
  transform: translateY(4px) scale(.97);
  transition: opacity .16s ease, transform .16s ease, visibility .16s ease;
}
.img-zoom-controls.is-visible {
  opacity: 1; visibility: visible; pointer-events: auto;
  transform: translateY(0) scale(1);
}
.img-zoom-btn {
  width: 28px; height: 28px; border: 0; border-radius: 50%;
  background: transparent; color: #fff; font-size: 18px; line-height: 1;
  font-family: inherit; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.img-zoom-btn:hover { background: rgba(255, 255, 255, .18); }
.img-zoom-btn:focus-visible { outline: 2px solid #fff; outline-offset: 1px; }
.img-zoom-preview { font-size: 15px; }
.img-zoom-field {
  display: inline-flex; align-items: center; justify-content: center;
  height: 24px; padding: 0 5px; border-radius: 999px;
  transition: background .15s ease, box-shadow .15s ease;
}
.img-zoom-field:focus-within {
  background: rgba(255, 255, 255, .18);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .55);
}
.img-zoom-input {
  width: 27px; padding: 0; border: 0; background: transparent;
  color: #fff; font-size: 11px; font-family: inherit; font-weight: 500;
  text-align: right; font-variant-numeric: tabular-nums; caret-color: #fff;
  -webkit-appearance: none; appearance: none;
}
.img-zoom-input:focus { outline: none; }
.img-zoom-pct { color: #fff; font-size: 11px; line-height: 1; }
/* 正文图片预览：点击图片外的区域关闭 */
body.img-lightbox-open { overflow: hidden; }
.img-lightbox {
  position: fixed; inset: 0; z-index: 100;
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
  background: rgba(8, 10, 12, .86);
  -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px);
  opacity: 0; transition: opacity .2s ease;
}
.img-lightbox[hidden] { display: none; }
.img-lightbox.is-open { opacity: 1; }
.img-lightbox-img {
  max-width: min(96vw, 1600px); max-height: 88vh;
  width: auto; height: auto;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, .45);
  transform: scale(.96);
  transition: transform .2s ease;
  object-fit: contain;
}
.img-lightbox.is-open .img-lightbox-img { transform: scale(1); }
.img-lightbox-close {
  position: absolute; top: 16px; right: 18px;
  width: 40px; height: 40px; border: 0; border-radius: 50%;
  background: rgba(255, 255, 255, .14); color: #fff;
  font-size: 24px; line-height: 1; font-family: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.img-lightbox-close:hover { background: rgba(255, 255, 255, .24); }
.article pre {
  background: #0f1419; color: #e7e9ea;
  margin: 18px 0; padding: 14px 16px; border-radius: 12px;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: calc(13px * var(--reader-fs)); line-height: 1.6;
}
.article pre code { font: inherit; color: inherit; }
.inline-code {
  padding: .1em .34em;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: #f6f8fa;
  color: #24364b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: .88em;
  line-height: 1.45;
  white-space: break-spaces;
  overflow-wrap: anywhere;
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
}
.article blockquote {
  margin: 18px 0; padding: 2px 0 2px 16px;
  border-left: 3px solid var(--border-strong);
  color: var(--muted);
}
.article .callout {
  margin: 22px 0; padding: 18px 20px;
  background: #f1f8fe;
  border: 1px solid #d5e8f8;
  border-left: 4px solid var(--link);
  border-radius: 12px;
}
.callout__title {
  margin-bottom: 10px;
  font-size: 13px; font-weight: 700; letter-spacing: .04em;
  color: var(--link);
}
.article .callout ul { margin: 0; padding-left: 20px; }
.article .callout li { margin: 6px 0; line-height: inherit; }
.article .callout p { margin: 8px 0 0; }
.table-wrap {
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  margin: 18px 0 22px;
}
.article table { border-collapse: collapse; width: 100%; font-size: calc(14px * var(--reader-fs)); line-height: 1.55; }
.article th, .article td {
  border: 1px solid var(--border); padding: 9px 12px;
  text-align: left; vertical-align: top;
}
.article th { background: var(--card); font-weight: 600; color: var(--fg); white-space: nowrap; }
.article td { overflow-wrap: anywhere; }
.article tbody tr:nth-child(even) td { background: #fbfcfd; }
.orig-link {
  display: inline-flex; align-items: center; gap: 4px;
  margin: 2px 0 22px; padding: 4px 0;
  font-size: 13.5px; color: var(--muted);
}
.orig-link:hover { color: var(--fg); }
.fidelity {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 12px 14px; margin: 28px 0 0;
  font-size: 12.5px; line-height: 1.65; color: var(--muted);
  overflow-wrap: anywhere;
}
.img-missing { color: #f4212e; font-size: 14px; }

/* 右侧目录：宽屏显示，整块可隐藏，可全折叠到只剩一级 */
html { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .img-zoom-controls { transition: none; }
}
/* 目录：宽屏固定侧栏；窄屏默认折叠，点「目录」按钮展开浮层 */
.toc {
  position: fixed; top: 92px; right: 16px; z-index: 20;
  width: 200px; max-width: 82vw; max-height: calc(100vh - 130px); overflow-y: auto;
  padding: 12px; border: 1px solid var(--border); border-radius: 12px;
  background: rgba(255, 255, 255, .95);
  -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  font-size: 12.5px; line-height: 1.55;
}
.toc-open {
  position: fixed; top: 92px; right: 16px; z-index: 21;
  display: inline-flex; align-items: center; justify-content: center;
  width: 42px; height: 42px; padding: 0;
  border: 0; background: transparent; color: var(--muted);
  cursor: grab; touch-action: none;
  -webkit-tap-highlight-color: transparent;
  -webkit-user-select: none; user-select: none;
}
.toc-open:hover { color: var(--fg); }
.toc-open.is-dragging { cursor: grabbing; opacity: .7; }
.toc-open-icon {
  width: 20px; height: 20px; pointer-events: none;
  fill: none; stroke: currentColor; stroke-width: 1.8;
  stroke-linecap: round; stroke-linejoin: round;
}
.toc[hidden], .toc-open[hidden] { display: none; }
.toc-head { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; }
.toc-title { flex: 1; font-weight: 700; color: var(--fg); font-size: 12.5px; }
.toc-fold, .toc-close {
  border: 0; background: none; padding: 2px 6px; border-radius: 6px;
  color: var(--muted); font: inherit; font-size: 11.5px; cursor: pointer;
}
.toc-fold:hover, .toc-close:hover { background: var(--card); color: var(--fg); }
.toc-close { font-size: 15px; line-height: 1; padding: 1px 6px; }
.toc-nav ul { list-style: none; margin: 0; padding: 0; }
.toc-nav .toc-l2-list {
  margin: 2px 0 2px 8px; padding-left: 8px; border-left: 1px solid var(--border);
}
.toc-nav a {
  display: block; padding: 3px 6px; border-radius: 6px;
  color: var(--muted); text-decoration: none; overflow-wrap: anywhere;
}
.toc-nav a:hover { color: var(--fg); background: var(--card); text-decoration: none; }
.toc-nav .toc-l1 { color: color-mix(in srgb, var(--fg) 84%, var(--link)); font-weight: 600; }
.toc.is-folded .toc-l2-list { display: none; }
h2[id], h3[id] { scroll-margin-top: 20px; }

/* 聊天记录：微信式左头像气泡；整块默认折叠，点击 summary 展开 */
.chat-block { display: flex; flex-direction: column; gap: 12px; margin: 22px 0 26px; }
.chat-appendix {
  border: 1px solid var(--border); border-radius: 12px; background: var(--card);
  overflow: hidden;
}
/* 作者样式里的 display 会盖过浏览器对 details 的默认隐藏，这里显式收起 */
.chat-appendix:not([open]) > :not(summary) { display: none; }
.chat-log {
  display: flex; flex-direction: column; gap: 18px;
  padding: 18px 20px;
}
.chat-msg {
  display: grid; grid-template-columns: 38px minmax(0, 1fr);
  align-items: start; gap: 10px; min-width: 0;
}
.chat-avatar {
  display: flex; align-items: center; justify-content: center;
  width: 38px; height: 38px; border-radius: 50%; overflow: hidden;
  background: var(--card); box-shadow: inset 0 0 0 1px rgba(15, 20, 25, .06);
}
.chat-avatar img { width: 100%; height: 100%; display: block; object-fit: cover; }
.chat-avatar__initial {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%; background: var(--chat-avatar-bg, #4a5568);
  color: #fff; font-size: 15px; font-weight: 750; line-height: 1;
}
.chat-message { min-width: 0; }
.chat-meta {
  display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 8px;
  margin: 0 0 5px; color: var(--muted); font-size: 13px; line-height: 1.45;
}
.chat-user { color: color-mix(in srgb, var(--fg) 84%, var(--muted)); font-weight: 700; }
.chat-time { color: var(--muted-2); font-size: 11.5px; font-weight: 400; }
.chat-bubble {
  position: relative; display: inline-block;
  max-width: min(100%, 680px); padding: 10px 14px;
  border: 1px solid #e0e9e2; border-radius: 4px 14px 14px 14px;
  background: #f1f7f2;
}
.chat-bubble::before {
  content: ""; position: absolute; top: 13px; left: -5px;
  width: 9px; height: 9px; border-left: 1px solid #e0e9e2;
  border-bottom: 1px solid #e0e9e2; background: #f1f7f2;
  transform: rotate(45deg);
}
.chat-text {
  color: var(--fg);
  font-size: calc(16px * var(--reader-fs));
  line-height: calc(1.7 * var(--reader-lh));
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.chat-appendix > summary {
  cursor: pointer; padding: 12px 16px;
  color: var(--muted); font-size: 14px; font-weight: 600; line-height: 1.6;
  list-style: none; user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.chat-appendix > summary::-webkit-details-marker { display: none; }
.chat-appendix > summary::before { content: "▸ "; color: var(--muted-2); }
.chat-appendix[open] > summary { border-bottom: 1px solid var(--border); }
.chat-appendix[open] > summary::before { content: "▾ "; }
.chat-note {
  padding: 14px 20px 0; color: var(--muted-2);
  font-size: 13px; line-height: 1.65;
}
@media (max-width: 640px) {
  .chat-log { padding: 14px; }
  .chat-note { padding: 12px 14px 0; }
  .chat-msg { grid-template-columns: 34px minmax(0, 1fr); gap: 8px; }
  .chat-avatar { width: 34px; height: 34px; }
  .chat-avatar__initial { font-size: 14px; }
  .chat-text { font-size: calc(15.5px * var(--reader-fs)); }
}

/* 目录：筛选与排序 */
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 20px; }
.filters button {
  border: 1px solid transparent; background: var(--card); border-radius: 999px;
  padding: 6px 13px; cursor: pointer; font-size: 13.5px; color: var(--muted);
  transition: background .12s ease, color .12s ease;
  -webkit-tap-highlight-color: transparent;
}
.filters button:hover { background: var(--card-hover); color: var(--fg); }
/* 分类筛选按钮（#filters 内 data-cat）比其余小按钮略大、颜色略偏链接色 */
.filters button[data-cat] {
  font-size: 14.5px; color: color-mix(in srgb, var(--fg) 82%, var(--link));
}
.filters button.active { background: var(--fg); color: #fff; border-color: var(--fg); }
.search {
  width: 100%; height: 44px; padding: 0 16px; margin-bottom: 12px;
  border: 1px solid var(--border); border-radius: 999px;
  background: var(--bg); color: var(--fg);
  font-size: 16px;
  transition: border-color .12s ease, box-shadow .12s ease;
}
.search::placeholder { color: var(--muted-2); }
.search:focus {
  outline: none; border-color: var(--link);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--link) 16%, transparent);
}
.index-intro { color: var(--muted); font-size: 14.5px; line-height: 1.75; margin: -6px 0 20px; }
.filter-bar { margin: 0 0 8px; }
.filter-toggle {
  width: 100%; display: flex; align-items: center; gap: 10px;
  padding: 11px 14px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--card); color: var(--fg); font: inherit; cursor: pointer; text-align: left;
  -webkit-tap-highlight-color: transparent;
}
.filter-toggle:hover { border-color: var(--border-strong); }
.filter-toggle-label { font-weight: 700; font-size: 14px; white-space: nowrap; }
.filter-summary {
  flex: 1; min-width: 0; color: var(--muted); font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.filter-toggle.has-active .filter-summary { color: var(--link); }
.filter-chevron { color: var(--muted); font-size: 12px; transition: transform .15s ease; }
.filter-toggle[aria-expanded="true"] .filter-chevron { transform: rotate(180deg); }
.filter-panel { padding: 2px 0 0; }
.filter-panel .filters { margin: 10px 0 12px; }
.filter-panel .filter-rows { margin-bottom: 8px; }
.filter-rows { display: flex; flex-direction: column; gap: 6px; margin: 6px 0 14px; }
.filter-row { display: flex; align-items: center; gap: 10px; }
.filter-row .flabel { flex: 0 0 34px; color: var(--muted); font-size: 12.5px; }
.filter-row .filters { margin: 0; gap: 6px; }
.filter-row .filters button { padding: 4px 11px; font-size: 12.5px; }
.meta-status { min-height: 1.2em; margin: -4px 0 16px; color: var(--muted); font-size: 12px; }
#meta-count { margin-left: 10px; }

/* 分类标题与卡片 */
.cat {
  grid-column: 1 / -1;
  display: flex; align-items: center; gap: 8px;
  margin: 26px 0 12px; padding: 10px 14px;
  border: 1px solid transparent; border-radius: 10px;
  background: var(--card);
  color: color-mix(in srgb, var(--fg) 80%, var(--link));
  font-size: 17px; font-weight: 700; user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.cat:hover { background: var(--card-hover); }
.cat .cat-toggle {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px;
  border: 0; padding: 0; background: transparent; color: inherit;
  font: inherit; text-align: left; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.cat .cat-toggle:focus-visible { outline: 2px solid var(--link); outline-offset: 3px; border-radius: 6px; }
.cat .cat-name { flex: 1; min-width: 0; }
.cat .cat-count {
  color: var(--muted); font-size: 12px; font-weight: 600; background: var(--bg);
  border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; white-space: nowrap;
}
.cat .cat-chevron { color: var(--muted); font-size: 12px; transition: transform .15s ease; }
.cat .cat-drag {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  border: 0; border-radius: 7px; background: transparent;
  color: var(--muted-2); cursor: grab; touch-action: none;
  -webkit-tap-highlight-color: transparent;
}
.cat .cat-drag:hover { background: var(--bg); color: var(--fg); }
.cat .cat-drag:focus-visible { outline: 2px solid var(--link); outline-offset: 1px; }
.cat .cat-drag[aria-disabled="true"] {
  opacity: .32; cursor: default; pointer-events: none;
}
.cat .cat-drag-icon { width: 15px; height: 15px; fill: currentColor; }
.cat.is-dragging {
  border-color: var(--link);
  box-shadow: 0 10px 30px rgba(15, 20, 25, .12);
  opacity: .76;
}
.cat.is-collapsed .cat-chevron { transform: rotate(-90deg); }
.cat.is-collapsed { background: transparent; }
.cat.is-static, .cat.is-static:hover { background: var(--card); }
.cat.is-static .cat-toggle { cursor: default; }
#list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
#list .cat { margin-top: 24px; }
#list .cat:first-child { margin-top: 4px; }
.card {
  position: relative;
  display: flex; flex-direction: column;
  padding: 16px 18px; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--bg); color: inherit;
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
  -webkit-tap-highlight-color: transparent;
}
.card:active { background: var(--card); }
@media (hover: hover) {
  .card:hover {
    border-color: var(--border-strong);
    box-shadow: 0 8px 24px rgba(15, 20, 25, .06);
  }
}
.card .ctitle {
  font-weight: 700; font-size: 16.5px; line-height: 1.5; margin-bottom: 7px;
  overflow-wrap: anywhere;
  padding-right: 38px; /* 给右上角图钉留位置 */
}
.card .cmeta {
  color: var(--muted); font-size: 12.5px; line-height: 1.5; margin-bottom: 8px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.list-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px 12px; margin: 2px 0 4px;
}
.list-count { color: var(--muted); font-size: 13px; }
.cat-order-hint { color: var(--muted-2); font-size: 12px; }
.empty-state {
  margin: 28px 0; padding: 32px 20px; text-align: center;
  border: 1px dashed var(--border-strong); border-radius: var(--radius);
  color: var(--muted); font-size: 14px;
}
.empty-state p { margin: 0 0 14px; }
.empty-state button {
  border: 1px solid var(--border); background: var(--bg); border-radius: 999px;
  padding: 6px 16px; font: inherit; font-size: 13px; color: var(--fg); cursor: pointer;
}
.empty-state button:hover { background: var(--card-hover); }
.list-actions { display: flex; gap: 8px; }
.list-actions button {
  border: 1px solid var(--border); background: var(--bg); border-radius: 999px;
  padding: 4px 11px; font: inherit; font-size: 12.5px; color: var(--muted); cursor: pointer;
}
.list-actions button:hover { color: var(--fg); border-color: var(--border-strong); }

/* 目录页置顶区 */
.pinned { margin: 18px 0 8px; }
.pinned-title { margin: 0 0 10px; font-size: 17px; font-weight: 700; color: var(--fg); }
.pinned-title.is-toggle {
  display: flex; align-items: center; gap: 8px;
  cursor: pointer; user-select: none; -webkit-tap-highlight-color: transparent;
}
.pinned-title.is-toggle .cat-chevron {
  color: var(--muted); font-size: 12px; transition: transform .15s ease;
}
.pinned.is-collapsed .pinned-title.is-toggle .cat-chevron { transform: rotate(-90deg); }
.pinned.is-collapsed .pinned-list { display: none; }
.pinned-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.pinned-item { display: block; }
.pinned-item .card { height: 100%; }
.footer {
  margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--border);
  color: var(--muted-2); font-size: 12px;
}

/* 评分 / 已读 */
.xr-stars { display: inline-flex; gap: 1px; line-height: 1; color: #cfd6dc; font-size: 12px; }
.xr-stars .xr-star { font-size: inherit; cursor: default; }
.xr-rating { display: inline-flex; gap: 2px; align-items: center; }
.xr-star {
  appearance: none; -webkit-appearance: none; border: 0; background: none;
  padding: 3px 2px; margin: 0; font-family: inherit; font-size: 24px; line-height: 1;
  color: #cfd6dc; cursor: pointer; transition: color .12s ease, transform .12s ease;
  -webkit-tap-highlight-color: transparent;
}
.xr-star.on { color: var(--star); }
.xr-rating .xr-star:hover { transform: translateY(-1px) scale(1.08); }
.xr-star:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; border-radius: 6px; }
.card-badges { display: inline-flex; align-items: center; gap: 6px; margin-left: 8px; vertical-align: middle; }
.badge-read {
  background: var(--ok-soft); color: var(--ok); font-size: 11px; font-weight: 600;
  line-height: 1.6; padding: 0 7px; border-radius: 999px;
}
/* 卡片右上角图钉：未置顶为灰色空心，已置顶仅换橙色，不加底色 */
.card-pin {
  position: absolute; top: 10px; right: 10px; z-index: 2;
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 999px;
  border: 1px solid transparent; background: transparent; color: var(--muted);
  cursor: pointer; transition: background .12s ease, color .12s ease, border-color .12s ease;
  -webkit-tap-highlight-color: transparent;
}
.card-pin:hover { color: var(--fg); }
.card-pin.on { color: #b45309; }
.card-pin-icon { display: block; width: 15px; height: 15px; }
.source-badge {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: 8px; vertical-align: middle;
  border: 1px solid var(--border); border-radius: 999px; padding: 0 7px;
  color: var(--muted); font-size: 11px; font-weight: 600;
  line-height: 1.7; white-space: nowrap;
}
/* 文章页分类标签：与「查看原文」同一行、同字号，点击回目录定位分类 */
.post-meta-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px;
  margin: 0 0 12px;
}
.post-meta-row .orig-link { margin: 0; }
.post-meta-row .source-badge { margin-left: 0; }
.cat-badge {
  display: inline-flex; align-items: center;
  border: 0; padding: 0;
  color: var(--muted-2); font-size: 13px; font-weight: 500;
  line-height: 1.6; white-space: nowrap;
}
.cat-badge::before { content: "分类："; color: var(--muted-2); }
.cat-badge:hover { color: var(--link); text-decoration: none; }
.tag-list {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  margin: 0 0 14px;
}
.tag-list--compact { gap: 5px; margin: 9px 0 0; }
.tag-list__label {
  color: var(--muted-2); font-size: 12px; font-weight: 600;
  margin-right: 2px;
}
.tag-badge {
  display: inline-flex; align-items: center;
  border: 1px solid var(--border); border-radius: 6px;
  padding: 1px 7px; background: #fafbfc;
  color: var(--muted); font-size: 11.5px; font-weight: 500;
  line-height: 1.65;
}
.tag-list--compact .tag-badge { padding: 0 6px; font-size: 11px; }
.source-badge .src-icon {
  display: inline-block; width: 12px; height: 12px;
  font-size: 11px; line-height: 1; text-align: center;
}
.source-badge svg.src-icon { fill: none; stroke: currentColor; stroke-width: 1.2; }
.card-linkonly { cursor: default; }
.card-linkonly .ctitle a { color: inherit; }
.card-linkonly .ctitle a:hover { color: var(--link); text-decoration: underline; }
/* 徽标按来源类型配色：淡底深字 */
.source-badge[data-source-type="x_article"] {
  background: #f2ecfc; color: #6b21c4; border-color: #e2d5f5;
}
.source-badge[data-source-type="x_post"] {
  background: #fff1e6; color: #c2410c; border-color: #f6dcc3;
}
.source-badge[data-source-type="web_article"] {
  background: #e9f2f1; color: #1f5f5b; border-color: #d2e3e1;
}
.source-badge[data-source-type="talk"] {
  background: #e8f4ff; color: #0b63a8; border-color: #cfe6fa;
}
.source-badge[data-source-type="webcafe"] {
  background: #eef4ff; color: #1d4ed8; border-color: #dbe7ff;
}
.source-badge[data-source-type="wechat"] {
  background: #e8f7ee; color: #14803c; border-color: #cfead9;
}
.source-badge[data-source-type="reddit"] {
  background: #fff0e8; color: #c93a00; border-color: #ffd5c0;
}
.source-badge[data-source-type="reddit"] svg.src-icon { color: #ff4500; }
.source-badge[data-source-type="note"] {
  background: #fff8e1; color: #9a6700; border-color: #f2e3b3;
}
.card-controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px;
  margin-top: 8px; font-size: 13px;
}
.card-controls .cc-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.card-controls .xr-star { font-size: 19px; padding: 4px 3px; }
.card-controls .pc-read { padding: 4px 11px; font-size: 12.5px; }
.post-controls {
  --post-rating-size: 13.5px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px;
  margin: 0 0 12px; padding: 0;
  background: transparent; border: 0; border-radius: 0;
  font-size: 14px;
}
.post-controls .pc-row { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.post-controls .pc-label { color: var(--muted); font-size: var(--post-rating-size); }
.post-controls .xr-star {
  padding: 1px; font-size: var(--post-rating-size); line-height: 1;
}
.post-controls .pc-rating-text { color: var(--muted); font-size: 12.5px; }
.post-controls .pc-read {
  border: 0; background: transparent; padding: 3px 0;
}
.post-controls .pc-read:hover { color: var(--fg); text-decoration: underline; }
.post-controls .pc-read.on {
  background: transparent; border: 0; color: var(--ok);
}
.post-controls .pc-pin {
  width: 28px; height: 28px; padding: 0; justify-content: center;
  border: 0; background: transparent;
}
.post-controls .pc-pin.on { background: transparent; color: #b45309; }
.pc-read {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); background: var(--bg); color: var(--muted);
  border-radius: 999px; padding: 5px 12px; font-size: 13px; font-family: inherit;
  cursor: pointer; transition: background .12s ease, color .12s ease, border-color .12s ease;
  -webkit-tap-highlight-color: transparent;
}
.pc-read:hover { border-color: var(--border-strong); color: var(--fg); }
.pc-read.on { background: var(--ok-soft); border-color: #b7e0c6; color: var(--ok); font-weight: 600; }
.pc-read .pc-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; opacity: .45; }
.pc-read.on .pc-dot { opacity: 1; }
.pc-pin {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); background: var(--bg); color: var(--muted);
  border-radius: 999px; padding: 5px 12px; font-size: 13px; font-family: inherit;
  cursor: pointer; transition: background .12s ease, color .12s ease, border-color .12s ease;
  -webkit-tap-highlight-color: transparent;
}
.pc-pin:hover { border-color: var(--border-strong); color: var(--fg); }
.pc-pin.on { background: #fff4e5; border-color: #f0d3a8; color: #b45309; font-weight: 600; }
.pc-pin-icon { display: block; width: 13px; height: 13px; flex: none; }
.card-controls .pc-pin { padding: 4px 11px; font-size: 12.5px; }

/* 网站收藏 */
#sites { display: block; }
.site-group { margin: 0 0 26px; }
.site-group .cat { margin: 0 0 12px; }
.sites-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.site-card {
  display: flex; align-items: center; gap: 8px;
  padding: 13px 12px 13px 15px; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--bg); color: inherit;
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
  -webkit-tap-highlight-color: transparent;
}
.site-main {
  flex: 1; min-width: 0;
  display: flex; align-items: center; gap: 12px;
  color: inherit;
}
.site-card:active { background: var(--card); }
@media (hover: hover) {
  .site-card:hover {
    border-color: var(--border-strong);
    box-shadow: 0 8px 24px rgba(15, 20, 25, .06);
  }
  .site-main:hover { text-decoration: none; }
}
.site-pin {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 999px;
  border: 1px solid transparent; background: transparent; color: var(--muted);
  cursor: pointer; transition: background .12s ease, color .12s ease, border-color .12s ease;
  -webkit-tap-highlight-color: transparent;
}
.site-pin:hover { background: var(--card); color: var(--fg); }
.site-pin.on { color: #b45309; }
.site-pin-icon { display: block; width: 15px; height: 15px; }
.site-logo {
  flex: none; width: 40px; height: 40px; border-radius: 10px;
  object-fit: contain; background: var(--card);
}
.site-logo-fallback {
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700; color: var(--muted);
}
.site-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.site-title { font-weight: 600; font-size: 15.5px; line-height: 1.4; overflow-wrap: anywhere; }
.site-host { color: var(--muted); font-size: 12.5px; line-height: 1.4; overflow-wrap: anywhere; }

/* 手机端：单列、更大触控区、正文不出现横向滚动 */
@media (max-width: 760px) {
  #list { grid-template-columns: 1fr; }
  .pinned-list { grid-template-columns: 1fr; }
  .sites-grid { grid-template-columns: 1fr; }
  .index-wrap { max-width: 700px; }
}
@media (max-width: 560px) {
  :root { --pad-x: 16px; --header-h: 52px; }
  body { line-height: 1.8; }
  .wrap { padding-bottom: 56px; }
  .site-header { margin-bottom: 20px; }
  .site-header .brand { font-size: 16.5px; }
  .site-header .brand-mark { width: 24px; height: 24px; }
  .site-header nav .gh-link { display: none; }
  .site-header nav a { padding: 6px 10px; font-size: 13.5px; }
  .site-header nav .reader-toggle { padding: 6px 10px; font-size: 13.5px; }
  /* 行宽只对桌面有意义，移动端不显示这一项 */
  .reader-field--width { display: none; }
  h1.title { font-size: 25px; line-height: 1.36; margin-bottom: 14px; }
  .index-wrap h1.title { font-size: 24px; }
  .author { margin-bottom: 16px; }
  .author img, .author .avatar-empty { width: 42px; height: 42px; }
  .article { line-height: calc(1.85 * var(--reader-lh)); }
  .article h2 { font-size: calc(21px * var(--reader-fs)); margin: 32px 0 12px; }
  .article h3 { font-size: calc(18.5px * var(--reader-fs)); margin: 26px 0 9px; }
  .article h4 { font-size: calc(16.5px * var(--reader-fs)); margin: 22px 0 8px; }
  .article pre {
    white-space: pre-wrap; overflow-wrap: anywhere;
    font-size: calc(12.5px * var(--reader-fs)); padding: 12px 14px;
  }
  .article figure.media { margin: 18px -4px; }
  .article table { font-size: calc(13.5px * var(--reader-fs)); }
  .article th, .article td { padding: 8px 10px; }
  .post-controls { gap: 8px 12px; }
  .card-controls .xr-star { font-size: 22px; padding: 5px 3px; }
  .pc-read { padding: 7px 14px; }
  .card-controls .pc-read { padding: 6px 12px; }
  .card { padding: 15px 16px; }
  .card .cmeta { white-space: normal; }
  .pinned-title { font-size: 16px; }
  .pc-pin { padding: 7px 14px; }
  .card-controls .pc-pin { padding: 6px 12px; }
  .filters button { padding: 8px 14px; font-size: 14px; }
  .filter-row { align-items: flex-start; }
  .filter-row .flabel { flex-basis: 34px; padding-top: 8px; font-size: 12.5px; }
  .filter-row .filters button { padding: 7px 12px; font-size: 13px; }
  .list-actions button { padding: 6px 12px; min-height: 32px; }
  .footer { margin-top: 40px; }
}
"""


def post_page(meta: dict, body_html: str, toc_html: str = "") -> str:
    # description 只在 meta 标签使用；未填写时自动取正文前 80 字，避免每次人工总结
    description = (meta.get("description") or "").strip()
    if not description:
        snippet = BeautifulSoup(body_html, "html.parser")
        for avatar in snippet.select(".chat-avatar"):
            avatar.decompose()
        for chat in snippet.select(".chat-appendix"):
            for label in chat.select("summary, .chat-note"):
                label.decompose()
        description = re.sub(r"\s+", " ", snippet.get_text(" ", strip=True)).strip()[:80]
    post_assets = ROOT / "posts" / meta["slug"] / "assets"
    avatar = meta.get("avatar_local")
    if source_type_of(meta) == "note":
        # 自建笔记统一用站主的固定头像
        avatar_html = (
            '<img src="../../assets/note-avatar.jpg" alt="" width="46" height="46" '
            'loading="lazy" decoding="async" />'
        )
    else:
        avatar_html = (
            image_html(f"assets/{avatar}", "", assets_dir=post_assets)
            if avatar
            else '<span class="avatar-empty" aria-hidden="true"></span>'
        )
    cover = meta.get("cover_local")
    cover_html = (
        f'<figure class="media">'
        f'<a class="media-link" href="assets/{esc(cover)}" target="_blank" rel="noopener" '
        f'aria-label="查看大图">'
        f'{image_html(f"assets/{cover}", "封面", assets_dir=post_assets, lazy=True, responsive=True)}</a>'
        f'</figure>'
        if cover and meta.get("cover_separate")
        else ""
    )
    handle = author_handle(meta)
    handle_html = f' <span class="meta">{handle}</span>' if handle else ""
    orig_link_html = (
        f'<a class="orig-link" href="{esc(meta["url"])}" target="_blank" rel="noopener">'
        f'{original_link_text(meta)}</a>'
        if meta.get("url")
        else ""
    )
    # 分类标签：放在原文链接右侧，点击回目录并定位到该分类
    cat_badge_html = (
        f'<a class="cat-badge" href="../../?cat={urllib.parse.quote(meta["category"])}" '
        f'title="返回目录 · {esc(meta["category"])}">{esc(meta["category"])}</a>'
    )
    post_links_html = (
        f'<div class="post-meta-row">{orig_link_html}{source_badge(meta)}{cat_badge_html}</div>'
    )
    tags_row_html = ""  # 网页不再展示关键词，只保留分类 Category
    toc_script = (
        f'<script src="../../assets/toc.js?v={asset_version("assets/toc.js")}" defer></script>'
        if toc_html
        else ""
    )
    zoom_script = (
        f'<script src="../../assets/image-zoom.js?v={asset_version("assets/image-zoom.js")}" defer></script>'
    )
    # 原创笔记不是镜像，不显示镜像说明
    fidelity_html = ""
    if source_type_of(meta) != "note":
        fidelity_html = (
            '<div class="fidelity">\n'
            '    镜像说明：正文与图片按原文顺序本地托管；图片优先下载 orig 分辨率。\n'
            f'    已镜像图片 {meta.get("images_ok",0)}/{meta.get("images_total",0)}。\n'
            f'    {esc(meta.get("fidelity_note") or "")}\n'
            '  </div>'
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#ffffff" />
<title>{esc(meta['title'])} · X Mirror</title>
<meta name="description" content="{esc(description)}" />
<link rel="icon" href="../../assets/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="../../assets/logo.svg" />
<link rel="icon" type="image/png" sizes="32x32" href="../../assets/favicon-32.png" />
<link rel="apple-touch-icon" href="../../assets/apple-touch-icon.png" />
<link rel="manifest" href="../../site.webmanifest" />
<link rel="stylesheet" href="../../assets/site.css?v={asset_version('assets/site.css')}" />
</head>
<body class="post-page">
<div class="wrap">
  <header class="site-header post-header">
    <a class="back-link" href="../../">← 目录</a>
    <div class="reader-settings">
      <button type="button" class="reader-toggle" aria-label="阅读设置" aria-expanded="false" aria-controls="reader-panel" data-reader-toggle>Aa</button>
    </div>
  </header>
  <div class="author">
    {avatar_html}
    <div>
      <div class="name">{esc(meta['author_name'])}{handle_html}</div>
      <div class="meta">{esc(meta['published_local'])}</div>
    </div>
  </div>
  <h1 class="title">{render_inline_text(clean_heading_text(meta['title']))}</h1>
  {post_links_html}
  {tags_row_html}
  <div class="post-controls" data-meta-mount data-slug="{esc(meta['slug'])}"></div>
  {cover_html}
  <article class="article">
{body_html}
  </article>
  {fidelity_html}
  <div class="footer">Personal archive mirror · not affiliated with X/Twitter</div>
</div>
{toc_html}
<script src="../../assets/meta.js?v={asset_version('assets/meta.js')}" defer></script>
<script src="../../assets/reader-settings.js?v={asset_version('assets/reader-settings.js')}" defer></script>
{zoom_script}
{toc_script}
</body>
</html>
"""


# 目录页：Chrome 在悬停/触摸卡片时提前拉取文章页，减少点击后的等待。
# 只 prefetch（不 prerender），避免提前执行文章页脚本产生副作用。
SPECULATION_PREFETCH = """<script type="speculationrules">
{
  "prefetch": [{
    "where": {"selector_matches": ".card[href^='posts/']"},
    "eagerness": "moderate"
  }]
}
</script>"""


def header_html(active: str) -> str:
    """目录页顶部导航：文章 / 网站 两个 tab。active 取 posts 或 sites。"""
    posts_cls = "tab active" if active == "posts" else "tab"
    sites_cls = "tab active" if active == "sites" else "tab"
    posts_aria = ' aria-current="page"' if active == "posts" else ""
    sites_aria = ' aria-current="page"' if active == "sites" else ""
    return f"""<header class="site-header">
    <a class="brand" href="./"><img class="brand-mark" src="assets/logo.svg" alt="" width="26" height="26" />X Mirror</a>
    <nav>
      <a class="{posts_cls}" href="./"{posts_aria}>文章</a>
      <a class="{sites_cls}" href="sites.html"{sites_aria}>网站</a>
      <div class="reader-settings">
        <button type="button" class="reader-toggle" aria-label="阅读设置" aria-expanded="false" aria-controls="reader-panel" data-reader-toggle>设置</button>
      </div>
      <a class="gh-link" href="https://github.com/wentao-hu/x-mirror">GitHub</a>
    </nav>
  </header>"""


def load_sites() -> list[dict]:
    if not SITES_FILE.exists():
        return []
    raw = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    return raw.get("sites", [])


def site_host(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def site_logo_html(site: dict) -> str:
    logo = site.get("logo")
    if logo:
        return (
            f'<img class="site-logo" src="{esc(logo)}" alt="" width="40" height="40" '
            f'loading="lazy" decoding="async" />'
        )
    letter = esc((site.get("title") or "?")[:1].upper())
    return f'<span class="site-logo site-logo-fallback" aria-hidden="true">{letter}</span>'


def sites_page(sites: list[dict]) -> str:
    cats = [c for c in SITE_CATEGORY_ORDER if any(s["category"] == c for s in sites)]
    for s in sites:
        if s["category"] not in cats:
            cats.append(s["category"])
    groups = []
    for c in cats:
        cards = []
        for s in sites:
            if s["category"] != c:
                continue
            cards.append(
                f"""<div class="site-card" data-slug="site-{esc(s['slug'])}">
      <a class="site-main" href="{esc(s['url'])}" target="_blank" rel="noopener noreferrer">
        {site_logo_html(s)}
        <span class="site-info">
          <span class="site-title">{esc(s['title'])}</span>
          <span class="site-host">{esc(site_host(s['url']))}</span>
        </span>
      </a>
      <button type="button" class="site-pin" aria-pressed="false" aria-label="置顶 {esc(s['title'])}" title="置顶">
        <svg class="site-pin-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M8 1.6a3.6 3.6 0 0 0-3.6 3.6c0 2.5 2.6 4.8 3.6 5.7 1-.9 3.6-3.2 3.6-5.7A3.6 3.6 0 0 0 8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
          <path d="M8 10.9v3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </button>
    </div>"""
            )
        groups.append(
            f'<section class="site-group">\n'
            f'<h2 class="cat is-static"><span class="cat-name">{esc(c)}</span>'
            f'<span class="cat-count">{len(cards)} 个</span></h2>\n'
            f'<div class="sites-grid">\n' + "\n".join(cards) + "\n</div>\n</section>"
        )
    body = (
        "\n".join(groups)
        if groups
        else '<p class="index-intro">还没有收藏网站，编辑 sites.json 后重新生成。</p>'
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#ffffff" />
<title>网站收藏 · X Mirror</title>
<meta name="description" content="收藏的有用网站：SEO 内容站、工具站、域名注册、支付等，按用途分类。" />
<link rel="icon" href="assets/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="assets/logo.svg" />
<link rel="icon" type="image/png" sizes="32x32" href="assets/favicon-32.png" />
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png" />
<link rel="manifest" href="site.webmanifest" />
<link rel="stylesheet" href="assets/site.css?v={asset_version('assets/site.css')}" />
</head>
<body>
<div class="wrap index-wrap">
  {header_html('sites')}
  <section class="pinned" id="sites-pinned" hidden>
    <h2 class="pinned-title is-toggle" id="sites-pinned-toggle" role="button" tabindex="0" aria-expanded="true">
      <span>置顶</span><span class="cat-chevron" aria-hidden="true">▾</span>
    </h2>
    <div class="pinned-list" id="sites-pinned-list"></div>
  </section>
  <div id="sites">
{body}
  </div>
  <div class="footer">共 {len(sites)} 个网站 · Personal archive</div>
</div>
<script src="assets/meta.js?v={asset_version('assets/meta.js')}" defer></script>
<script src="assets/sites.js?v={asset_version('assets/sites.js')}" defer></script>
<script src="assets/reader-settings.js?v={asset_version('assets/reader-settings.js')}" defer></script>
</body>
</html>
"""


def index_page(posts: list[dict]) -> str:
    unknown = sorted({
        p.get("category", "")
        for p in posts
        if p.get("entry_type") != "link_only"
        and p.get("category") not in CATEGORY_ORDER
    })
    if unknown:
        raise CategoryTaxonomyError(
            "目录中存在未知文章分类: "
            + ", ".join(repr(value) for value in unknown)
            + f"；允许值: {', '.join(CATEGORY_ORDER)}"
        )
    cats = [c for c in CATEGORY_ORDER if any(p["category"] == c for p in posts)]
    for p in posts:
        if p.get("entry_type") == "link_only" and p["category"] not in cats:
            cats.append(p["category"])
    filter_btns = ['<button class="active" data-cat="all">全部</button>'] + [
        f'<button data-cat="{esc(c)}" title="{esc(CATEGORY_DEFINITIONS.get(c, "文章分类"))}">'
        f'{esc(c)}</button>' for c in cats
    ]
    sections = []
    for c in cats:
        cards = []
        for p in posts:
            if p["category"] != c:
                continue
            q = esc(
                " ".join(
                    [
                        p["title"],
                        p["author_name"],
                        p["author_username"],
                        p.get("description", ""),
                        *meta_tags(p),
                    ]
                )
            )
            date = esc(p['published_local'][:16])
            if p.get("entry_type") == "link_only":
                # 仅链接条目：标题直接外链原文，正文/图片一律不镜像
                # 首页卡片只显示作者名和日期；账号 ID 留到详情页展示
                cmeta = f"{esc(p['author_name'])} · {date}"
                cards.append(
                    f"""<div class="card card-linkonly" data-slug="{esc(p['slug'])}" data-source-type="{esc(source_type_of(p))}" data-cat="{esc(c)}" data-published="{esc(p.get('published_utc',''))}" data-q="{q}">
  <div class="ctitle"><a href="{esc(p['url'])}" target="_blank" rel="noopener noreferrer">{esc(p['title'])}</a>{source_badge(p)}</div>
  <div class="cmeta">{cmeta}</div>
  <div class="card-controls" data-meta-mount data-slug="{esc(p['slug'])}"></div>
</div>"""
                )
            else:
                cards.append(
                    f"""<a class="card" data-slug="{esc(p['slug'])}" data-source-type="{esc(source_type_of(p))}" data-cat="{esc(c)}" data-published="{esc(p.get('published_utc',''))}" data-q="{q}" href="posts/{esc(p['slug'])}/">
  <div class="ctitle">{esc(p['title'])}{source_badge(p)}</div>
  <div class="cmeta">{esc(p['author_name'])} · {date}</div>
</a>"""
                )
        sections.append(
            f'<h2 class="cat" data-cat="{esc(c)}" '
            f'title="{esc(CATEGORY_DEFINITIONS.get(c, "文章分类"))}">'
            f'<button type="button" class="cat-toggle" aria-expanded="true" '
            f'title="展开或折叠 {esc(c)}">'
            f'<span class="cat-name">{esc(c)}</span>'
            f'<span class="cat-count">{len(cards)} 篇</span>'
            f'<span class="cat-chevron" aria-hidden="true">▾</span>'
            f'</button>'
            f'<button type="button" class="cat-drag" '
            f'aria-label="拖动调整 {esc(c)} 分类顺序" '
            f'title="拖动调整分类顺序；聚焦后可用方向键">'
            f'<svg class="cat-drag-icon" viewBox="0 0 16 16" aria-hidden="true">'
            f'<circle cx="5" cy="4" r="1.2"/><circle cx="11" cy="4" r="1.2"/>'
            f'<circle cx="5" cy="8" r="1.2"/><circle cx="11" cy="8" r="1.2"/>'
            f'<circle cx="5" cy="12" r="1.2"/><circle cx="11" cy="12" r="1.2"/>'
            f'</svg></button></h2>\n'
            + "\n".join(cards)
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#ffffff" />
<title>X Mirror · 出海 SEO 收藏镜像</title>
<meta name="description" content="出海 SEO 收藏镜像：X、web.cafe、微信公众号与原创整理笔记本地化，图片全部本地托管" />
<link rel="icon" href="assets/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="assets/logo.svg" />
<link rel="icon" type="image/png" sizes="32x32" href="assets/favicon-32.png" />
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png" />
<link rel="manifest" href="site.webmanifest" />
{SPECULATION_PREFETCH}
<link rel="stylesheet" href="assets/site.css?v={asset_version('assets/site.css')}" />
</head>
<body>
<div class="wrap index-wrap">
  {header_html('posts')}
  <input class="search" id="q" type="search" placeholder="搜索标题 / 作者…" />
  <div class="filter-bar">
    <button class="filter-toggle" id="filter-toggle" type="button" aria-expanded="false" aria-controls="filter-panel">
      <span class="filter-toggle-label">筛选与排序</span>
      <span class="filter-summary" id="filter-summary">全部</span>
      <span class="filter-chevron" aria-hidden="true">▾</span>
    </button>
  </div>
  <div class="filter-panel" id="filter-panel" hidden>
    <div class="filters" id="filters">{''.join(filter_btns)}</div>
    <div class="filter-rows">
      <div class="filter-row">
        <span class="flabel">类型</span>
        <div class="filters" data-meta-filter="type">
          <button data-type="all" class="active">全部</button>
          <button data-type="x_post">帖子</button>
          <button data-type="x_article">长文</button>
          <button data-type="talk">演讲展示</button>
          <button data-type="web_article">网页</button>
          <button data-type="webcafe">web.cafe</button>
          <button data-type="wechat">微信</button>
          <button data-type="reddit">Reddit</button>
          <button data-type="note">自建笔记</button>
        </div>
      </div>
      <div class="filter-row">
        <span class="flabel">评分</span>
        <div class="filters" data-meta-filter="rating">
          <button data-rating="all" class="active">全部</button>
          <button data-rating="0">未评分</button>
          <button data-rating="1">≥1★</button>
          <button data-rating="2">≥2★</button>
          <button data-rating="3">≥3★</button>
          <button data-rating="4">≥4★</button>
          <button data-rating="5">5★</button>
        </div>
      </div>
      <div class="filter-row">
        <span class="flabel">阅读</span>
        <div class="filters" data-meta-filter="read">
          <button data-read="all" class="active">全部</button>
          <button data-read="yes">已读完</button>
          <button data-read="no">未读</button>
        </div>
      </div>
      <div class="filter-row">
        <span class="flabel">时间</span>
        <div class="filters" data-meta-filter="time">
          <button data-time="all" class="active">全部</button>
          <button data-time="1d">最近 1 天</button>
          <button data-time="3d">最近 3 天</button>
          <button data-time="30d">最近 1 个月</button>
          <button data-time="90d">最近 3 个月</button>
        </div>
      </div>
      <div class="filter-row">
        <span class="flabel">排序</span>
        <div class="filters" data-meta-filter="sort">
          <button data-sort="default" class="active">默认</button>
          <button data-sort="new">从新到旧</button>
          <button data-sort="rating">评分高→低</button>
          <button data-sort="unread">未读优先</button>
        </div>
      </div>
    </div>
  </div>
  <div class="meta-status"><span id="meta-count"></span></div>
  <div class="list-toolbar">
    <span class="list-count">共 {len(posts)} 篇</span>
    <span class="cat-order-hint">拖动分类右侧手柄排序，聚焦后也可用方向键</span>
    <div class="list-actions" id="list-actions">
      <button type="button" id="expand-all">全部展开</button>
      <button type="button" id="collapse-all">全部折叠</button>
    </div>
  </div>
  <section class="pinned" id="pinned" hidden>
    <h2 class="pinned-title is-toggle" id="pinned-toggle" role="button" tabindex="0" aria-expanded="true">
      <span>置顶</span><span class="cat-chevron" aria-hidden="true">▾</span>
    </h2>
    <div class="pinned-list" id="pinned-list"></div>
  </section>
  <div id="list">
{''.join(sections)}
  </div>
  <div class="footer">共 {len(posts)} 篇 · 时间均为北京时间（UTC+8） · Personal archive</div>
</div>
<script src="assets/meta.js?v={asset_version('assets/meta.js')}" defer></script>
<script src="assets/reader-settings.js?v={asset_version('assets/reader-settings.js')}" defer></script>
</body>
</html>
"""


def parse_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ8)
    return dt.strftime("%Y-%m-%d %H:%M")


def process_one(post_api: dict, users: dict) -> dict:
    pid = post_api["id"]
    art = post_api["article"]
    user = users[post_api["author_id"]]
    work = WORKDIRS[pid]
    slug = SLUGS[pid]
    out_dir = POSTS / slug
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    soup = BeautifulSoup(
        open(f"{work}/page.html", encoding="utf-8", errors="replace").read(), "lxml"
    )
    container, title_dom, cover_imgs = find_article_container(soup)
    title = art.get("title") or title_dom
    blocks = walk_blocks(container)
    # Prepend cover image(s) if not already first in body
    cover_blocks = []
    for img in cover_imgs:
        src = img.get("src") or ""
        if "/media/" not in src:
            continue
        import re as _re
        m = _re.search(r"/media/([A-Za-z0-9_-]+)", src)
        key = m.group(1) if m else src
        if any(b.get("key") == key for b in blocks if b["type"] == "image"):
            continue
        cover_blocks.append({
            "type": "image",
            "src": src,
            "orig_url": orig_url(src),
            "alt": (img.get("alt") or "封面").strip() or "封面",
            "key": key,
        })
    blocks = cover_blocks + blocks
    # Always put title heading first for consistency
    if not any(b.get("type") == "heading" and b.get("level") == 1 for b in blocks):
        blocks = [{"type": "heading", "level": 1, "text": title}] + blocks
    blocks = enrich_from_plain_text(
        blocks, art.get("plain_text") or "", art.get("entities") or {}
    )

    # Ensure cover is first image if not already present
    cover_id = art.get("cover_media")  # like 3_...
    # We don't have direct mapping from media id to pbs code; cover is usually first /media/ in DOM
    # Download all images
    images_total = 0
    images_ok = 0
    missing = []
    for b in blocks:
        if b["type"] != "image":
            continue
        images_total += 1
        ext = "jpg"
        local = f"{b['key']}.{ext}"
        dest = assets / local
        ok = download(b["orig_url"], dest)
        if not ok:
            # try without query from original src
            ok = download(b["src"].split("?")[0] + "?format=jpg&name=large", dest)
        if ok:
            # fix extension via mime
            ext = sniff_ext(dest)
            if ext != "jpg":
                new = f"{b['key']}.{ext}"
                dest.rename(assets / new)
                local = new
            b["local"] = local
            images_ok += 1
        else:
            missing.append(b["key"])
            b["local"] = None

    # avatar
    avatar_url = user.get("profile_image_url") or ""
    avatar_local = None
    if avatar_url:
        avatar_url = orig_url(avatar_url)
        avatar_local = "avatar.jpg"
        if not download(avatar_url, assets / avatar_local):
            # try original
            if not download(user.get("profile_image_url"), assets / avatar_local):
                avatar_local = None

    # Also download any media_entities that HTML missed: try to resolve via page images list
    api_media_n = len(art.get("media_entities") or []) + (
        1 if art.get("cover_media") else 0
    )

    fidelity_note = ""
    if pid == "2109883678897909932":
        fidelity_note = (
            "作者注明 X 上传图片有限制，后半段在 X 上可能加载不全；完整带图版见飞书："
            "https://qcnj3k0hgb3d.feishu.cn/wiki/BqrRwoyjDidlcLk6H7FcVN0unnc"
        )
    if missing:
        fidelity_note += f" 未能下载的图片 key: {', '.join(missing)}。"

    # Drop duplicate H1 from blocks in body
    body_blocks = [b for b in blocks if not (b["type"] == "heading" and b.get("level") == 1)]
    # If first image is cover duplicated in body, keep it (matches X article layout)

    generate_all(ROOT)
    toc_html = render_toc_html(body_blocks)
    body_html = render_blocks_html(body_blocks, "assets", assets)

    published = parse_time(post_api["created_at"])
    meta = {
        "id": pid,
        "slug": slug,
        "title": title,
        "url": f"https://x.com/{user['username']}/status/{pid}",
        "author_name": user.get("name") or user["username"],
        "author_username": user["username"],
        "published_utc": post_api["created_at"],
        "published_local": published,
        "category": CATEGORIES[pid],
        "description": DESCS[pid],
        "source_type": "x_post",  # 当前抽取流程均为普通推文；X 长文/网页来源在 data/*.json 标注
        "avatar_local": avatar_local,
        "images_total": images_total,
        "images_ok": images_ok,
        "api_media_count": api_media_n,
        "fidelity_note": fidelity_note.strip(),
        "plain_text_len": len(art.get("plain_text") or ""),
        "blocks_count": len(blocks),
    }

    # save raw for rebuild
    raw = {
        "meta": meta,
        "blocks": blocks,
        "plain_text": art.get("plain_text"),
        "entities": art.get("entities"),
    }
    (DATA / f"{slug}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (out_dir / "index.html").write_text(post_page(meta, body_html, toc_html), encoding="utf-8")
    print(
        f"[ok] {slug}: images {images_ok}/{images_total} (api media~{api_media_n}), blocks {len(blocks)}"
    )
    return meta


def main():
    api = json.load(open("/workspace/x-posts-api.json"))
    users = {u["id"]: u for u in api["includes"]["users"]}
    DATA.mkdir(parents=True, exist_ok=True)
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "site.css").write_text(CSS, encoding="utf-8")
    posts_meta = []
    # preserve a sensible order
    order = [
        "2111826068017717314",
        "2112129349071831259",
        "2110669876482203775",
        "2112216903150436383",
        "2111268767342997847",
        "2109883678897909932",
        "2112061360708403397",
    ]
    by_id = {p["id"]: p for p in api["data"]}
    for pid in order:
        posts_meta.append(process_one(by_id[pid], users))

    manifest = {"generated_at": datetime.now(TZ8).isoformat(), "posts": posts_meta}
    (ROOT / "posts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "index.html").write_text(index_page(posts_meta), encoding="utf-8")
    sites = load_sites()
    (ROOT / "sites.html").write_text(sites_page(sites), encoding="utf-8")
    print("Wrote index +", len(posts_meta), "posts,", len(sites), "sites")


if __name__ == "__main__":
    main()
