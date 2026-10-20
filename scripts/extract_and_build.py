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

from generate_webp import generate_all


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

CATEGORY_ORDER = ["新词站实战复盘", "出海复盘", "SEO基础", "建站教程", "外链推广", "web.cafe 精选"]

CATEGORIES = {
    "2110669876482203775": "新词站实战复盘",
    "2112216903150436383": "新词站实战复盘",
    "2112129349071831259": "新词站实战复盘",
    "2111826068017717314": "新词站实战复盘",
    "2111268767342997847": "SEO基础",
    "2109883678897909932": "建站教程",
    "2112061360708403397": "外链推广",
}

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


SOURCE_TYPE_LABELS = {
    "x_post": "帖子",
    "x_article": "长文",
    "web_article": "网页",
    "webcafe": "web.cafe",
    "wechat": "微信",
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
}


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
    }.get(st, X_ICON)
    return (
        f'<span class="source-badge" data-source-type="{esc(st)}">'
        f'{icon}<span class="src-label">{label}</span></span>'
    )


def linkify(text: str) -> str:
    """Escape then linkify URLs and @handles and #hashtags lightly."""
    s = esc(text)

    def repl_url(m):
        u = m.group(0)
        # unescape not needed; we escaped first so URL has no &amp issues... wait we did escape
        # actually URLs in text may contain & which became &amp;
        return f'<a href="{u}" rel="noopener noreferrer" target="_blank">{u}</a>'

    s = re.sub(r"https?://[^\s<>\"']+", repl_url, s)
    s = re.sub(
        r"(?<!\w)@([A-Za-z0-9_]{1,15})",
        r'<a class="mention" href="https://x.com/\1" rel="noopener noreferrer" target="_blank">@\1</a>',
        s,
    )
    # preserve newlines as <br> for multi-line paras
    s = s.replace("\n", "<br>\n")
    return s


def asset_version(rel_path: str) -> str:
    """返回资产内容 sha256 前 8 位，用于 ?v= 缓存版本。"""
    return hashlib.sha256((ROOT / rel_path).read_bytes()).hexdigest()[:8]


def image_html(
    rel_src: str,
    alt: str,
    assets_dir: Path | None = None,
    lazy: bool = False,
) -> str:
    """输出 <img>；若同目录已有 webp，则包一层 <picture> 提供 WebP 源。"""
    attrs = f'src="{rel_src}" alt="{alt}"'
    if lazy:
        attrs += ' loading="lazy" decoding="async"'
    img = f"<img {attrs} />"

    if assets_dir is not None:
        webp_path = Path(rel_src).with_suffix(".webp")
        if (assets_dir / webp_path.name).exists():
            return (
                f'<picture><source srcset="{webp_path.as_posix()}" '
                f'type="image/webp">{img}</picture>'
            )
    return img


def render_blocks_html(
    blocks: list[dict], assets_rel: str, assets_dir: Path | None = None
) -> str:
    parts = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            level = min(max(b.get("level", 2), 1), 4)
            if level == 1:
                continue  # title rendered in header
            parts.append(f"<h{level}>{esc(b['text'])}</h{level}>")
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
                f"{assets_rel}/{local}", alt, assets_dir=assets_dir, lazy=True
            )
            parts.append(f'<figure class="media">{img}</figure>')
        elif t == "code":
            parts.append(f"<pre><code>{esc(b['text'])}</code></pre>")
        elif t == "quote":
            parts.append(f"<blockquote>{linkify(b['text'])}</blockquote>")
        elif t == "list":
            tag = "ol" if b.get("ordered") else "ul"
            items = "".join(f"<li>{linkify(i)}</li>" for i in b["items"])
            parts.append(f"<{tag}>{items}</{tag}>")
        elif t == "table":
            rows_html = []
            for ri, row in enumerate(b["rows"]):
                cells = "".join(
                    f"<{'th' if ri==0 else 'td'}>{esc(c)}</{'th' if ri==0 else 'td'}>"
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
  --border: #eff3f4;
  --link: #1d9bf0;
  --card: #f7f9f9;
  --star: #f5a524;
  --ok: #0f7b45;
  --ok-soft: #e8f5ee;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  line-height: 1.6;
  font-size: 17px;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
picture { display: contents; }
.wrap { max-width: 680px; margin: 0 auto; padding: 16px 16px 64px; }
.index-wrap { max-width: 960px; }
.site-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0 20px; border-bottom: 1px solid var(--border); margin-bottom: 20px;
}
.site-header .brand { font-weight: 800; font-size: 20px; color: var(--fg); }
.site-header nav a { color: var(--muted); margin-left: 12px; font-size: 14px; }
.author {
  display: flex; gap: 12px; align-items: center; margin-bottom: 12px;
}
.author img {
  width: 48px; height: 48px; border-radius: 50%; object-fit: cover;
  background: var(--card);
}
.author .name { font-weight: 700; font-size: 16px; }
.author .meta { color: var(--muted); font-size: 14px; }
h1.title {
  font-size: 28px; line-height: 1.25; font-weight: 800; margin: 8px 0 16px;
}
.article h2 { font-size: 22px; margin: 28px 0 10px; font-weight: 800; }
.article h3 { font-size: 19px; margin: 24px 0 8px; font-weight: 700; }
.article h4 { font-size: 17px; margin: 20px 0 8px; font-weight: 700; }
.article p { margin: 0 0 14px; white-space: normal; }
.article figure.media { margin: 16px 0; }
.article figure.media img {
  display: block; width: 100%; height: auto; border-radius: 12px;
  border: 1px solid var(--border); background: var(--card);
}
.article pre {
  background: #0f1419; color: #e7e9ea; padding: 14px; border-radius: 12px;
  overflow-x: auto; font-size: 13px; line-height: 1.45;
}
.article blockquote {
  margin: 12px 0; padding: 8px 14px; border-left: 4px solid var(--border);
  color: var(--muted);
}
.article ul, .article ol { padding-left: 1.4em; margin: 0 0 14px; }
.table-wrap { overflow-x: auto; margin: 12px 0 16px; }
.article table { border-collapse: collapse; width: 100%; font-size: 14px; }
.article th, .article td {
  border: 1px solid var(--border); padding: 8px 10px; text-align: left;
}
.article th { background: var(--card); }
.orig-link {
  display: inline-block; margin: 8px 0 20px; font-size: 14px; color: var(--muted);
}
.fidelity {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 10px 12px; font-size: 13px; color: var(--muted); margin: 20px 0;
}
.img-missing { color: #f4212e; font-size: 14px; }
/* index */
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 20px; }
.filters button {
  border: 1px solid var(--border); background: var(--bg); border-radius: 999px;
  padding: 6px 12px; cursor: pointer; font-size: 13px; color: var(--muted);
}
/* 分类筛选按钮（#filters 内 data-cat）比其余小按钮略大、颜色略偏链接色 */
.filters button[data-cat] {
  font-size: 15px; color: color-mix(in srgb, var(--fg) 82%, var(--link));
}
.filters button.active { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.search {
  width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 999px;
  font-size: 15px; margin-bottom: 12px;
}
.index-intro { color: var(--muted); font-size: 14px; margin: -8px 0 18px; }
.filter-bar { margin: 0 0 8px; }
.filter-toggle {
  width: 100%; display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--card); color: var(--fg); font: inherit; cursor: pointer; text-align: left;
}
.filter-toggle:hover { border-color: #cbd5dc; }
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
.cat {
  grid-column: 1 / -1;
  display: flex; align-items: center; gap: 8px;
  margin: 22px 0 10px; padding: 9px 12px;
  border: 1px solid var(--border); border-radius: 10px;
  background: var(--card); color: color-mix(in srgb, var(--fg) 78%, var(--link));
  font-size: 18px; font-weight: 800; cursor: pointer; user-select: none;
}
.cat:hover { border-color: #cbd5dc; }
.cat:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; }
.cat .cat-name { flex: 1; min-width: 0; }
.cat .cat-count {
  color: var(--muted); font-size: 12px; font-weight: 600; background: var(--bg);
  border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; white-space: nowrap;
}
.cat .cat-chevron { color: var(--muted); font-size: 12px; transition: transform .15s ease; }
.cat.is-collapsed .cat-chevron { transform: rotate(-90deg); }
.cat.is-collapsed { background: transparent; }
.cat.is-static, .cat.is-static:hover { cursor: default; border-color: var(--border); }
#list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; }
#list .cat { margin-top: 18px; }
.card {
  display: flex; flex-direction: column;
  padding: 14px 16px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg); color: inherit;
  transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease;
}
.card:hover {
  border-color: #cbd5dc; box-shadow: 0 6px 18px rgba(15,20,25,.06);
  transform: translateY(-1px); background: var(--bg);
}
.card .ctitle { font-weight: 700; font-size: 16px; line-height: 1.45; margin-bottom: 6px; }
.card .cmeta {
  color: var(--muted); font-size: 12px; margin-bottom: 6px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.card .cdesc {
  color: var(--muted); font-size: 13px; flex: 1;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 2px 0 4px; }
.list-count { color: var(--muted); font-size: 13px; }
.list-actions { display: flex; gap: 8px; }
.list-actions button {
  border: 1px solid var(--border); background: var(--bg); border-radius: 999px;
  padding: 4px 10px; font: inherit; font-size: 12px; color: var(--muted); cursor: pointer;
}
.list-actions button:hover { color: var(--fg); border-color: #cbd5dc; }
@media (max-width: 760px) {
  #list { grid-template-columns: 1fr; }
  .index-wrap { max-width: 680px; }
}
.footer { margin-top: 40px; color: var(--muted); font-size: 12px; }
/* rating / read */
.xr-stars { display: inline-flex; gap: 1px; line-height: 1; color: #cfd6dc; font-size: 12px; }
.xr-stars .xr-star { font-size: inherit; cursor: default; }
.xr-rating { display: inline-flex; gap: 2px; align-items: center; }
.xr-star {
  appearance: none; -webkit-appearance: none; border: 0; background: none;
  padding: 0 1px; margin: 0; font-family: inherit; font-size: 22px; line-height: 1;
  color: #cfd6dc; cursor: pointer; transition: color .12s ease, transform .12s ease;
}
.xr-star.on { color: var(--star); }
.xr-rating .xr-star:hover { transform: translateY(-1px) scale(1.08); }
.xr-star:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; border-radius: 4px; }
.card-badges { display: inline-flex; align-items: center; gap: 6px; margin-left: 8px; vertical-align: middle; }
.badge-read {
  background: var(--ok-soft); color: var(--ok); font-size: 11px; font-weight: 600;
  line-height: 1.6; padding: 0 7px; border-radius: 999px;
}
.source-badge {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: 7px; vertical-align: middle;
  border: 1px solid var(--border); border-radius: 999px; padding: 0 7px;
  color: var(--muted); font-size: 11px; font-weight: 600;
  line-height: 1.7; white-space: nowrap;
}
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
.source-badge[data-source-type="webcafe"] {
  background: #eef4ff; color: #1d4ed8; border-color: #dbe7ff;
}
.source-badge[data-source-type="wechat"] {
  background: #e8f7ee; color: #14803c; border-color: #cfead9;
}
.card-controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px;
  margin-top: 8px; font-size: 13px;
}
.card-controls .cc-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.card-controls .xr-star { font-size: 17px; }
.card-controls .pc-read { padding: 3px 10px; font-size: 12px; }
.post-controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px;
  margin: 0 0 12px; padding: 10px 14px;
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  font-size: 14px;
}
.post-controls .pc-row { display: flex; align-items: center; gap: 8px; }
.post-controls .pc-label { color: var(--muted); font-size: 13px; }
.post-controls .pc-rating-text { color: var(--muted); font-size: 12px; min-width: 3.2em; }
.post-controls .pc-note { flex-basis: 100%; color: var(--muted); font-size: 12px; line-height: 1.5; }
.pc-clear {
  border: 0; background: none; color: var(--muted); font-size: 12px; font-family: inherit;
  cursor: pointer; padding: 2px 4px; text-decoration: underline; text-underline-offset: 2px;
}
.pc-clear:hover { color: var(--fg); }
.pc-read {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); background: var(--bg); color: var(--muted);
  border-radius: 999px; padding: 5px 12px; font-size: 13px; font-family: inherit;
  cursor: pointer; transition: background .12s ease, color .12s ease, border-color .12s ease;
}
.pc-read:hover { border-color: #cbd5dc; color: var(--fg); }
.pc-read.on { background: var(--ok-soft); border-color: #b7e0c6; color: var(--ok); font-weight: 600; }
.pc-read .pc-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; opacity: .45; }
.pc-read.on .pc-dot { opacity: 1; }
.filter-rows { display: flex; flex-direction: column; gap: 6px; margin: 6px 0 14px; }
.filter-row { display: flex; align-items: center; gap: 10px; }
.filter-row .flabel { flex: 0 0 32px; color: var(--muted); font-size: 12px; }
.filter-row .filters { margin: 0; gap: 6px; }
.filter-row .filters button { padding: 4px 10px; font-size: 12px; }
.meta-status { min-height: 1.2em; margin: -4px 0 16px; color: var(--muted); font-size: 12px; }
#meta-count { margin-left: 10px; }
@media (max-width: 480px) {
  .filter-row { align-items: flex-start; }
  .filter-row .flabel { padding-top: 5px; }
  h1.title { font-size: 24px; }
  html, body { font-size: 16px; }
}
"""


def post_page(meta: dict, body_html: str) -> str:
    post_assets = ROOT / "posts" / meta["slug"] / "assets"
    avatar = meta.get("avatar_local")
    avatar_html = (
        image_html(f"assets/{avatar}", "", assets_dir=post_assets)
        if avatar
        else '<img src="" alt="" style="background:#ddd" />'
    )
    cover = meta.get("cover_local")
    cover_html = (
        f'<figure class="media">'
        f'{image_html(f"assets/{cover}", "封面", assets_dir=post_assets, lazy=True)}'
        f'</figure>'
        if cover and meta.get("cover_separate")
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{esc(meta['title'])} · X Mirror</title>
<meta name="description" content="{esc(meta.get('description',''))}" />
<link rel="stylesheet" href="../../assets/site.css?v={asset_version('assets/site.css')}" />
</head>
<body>
<div class="wrap">
  <header class="site-header">
    <a class="brand" href="../../">X Mirror</a>
    <nav><a href="../../">目录</a></nav>
  </header>
  <div class="author">
    {avatar_html}
    <div>
      <div class="name">{esc(meta['author_name'])} <span class="meta">@{esc(meta['author_username'])}</span></div>
      <div class="meta">{esc(meta['published_local'])} · Asia/Shanghai</div>
    </div>
  </div>
  <h1 class="title">{esc(meta['title'])}{source_badge(meta)}</h1>
  <div class="post-controls" data-meta-mount data-slug="{esc(meta['slug'])}"></div>
  <a class="orig-link" href="{esc(meta['url'])}" target="_blank" rel="noopener">{original_link_text(meta)}</a>
  {cover_html}
  <article class="article">
{body_html}
  </article>
  <div class="fidelity">
    镜像说明：正文与图片按原文顺序本地托管；图片优先下载 orig 分辨率。
    已镜像图片 {meta.get('images_ok',0)}/{meta.get('images_total',0)}。
    {esc(meta.get('fidelity_note') or '')}
  </div>
  <div class="footer">Personal archive mirror · not affiliated with X/Twitter</div>
</div>
<script src="../../assets/meta.js?v={asset_version('assets/meta.js')}" defer></script>
</body>
</html>
"""


def index_page(posts: list[dict]) -> str:
    cats = [c for c in CATEGORY_ORDER if any(p["category"] == c for p in posts)]
    for p in posts:
        if p["category"] not in cats:
            cats.append(p["category"])
    filter_btns = ['<button class="active" data-cat="all">全部</button>'] + [
        f'<button data-cat="{esc(c)}">{esc(c)}</button>' for c in cats
    ]
    sections = []
    for c in cats:
        cards = []
        for p in posts:
            if p["category"] != c:
                continue
            q = esc(p['title'] + ' ' + p['author_name'] + ' ' + p['author_username'] + ' ' + p.get('description', ''))
            date = esc(p['published_local'][:16])
            if p.get("entry_type") == "link_only":
                # 仅链接条目：标题直接外链原文，正文/图片一律不镜像
                username = p.get('author_username', '')
                handle = f"@{esc(username)}" if username and username != "web.cafe" else esc(username)
                cmeta = f"{esc(p['author_name'])}" + (f" · {handle}" if handle else "") + f" · {date}"
                cards.append(
                    f"""<div class="card card-linkonly" data-slug="{esc(p['slug'])}" data-source-type="{esc(source_type_of(p))}" data-cat="{esc(c)}" data-published="{esc(p.get('published_utc',''))}" data-q="{q}">
  <div class="ctitle"><a href="{esc(p['url'])}" target="_blank" rel="noopener noreferrer">{esc(p['title'])}</a>{source_badge(p)}</div>
  <div class="cmeta">{cmeta}</div>
  <div class="cdesc">{esc(p.get('description',''))}</div>
  <div class="card-controls" data-meta-mount data-slug="{esc(p['slug'])}"></div>
</div>"""
                )
            else:
                cards.append(
                    f"""<a class="card" data-slug="{esc(p['slug'])}" data-source-type="{esc(source_type_of(p))}" data-cat="{esc(c)}" data-published="{esc(p.get('published_utc',''))}" data-q="{q}" href="posts/{esc(p['slug'])}/">
  <div class="ctitle">{esc(p['title'])}{source_badge(p)}</div>
  <div class="cmeta">{esc(p['author_name'])} · @{esc(p['author_username'])} · {date}</div>
  <div class="cdesc">{esc(p.get('description',''))}</div>
</a>"""
                )
        sections.append(
            f'<h2 class="cat" data-cat="{esc(c)}" role="button" tabindex="0" aria-expanded="true">'
            f'<span class="cat-name">{esc(c)}</span>'
            f'<span class="cat-count">{len(cards)} 篇</span>'
            f'<span class="cat-chevron" aria-hidden="true">▾</span></h2>\n'
            + "\n".join(cards)
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>X Mirror · 出海 SEO 收藏镜像</title>
<meta name="description" content="出海 SEO 收藏镜像：X、web.cafe 与微信公众号文章本地化，图片全部本地托管" />
<link rel="stylesheet" href="assets/site.css?v={asset_version('assets/site.css')}" />
</head>
<body>
<div class="wrap index-wrap">
  <header class="site-header">
    <span class="brand">X Mirror</span>
    <nav><a href="https://github.com/wentao-hu/x-mirror">GitHub</a></nav>
  </header>
  <h1 class="title" style="font-size:24px">出海 SEO 收藏镜像</h1>
  <p class="index-intro">
    原文来自 X、web.cafe 与微信公众号，本站做内容完全映射（正文 + 图片本地化），方便在打不开原站时阅读。
  </p>
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
          <button data-type="web_article">网页</button>
          <button data-type="webcafe">web.cafe</button>
          <button data-type="wechat">微信</button>
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
          <button data-time="7d">最近 7 天</button>
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
  <div class="meta-status"><span id="meta-status"></span><span id="meta-count"></span></div>
  <div class="list-toolbar">
    <span class="list-count">共 {len(posts)} 篇</span>
    <div class="list-actions" id="list-actions">
      <button type="button" id="expand-all">全部展开</button>
      <button type="button" id="collapse-all">全部折叠</button>
    </div>
  </div>
  <div id="list">
{''.join(sections)}
  </div>
  <div class="footer">共 {len(posts)} 篇 · Personal archive · Asia/Shanghai</div>
</div>
<script src="assets/meta.js?v={asset_version('assets/meta.js')}" defer></script>
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

    (out_dir / "index.html").write_text(post_page(meta, body_html), encoding="utf-8")
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
    print("Wrote index +", len(posts_meta), "posts")


if __name__ == "__main__":
    main()
