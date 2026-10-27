#!/usr/bin/env python3
"""聊天记录与行内 Markdown 渲染回归测试。"""
from pathlib import Path
import json
import sys
import unittest

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import extract_and_build as builder
from category_taxonomy import (
    CategoryTaxonomyError,
    display_width,
    validate_name,
    validate_post_category,
)


class ChatNewlineRenderingTest(unittest.TestCase):
    def test_single_blank_line_becomes_exactly_two_breaks(self):
        rendered = builder.linkify("第一段\n\n第二段")
        self.assertEqual(rendered, "第一段<br><br>第二段")
        self.assertNotIn("\n", rendered)

    def test_mixed_single_and_blank_lines_do_not_double_render(self):
        rendered = builder.linkify("第一段\n\n第二段\n第三段")
        self.assertEqual(rendered, "第一段<br><br>第二段<br>第三段")
        self.assertNotIn("\n", rendered)

    def test_related_keywords_render_and_ignore_empty_values(self):
        rendered = builder.tags_html(
            {"tags": ["海外收款", "", None, "Stripe"]},
            show_label=True,
        )
        self.assertIn("关键词", rendered)
        self.assertIn("海外收款", rendered)
        self.assertIn("Stripe", rendered)
        self.assertNotIn("None", rendered)


class ChatCollapseRenderingTest(unittest.TestCase):
    def test_long_log_keeps_collapsed_details_with_bubble_messages(self):
        rendered = builder.render_chat_html(
            {
                "messages": [
                    {"user": "甲", "time": "2026年10月23日 10:00", "text": "第一条"},
                    {"user": "乙", "time": "2026年10月23日 10:01", "text": "最后一条"},
                ],
            }
        )
        self.assertIn('<details class="chat-range">', rendered)
        self.assertIn("<summary>首尾消息</summary>", rendered)
        self.assertIn('<details class="chat-appendix">', rendered)
        self.assertIn("<summary>全部 2 条消息</summary>", rendered)
        self.assertNotIn(" open", rendered)
        soup = BeautifulSoup(rendered, "html.parser")
        self.assertEqual(len(soup.select(".chat-msg")), 4)
        self.assertEqual(len(soup.select(".chat-bubble")), 4)

    def test_expanded_thread_skips_range_and_cleans_links(self):
        rendered = builder.render_chat_html(
            {
                "expanded": True,
                "variant": "thread",
                "messages": [
                    {
                        "user": "甲",
                        "username": "alpha",
                        "text": "问 @beta\nhttps://x.com/beta/status/1234567890",
                    },
                    {
                        "user": "乙",
                        "avatar": "avatar.jpg",
                        "text": "收到",
                    },
                ],
            }
        )
        soup = BeautifulSoup(rendered, "html.parser")
        self.assertIsNotNone(soup.select_one(".chat-block--thread"))
        self.assertIsNone(soup.select_one("details"))
        self.assertEqual(len(soup.select(".chat-msg")), 2)
        self.assertEqual(len(soup.select(".chat-bubble")), 2)
        self.assertIsNotNone(soup.select_one(".chat-avatar__initial"))
        self.assertEqual(
            soup.select_one(".chat-msg:nth-of-type(2) img").get("src"),
            "assets/avatar.jpg",
        )
        self.assertNotIn("@beta", [a.get_text(strip=True) for a in soup.select("a")])
        self.assertNotIn("status/", rendered)


class InlineCodeRenderingTest(unittest.TestCase):
    def test_backticks_render_as_inline_code(self):
        rendered = builder.linkify("`deepinfer deepseek` 是什么")
        self.assertEqual(
            rendered,
            '<code class="inline-code">deepinfer deepseek</code> 是什么',
        )

    def test_inline_code_is_escaped_and_not_linkified(self):
        rendered = builder.linkify(
            "`<b>@user https://example.com **重点**</b>`"
        )
        self.assertIn(
            '&lt;b&gt;@user https://example.com **重点**&lt;/b&gt;',
            rendered,
        )
        self.assertNotIn("<a ", rendered)
        self.assertNotIn("<strong>", rendered)

    def test_inline_code_renders_in_heading_and_table(self):
        rendered = builder.render_blocks_html(
            [
                {"type": "heading", "level": 2, "text": "`deepinfer` 说明"},
                {
                    "type": "table",
                    "rows": [["字段", "值"], ["框架", "`deepinfer`"]],
                },
            ],
            "assets",
        )
        self.assertEqual(rendered.count('<code class="inline-code">'), 2)


class PostPresentationTest(unittest.TestCase):
    def make_meta(self, *, source_type="x_post", url="https://example.com/post"):
        return {
            "id": "test-post",
            "slug": "test-post",
            "title": "测试标题",
            "url": url,
            "author_name": "萧禹",
            "author_username": "",
            "published_utc": "2026-10-23T00:00:00.000Z",
            "published_local": "2026-10-23 08:00",
            "category": "SEO获客",
            "source_type": source_type,
            "images_total": 0,
            "images_ok": 0,
            "blocks_count": 0,
        }

    def test_source_badge_moves_from_title_to_meta_row(self):
        html = builder.post_page(
            self.make_meta(source_type="note", url=""),
            "<p>正文</p>",
        )
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1.title")
        self.assertEqual(title.get_text(" ", strip=True), "测试标题")
        self.assertIsNone(title.select_one(".source-badge"))
        meta_row = soup.select_one(".post-meta-row")
        self.assertIsNotNone(meta_row.select_one(".source-badge"))
        self.assertIsNotNone(meta_row.select_one(".cat-badge"))

    def test_chat_avatar_initial_is_not_part_of_meta_description(self):
        html = builder.post_page(
            self.make_meta(),
            '<div class="chat-block"><div class="chat-msg">'
            '<span class="chat-avatar"><span>M</span></span>'
            '<div class="chat-user">Marvin</div><div>验证需求</div>'
            "</div></div>",
        )
        soup = BeautifulSoup(html, "html.parser")
        description = soup.select_one('meta[name="description"]')["content"]
        self.assertEqual(description, "Marvin 验证需求")

    def test_original_link_source_badge_and_category_order(self):
        html = builder.post_page(self.make_meta(), "<p>正文</p>")
        soup = BeautifulSoup(html, "html.parser")
        children = soup.select(".post-meta-row > *")
        self.assertEqual(
            [child.get("class")[0] for child in children],
            ["orig-link", "source-badge", "cat-badge"],
        )

    def test_title_does_not_balance_wrap(self):
        self.assertNotIn("text-wrap: balance", builder.CSS)

    def test_sync_status_copy_is_not_part_of_post_ui(self):
        meta_js = (ROOT / "assets" / "meta.js").read_text(encoding="utf-8")
        self.assertNotIn("评分已同步到 Cloudflare KV", meta_js)
        self.assertNotIn("评分与已读已从 Cloudflare KV 同步", meta_js)
        self.assertNotIn("pc-note", builder.CSS)

    def test_post_rating_stars_match_label_size(self):
        self.assertIn("--post-rating-size: 13.5px", builder.CSS)
        self.assertIn(
            ".post-controls .pc-label { color: var(--muted); font-size: var(--post-rating-size); }",
            builder.CSS,
        )
        self.assertIn(
            ".post-controls .xr-star {\n"
            "  padding: 1px; font-size: var(--post-rating-size); line-height: 1;\n"
            "}",
            builder.CSS,
        )
        self.assertNotIn(
            ".post-controls .xr-star { font-size: 22px;",
            builder.CSS,
        )

    def test_category_headers_have_drag_controls_and_definitions(self):
        html = builder.index_page([self.make_meta()])
        soup = BeautifulSoup(html, "html.parser")
        head = soup.select_one('.cat[data-cat="SEO获客"]')
        self.assertIsNotNone(head)
        self.assertTrue(head.get("title"))
        self.assertIsNotNone(head.select_one("button.cat-toggle"))
        self.assertIsNotNone(head.select_one("button.cat-drag[aria-label]"))
        self.assertIn("拖动分类右侧手柄排序", html)

    def test_all_post_categories_use_the_single_primary_taxonomy(self):
        categories = set()
        for path in (ROOT / "data").glob("*.json"):
            meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
            categories.add(meta["category"])
        self.assertTrue(categories.issubset(set(builder.CATEGORY_ORDER)))
        self.assertGreaterEqual(len(builder.CATEGORY_ORDER), 7)

    def test_category_names_follow_length_and_character_policy(self):
        policy = builder.CATEGORY_TAXONOMY["name_policy"]
        for name in builder.CATEGORY_ORDER:
            validate_name(name, policy)
        self.assertEqual(display_width("SEO获客"), 7)
        with self.assertRaises(CategoryTaxonomyError):
            validate_name("五个汉字名", policy)
        with self.assertRaises(CategoryTaxonomyError):
            validate_name("TOOLONG", policy)
        with self.assertRaises(CategoryTaxonomyError):
            validate_name("AI 工具", policy)
        with self.assertRaises(CategoryTaxonomyError):
            validate_name("AI-工具", policy)

    def test_category_alias_is_not_valid_for_new_posts(self):
        meta = self.make_meta()
        meta["category"] = "AI 工具"
        with self.assertRaises(CategoryTaxonomyError):
            validate_post_category(meta, builder.CATEGORY_TAXONOMY, source="test.json")

    def test_unknown_category_is_not_auto_appended(self):
        meta = self.make_meta()
        meta["category"] = "未知分类"
        with self.assertRaises(CategoryTaxonomyError):
            builder.index_page([meta])

    def test_new_or_changed_post_requires_category_reason(self):
        meta = self.make_meta()
        with self.assertRaises(CategoryTaxonomyError):
            validate_post_category(
                meta,
                builder.CATEGORY_TAXONOMY,
                source="test.json",
                require_reason=True,
            )
        meta["category_reason"] = "主要交付是搜索获客，不归入需求研究。"
        self.assertEqual(
            validate_post_category(
                meta,
                builder.CATEGORY_TAXONOMY,
                source="test.json",
                require_reason=True,
            ),
            "SEO获客",
        )

    def test_generated_category_names_module_matches_taxonomy(self):
        path = ROOT / "functions" / "_lib" / "category-names.js"
        self.assertEqual(path.read_text(encoding="utf-8"), builder.render_category_names_module())

    def test_category_order_has_local_and_remote_sync(self):
        meta_js = (ROOT / "assets" / "meta.js").read_text(encoding="utf-8")
        self.assertIn("x-mirror-category-order-v1", meta_js)
        self.assertIn("/category-order", meta_js)
        self.assertIn("pointerdown", meta_js)
        self.assertIn("ArrowUp", meta_js)
        self.assertIn("refreshCategoryOrder", meta_js)


class ImageZoomInteractionTest(unittest.TestCase):
    def test_zoom_controls_are_on_demand_and_touch_accessible(self):
        zoom_js = (ROOT / "assets" / "image-zoom.js").read_text(encoding="utf-8")
        self.assertIn("SHOW_DELAY = 400", zoom_js)
        self.assertIn("HIDE_DELAY = 600", zoom_js)
        self.assertIn("fig.addEventListener('pointerenter'", zoom_js)
        self.assertIn("fig.addEventListener('focusin'", zoom_js)
        self.assertIn("isTouchActivation", zoom_js)
        self.assertIn('data-img-action="preview"', zoom_js)
        self.assertIn("bottom: 8px", builder.CSS)
        self.assertIn("opacity: 0; visibility: hidden; pointer-events: none;", builder.CSS)
        self.assertNotIn("position: absolute; top: 8px; right: 8px;", builder.CSS)


class TargetPostDataTest(unittest.TestCase):
    def load_data(self, filename):
        return json.loads((ROOT / "data" / filename).read_text(encoding="utf-8"))

    def test_airobert_comments_are_an_expanded_chat_without_status_urls(self):
        data = self.load_data("airobert-precise-demand-near-money.json")
        chat_blocks = [block for block in data["blocks"] if block["type"] == "chat"]
        self.assertEqual(len(chat_blocks), 1)
        chat = chat_blocks[0]
        self.assertTrue(chat["expanded"])
        self.assertEqual(chat["variant"], "thread")
        self.assertEqual(len(chat["messages"]), 14)
        self.assertTrue(all(message.get("username") for message in chat["messages"]))
        self.assertNotIn("status/", json.dumps(chat, ensure_ascii=False))
        self.assertNotIn("https://x.com/", data["plain_text"])
        self.assertEqual(data["meta"]["blocks_count"], len(data["blocks"]))
        self.assertEqual(data["meta"]["plain_text_len"], len(data["plain_text"]))

    def test_liangzhu_page_keeps_five_items_and_shows_the_fidelity_note(self):
        data = self.load_data("liangzhu-seo-launch-checklist.json")
        text = "\n".join(
            block["text"]
            for block in data["blocks"]
            if block["type"] == "paragraph"
        )
        self.assertIn("1. 检查是不是纯客户端渲染", text)
        self.assertIn("5. 清除多重重定向死链", text)
        self.assertNotIn("\n6. ", text)
        note = "说明：原文自称「这 7 项」，但清单只列到第 5 项，此处按原文保留，未补写。"
        self.assertIn(note, text)
        self.assertIn("页面已显式说明", data["meta"]["fidelity_note"])
        self.assertEqual(data["meta"]["blocks_count"], len(data["blocks"]))
        self.assertEqual(data["meta"]["plain_text_len"], len(data["plain_text"]))


if __name__ == "__main__":
    unittest.main()
