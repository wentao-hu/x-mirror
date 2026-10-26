#!/usr/bin/env python3
"""文章分类 taxonomy 的唯一加载、规范化和校验入口。"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY_PATH = ROOT / "category-taxonomy.json"


class CategoryTaxonomyError(ValueError):
    """taxonomy、分类名或帖子分类不合法。"""


def normalize_key(value: str) -> str:
    """用于检测大小写、全半角和空白造成的等价名称。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def display_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in value)


def _allowed_char(ch: str) -> bool:
    if ch.isascii() and ch.isalnum():
        return True
    codepoint = ord(ch)
    return 0x3400 <= codepoint <= 0x4DBF or 0x4E00 <= codepoint <= 0x9FFF


def validate_name(name: Any, policy: dict[str, Any]) -> None:
    if not isinstance(name, str) or not name:
        raise CategoryTaxonomyError("分类名不能为空")
    if name != name.strip():
        raise CategoryTaxonomyError(f"分类名不能包含首尾空白: {name!r}")
    if unicodedata.normalize("NFKC", name) != name:
        raise CategoryTaxonomyError(f"分类名必须使用 NFKC 规范形式: {name!r}")
    invalid = [ch for ch in name if not _allowed_char(ch)]
    if invalid:
        raise CategoryTaxonomyError(f"分类名只允许中文、ASCII 字母和数字，非法字符: {invalid!r}")
    max_codepoints = policy.get("max_codepoints")
    max_width = policy.get("max_display_units")
    if not isinstance(max_codepoints, int) or max_codepoints <= 0:
        raise CategoryTaxonomyError("name_policy.max_codepoints 必须是正整数")
    if not isinstance(max_width, int) or max_width <= 0:
        raise CategoryTaxonomyError("name_policy.max_display_units 必须是正整数")
    if len(name) > max_codepoints:
        raise CategoryTaxonomyError(
            f"分类名 {name!r} 超过 {max_codepoints} 个 Unicode 码点"
        )
    width = display_width(name)
    if width > max_width:
        raise CategoryTaxonomyError(
            f"分类名 {name!r} 估算显示宽度 {width}，超过上限 {max_width}"
        )


def _nonempty_string_list(value: Any, field: str, category: str) -> None:
    if not isinstance(value, list) or not value:
        raise CategoryTaxonomyError(f"{category!r} 的 {field} 必须是非空数组")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CategoryTaxonomyError(f"{category!r} 的 {field} 含空值或非字符串")


def validate_taxonomy(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CategoryTaxonomyError("taxonomy 根节点必须是对象")
    if data.get("schema_version") != 1:
        raise CategoryTaxonomyError("仅支持 schema_version=1")
    if not isinstance(data.get("taxonomy_revision"), int) or data["taxonomy_revision"] <= 0:
        raise CategoryTaxonomyError("taxonomy_revision 必须是正整数")
    policy = data.get("name_policy")
    if not isinstance(policy, dict):
        raise CategoryTaxonomyError("name_policy 必须是对象")
    max_codepoints = policy.get("max_codepoints")
    max_width = policy.get("max_display_units")
    if not isinstance(max_codepoints, int) or max_codepoints <= 0:
        raise CategoryTaxonomyError("name_policy.max_codepoints 必须是正整数")
    if not isinstance(max_width, int) or max_width <= 0:
        raise CategoryTaxonomyError("name_policy.max_display_units 必须是正整数")

    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise CategoryTaxonomyError("categories 必须是非空数组")

    official_keys: dict[str, str] = {}
    all_keys: dict[str, str] = {}
    names: set[str] = set()

    for index, category in enumerate(categories):
        if not isinstance(category, dict):
            raise CategoryTaxonomyError(f"categories[{index}] 必须是对象")
        name = category.get("name")
        validate_name(name, policy)
        if name in names:
            raise CategoryTaxonomyError(f"分类名重复: {name!r}")
        names.add(name)

        key = normalize_key(name)
        if key in official_keys:
            raise CategoryTaxonomyError(
                f"分类名规范化后冲突: {name!r} 与 {official_keys[key]!r}"
            )
        official_keys[key] = name
        all_keys[key] = name

        for field in ("definition",):
            value = category.get(field)
            if not isinstance(value, str) or not value.strip():
                raise CategoryTaxonomyError(f"{name!r} 的 {field} 不能为空")
        for field in ("includes", "excludes"):
            _nonempty_string_list(category.get(field), field, name)

        aliases = category.get("aliases")
        if not isinstance(aliases, list):
            raise CategoryTaxonomyError(f"{name!r} 的 aliases 必须是数组")
        alias_keys: set[str] = set()
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise CategoryTaxonomyError(f"{name!r} 的 aliases 含空值或非字符串")
            alias_key = normalize_key(alias)
            if alias_key in alias_keys:
                raise CategoryTaxonomyError(f"{name!r} 的 alias 重复: {alias!r}")
            alias_keys.add(alias_key)
            owner = all_keys.get(alias_key)
            if owner and owner != name:
                raise CategoryTaxonomyError(
                    f"alias {alias!r} 规范化后与分类 {owner!r} 冲突"
                )
            all_keys[alias_key] = name

    return data


def load_taxonomy(path: Path | str = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    taxonomy_path = Path(path)
    try:
        raw = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CategoryTaxonomyError(f"taxonomy 文件不存在: {taxonomy_path}") from exc
    except json.JSONDecodeError as exc:
        raise CategoryTaxonomyError(f"taxonomy JSON 无法解析: {exc}") from exc
    return validate_taxonomy(raw)


def official_names(taxonomy: dict[str, Any]) -> list[str]:
    return [category["name"] for category in taxonomy["categories"]]


def definitions(taxonomy: dict[str, Any]) -> dict[str, str]:
    return {category["name"]: category["definition"] for category in taxonomy["categories"]}


def alias_map(taxonomy: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for category in taxonomy["categories"]:
        name = category["name"]
        mapping[normalize_key(name)] = name
        for alias in category["aliases"]:
            mapping[normalize_key(alias)] = name
    return mapping


def resolve_alias(name: str, taxonomy: dict[str, Any]) -> str | None:
    return alias_map(taxonomy).get(normalize_key(name))


def validate_post_category(
    meta: dict[str, Any],
    taxonomy: dict[str, Any],
    *,
    source: str = "post",
    require_reason: bool = False,
) -> str:
    category = meta.get("category")
    allowed = official_names(taxonomy)
    if not isinstance(category, str) or not category:
        raise CategoryTaxonomyError(f"{source}: category 不能为空")
    if category not in allowed:
        canonical = resolve_alias(category, taxonomy)
        if canonical:
            raise CategoryTaxonomyError(
                f"{source}: {category!r} 是历史 alias，必须写成正式分类 {canonical!r}"
            )
        raise CategoryTaxonomyError(
            f"{source}: 未知分类 {category!r}；允许值: {', '.join(allowed)}"
        )
    if require_reason:
        reason = meta.get("category_reason")
        if not isinstance(reason, str) or len(reason.strip()) < 12:
            raise CategoryTaxonomyError(
                f"{source}: 新增或改分类时必须填写 category_reason，"
                "至少说明主要交付以及排除了哪个相近分类"
            )
    return category
