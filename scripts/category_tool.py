#!/usr/bin/env python3
"""分类体系校验、提案与上下文查看工具。"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from pathlib import Path

from category_taxonomy import (
    DEFAULT_TAXONOMY_PATH,
    ROOT,
    CategoryTaxonomyError,
    definitions,
    display_width,
    load_taxonomy,
    normalize_key,
    official_names,
    resolve_alias,
    validate_name,
    validate_post_category,
)


def load_posts() -> list[tuple[Path, dict]]:
    posts = []
    for path in sorted((ROOT / "data").glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CategoryTaxonomyError(f"{path.name}: JSON 无法解析: {exc}") from exc
        meta = raw.get("meta")
        if not isinstance(meta, dict):
            raise CategoryTaxonomyError(f"{path.name}: 缺少 meta 对象")
        posts.append((path, meta))
    return posts


def cmd_validate(args: argparse.Namespace) -> int:
    taxonomy = load_taxonomy(args.taxonomy)
    posts = load_posts()
    counts: Counter[str] = Counter()
    for path, meta in posts:
        category = validate_post_category(meta, taxonomy, source=path.name)
        counts[category] += 1
    print(
        f"分类体系有效：{len(official_names(taxonomy))} 类，"
        f"{len(posts)} 篇，taxonomy_revision={taxonomy['taxonomy_revision']}"
    )
    for name in official_names(taxonomy):
        print(f"  {name}\t{counts[name]} 篇\t宽度 {display_width(name)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    taxonomy = load_taxonomy(args.taxonomy)
    counts = Counter()
    for _, meta in load_posts():
        validate_post_category(meta, taxonomy, source=meta.get("slug", "post"))
        counts[meta["category"]] += 1
    for index, category in enumerate(taxonomy["categories"], start=1):
        name = category["name"]
        aliases = " / ".join(category["aliases"]) if category["aliases"] else "无"
        print(f"{index}. {name}（{counts[name]} 篇，宽度 {display_width(name)}）")
        print(f"   定义：{category['definition']}")
        print(f"   旧名：{aliases}")
    return 0


def cmd_check_post(args: argparse.Namespace) -> int:
    taxonomy = load_taxonomy(args.taxonomy)
    path = Path(args.path).expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        raise CategoryTaxonomyError(f"{path.name}: 缺少 meta 对象")
    category = validate_post_category(
        meta,
        taxonomy,
        source=path.name,
        require_reason=args.new,
    )
    definition = definitions(taxonomy)[category]
    print(f"分类有效：{category}")
    print(f"定义：{definition}")
    if meta.get("category_reason"):
        print(f"归类依据：{meta['category_reason']}")
    elif args.new:
        print("错误：新帖子或改分类的帖子必须填写 category_reason。")
        return 1
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    taxonomy = load_taxonomy(args.taxonomy)
    name = args.name
    policy = taxonomy["name_policy"]
    valid = True
    try:
        validate_name(name, policy)
    except CategoryTaxonomyError as exc:
        valid = False
        print(f"格式错误：{exc}")

    canonical = resolve_alias(name, taxonomy)
    if canonical:
        valid = False
        print(f"名称冲突：{name!r} 已是 {canonical!r} 的正式名称或旧名。")

    names = official_names(taxonomy)
    scored = []
    key = normalize_key(name)
    for existing in names:
        existing_key = normalize_key(existing)
        ratio = difflib.SequenceMatcher(None, key, existing_key).ratio()
        contained = key in existing_key or existing_key in key
        scored.append((ratio, contained, existing))
    scored.sort(reverse=True)
    nearby = [item for item in scored if item[0] >= 0.2 or item[1]]

    print(
        f"名称检查：{name!r}，码点 {len(name)}/{policy['max_codepoints']}，"
        f"估算宽度 {display_width(name)}/{policy['max_display_units']}"
    )
    print("最近邻：")
    if nearby:
        for ratio, contained, existing in nearby[:3]:
            flags = ["包含关系"] if contained else []
            print(f"  {existing}\t字符相似度 {ratio:.2f}\t{' / '.join(flags) or '需语义复核'}")
    else:
        print("  无字符近邻；仍需人工审查定义和收录边界")

    print("\n新分类审批表：")
    print("  1. 主要问题：这个分类长期回答哪个独立问题？")
    print("  2. 最近邻：与上面的分类如何互斥？")
    print("  3. 样本：至少 3 篇独立、真实、可查证的现有文章。")
    print("  4. 边界：同时填写 includes 与 excludes。")
    print("  5. 迁移：列出需要迁移和不迁移的文章。")
    print("  6. 复审：说明未来什么条件下合并或撤销。")
    print("  7. 批准：必须由用户明确批准后，才能修改 taxonomy。")
    return 0 if valid else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="x-mirror 分类治理工具")
    parser.add_argument(
        "--taxonomy",
        default=str(DEFAULT_TAXONOMY_PATH),
        help="taxonomy JSON 路径",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="校验 taxonomy 和全部帖子分类")
    p_validate.set_defaults(func=cmd_validate)

    p_list = sub.add_parser("list", help="列出现有分类、定义和篇数")
    p_list.set_defaults(func=cmd_list)

    p_check = sub.add_parser("check-post", help="校验单篇帖子分类")
    p_check.add_argument("path")
    p_check.add_argument("--new", action="store_true", help="要求填写 category_reason")
    p_check.set_defaults(func=cmd_check_post)

    p_propose = sub.add_parser("propose", help="检查新分类名称并生成审批表")
    p_propose.add_argument("name")
    p_propose.set_defaults(func=cmd_propose)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (CategoryTaxonomyError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
