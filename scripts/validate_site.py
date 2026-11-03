#!/usr/bin/env python3
"""发布前核对数据、页面、首页与全文索引；拒绝无声漏文或旧版本覆盖。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

import extract_and_build as builder
from search_index import build_index, extract_text

ROOT = Path(__file__).resolve().parents[1]


def unique(values: list[str], label: str) -> set[str]:
    duplicates = [slug for slug, count in Counter(values).items() if count > 1]
    if duplicates:
        raise ValueError(f"{label} slug 重复: {duplicates}")
    return set(values)


def same_slugs(actual: set[str], expected: set[str], label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} 不一致，遗漏: {sorted(expected - actual)}，多出: {sorted(actual - expected)}")


def asset_references(soup: BeautifulSoup) -> list[str]:
    refs = [node['src'] for node in soup.select('script[src]')]
    refs += [node['href'] for node in soup.select('link[rel="stylesheet"]')]
    search = soup.select_one('#q[data-search-index]')
    if search is None:
        raise ValueError("首页缺少全文索引入口")
    refs += [value for key, value in search.attrs.items() if key.startswith('data-search-')]
    return refs


def validate_local(root: Path = ROOT) -> set[str]:
    raw = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((root / 'data').glob('*.json'))]
    data_slugs = unique([item['meta']['slug'] for item in raw], 'data')
    posts = json.loads((root / 'posts.json').read_text(encoding='utf-8'))['posts']
    all_slugs = unique([post['slug'] for post in posts], 'posts.json')
    mirrors = {post['slug'] for post in posts if post.get('entry_type') != 'link_only'}
    same_slugs(mirrors, data_slugs, 'data 与 posts.json')
    manifest = {post['slug']: post for post in posts}
    soup = BeautifulSoup((root / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    cards = soup.select('#list .card[data-slug]')
    same_slugs(unique([card['data-slug'] for card in cards], '首页'), all_slugs, '首页')
    for card in cards:
        if card['data-slug'] in mirrors and card.get('href') != f"posts/{card['data-slug']}/":
            raise ValueError(f"首页文章链接错误: {card['data-slug']}")
    payload = json.loads((root / 'assets/search-index.json').read_text(encoding='utf-8'))
    if payload.get('version') != 1:
        raise ValueError('全文索引版本不支持')
    build_index(payload['documents'], list(all_slugs))
    version_module = root / 'functions/_lib/search-version.js'
    if (root / 'functions/api/search.js').exists():
        version = hashlib.sha256((root / 'assets/search-index.json').read_bytes()).hexdigest()[:8]
        expected_module = '// 由 rebuild_from_data.py 生成，与静态全文索引保持同一版本。\n' + f'export const SEARCH_VERSION = "{version}";\n'
        if not version_module.is_file() or version_module.read_text(encoding='utf-8') != expected_module:
            raise ValueError('边缘搜索索引版本过期')
    documents = {doc['slug']: doc for doc in payload['documents']}
    for item in raw:
        meta = item['meta']
        slug = meta['slug']
        if meta != manifest[slug]:
            raise ValueError(f'文章清单元信息过期: {slug}')
        body = builder.render_blocks_html(item['blocks'], 'assets')
        expected = builder.search_document(meta, body)
        if documents[slug] != expected:
            raise ValueError(f'全文索引与 data 正文不一致: {slug}')
        page_path = root / 'posts' / slug / 'index.html'
        if not page_path.is_file():
            raise ValueError(f'文章页缺失: {slug}')
        page = BeautifulSoup(page_path.read_text(encoding='utf-8'), 'html.parser')
        article = page.select_one('article.article')
        if article is None or extract_text(str(article)) != expected['text']:
            raise ValueError(f'文章页正文与 data 不一致: {slug}')
    for post in posts:
        if post.get('entry_type') == 'link_only' and documents[post['slug']] != builder.search_document(post):
            raise ValueError(f'外链索引不一致: {post["slug"]}')
    for page_path in (root / 'posts').glob('*/index.html'):
        if page_path.parent.name not in mirrors:
            page = BeautifulSoup(page_path.read_text(encoding='utf-8'), 'html.parser')
            if page.select_one('article'):
                raise ValueError(f'孤立文章缺少 data: {page_path.parent.name}')
    for ref in asset_references(soup):
        parts = urlsplit(ref)
        path = root / parts.path.lstrip('/')
        if parts.scheme or not path.is_file():
            raise ValueError(f'首页资源缺失或不是本地文件: {ref}')
        version = parse_qs(parts.query).get('v', [''])[0]
        if version != hashlib.sha256(path.read_bytes()).hexdigest()[:8]:
            raise ValueError(f'首页资源版本过期: {ref}')
    return all_slugs


def ensure_no_loss(local: set[str], online: set[str], *, exact: bool = False) -> None:
    missing = online - local
    if missing:
        raise ValueError(f'待发布版本会丢失线上文章: {sorted(missing)}；先同步完整数据，删文须单独确认')
    if exact and local != online:
        raise ValueError(f'线上未完整更新，缺少: {sorted(local - online)}')


def fetch(url: str) -> bytes:
    return subprocess.check_output([
        'curl', '--http1.1', '-fsS', '--compressed', '--max-time', '120',
        '-H', 'Cache-Control: no-cache', url,
    ])


def verify_online(base: str, local: set[str], *, exact: bool = False) -> None:
    base = base.rstrip('/') + '/'
    posts = json.loads(fetch(urljoin(base, 'posts.json')))['posts']
    online = unique([post['slug'] for post in posts], '线上清单')
    html = fetch(base)
    soup = BeautifulSoup(html, 'html.parser')
    cards = unique([c['data-slug'] for c in soup.select('#list .card[data-slug]')], '线上首页')
    ensure_no_loss(local, online | cards, exact=exact)
    if exact:
        same_slugs(cards, local, '线上首页')
        same_slugs(online, local, '线上清单')
        if html != (ROOT / 'index.html').read_bytes():
            raise ValueError('线上首页不是本次构建版本')
        for ref in asset_references(soup):
            if fetch(urljoin(base, ref)) != (ROOT / urlsplit(ref).path).read_bytes():
                raise ValueError(f'线上资源版本与本地不同: {ref}')
        version = hashlib.sha256((ROOT / 'assets/search-index.json').read_bytes()).hexdigest()[:8]
        result = json.loads(fetch(urljoin(base, f'api/search?v={version}&q=SEO')))
        if not result.get('ok') or result.get('version') != version or result.get('total') != len(local):
            raise ValueError('线上边缘搜索版本不一致')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online', help='上线前防止覆盖线上独有文章')
    parser.add_argument('--verify-online', help='上线后严格核对首页与搜索资源')
    args = parser.parse_args()
    try:
        slugs = validate_local()
        if args.online:
            verify_online(args.online, slugs)
        if args.verify_online:
            verify_online(args.verify_online, slugs, exact=True)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f'发布校验失败: {error}', file=sys.stderr)
        raise SystemExit(1)
    print(f'发布校验通过: {len(slugs)} 篇，data / 首页 / 页面 / 全文索引一致')


if __name__ == '__main__':
    main()
