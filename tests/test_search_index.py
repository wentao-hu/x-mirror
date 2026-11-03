"""全文索引的数据完整性与正文提取回归测试。"""
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class SearchIndexTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("search_index"),
            "构建流程需要全文索引模块，不能只依赖首页卡片的标题",
        )
        import search_index
        self.search = search_index

    def test_inline_markup_does_not_break_chinese_phrase(self):
        text = self.search.extract_text(
            '<p>提高<strong>付费</strong>转化率，使用<a href="/">Google</a>索引。</p>'
            '<p>第二段<br>第三行 &amp; C++</p>'
        )
        self.assertEqual(text, "提高付费转化率，使用Google索引。 第二段 第三行 & C++")

    def test_all_rendered_content_is_searchable_including_collapsed_chat(self):
        import extract_and_build as builder
        body = builder.render_blocks_html([
            {"type": "heading", "level": 2, "text": "小标题"},
            {"type": "paragraph", "text": "普通正文"},
            {"type": "list", "items": ["列表甲", "列表乙"]},
            {"type": "table", "rows": [["表头", "数值"], ["长尾词", "0.25"]]},
            {"type": "quote", "text": "引用观点"},
            {"type": "code", "text": "print('<tag>')"},
            {"type": "callout", "title": "提示标题", "items": ["提示项"], "text": "提示正文"},
            {"type": "chat", "messages": [{"user": "甲", "text": "折叠聊天独有词"}]},
        ], "assets")
        text = self.search.extract_text(body)
        for phrase in ["小标题", "普通正文", "列表甲 列表乙", "长尾词 0.25",
                       "引用观点", "print('<tag>')", "提示标题", "提示正文", "折叠聊天独有词"]:
            self.assertIn(phrase, text)
        self.assertNotIn("聊天记录（", text)

    def test_controls_and_image_placeholders_are_not_content(self):
        text = self.search.extract_text(
            '<div class="chat-avatar">头像首字母</div>'
            '<details class="chat-appendix"><summary>聊天记录（1 条）</summary>'
            '<p class="chat-note">控件说明</p><p>真正的聊天正文</p></details>'
            '<p class="img-missing">图片缺失</p><script>脚本内容</script>'
            '<img src="local.webp" alt="不做图片 OCR">'
        )
        self.assertEqual(text, "真正的聊天正文")

    def test_long_article_end_is_not_truncated(self):
        text = self.search.extract_text("<p>" + "正文" * 30000 + "末尾独有词</p>")
        self.assertTrue(text.endswith("末尾独有词"))
        self.assertGreater(len(text), 60000)

    def test_index_requires_exact_slug_coverage(self):
        doc = {"slug": "first", "title": "标题", "metadata": "作者", "text": "正文"}
        result = self.search.build_index([doc], ["first"])
        self.assertEqual(result, {"version": 1, "documents": [doc]})
        with self.assertRaisesRegex(ValueError, "遗漏|不一致"):
            self.search.build_index([doc], ["first", "missing"])
        with self.assertRaisesRegex(ValueError, "重复"):
            self.search.build_index([doc, doc], ["first"])
        with self.assertRaisesRegex(ValueError, "重复"):
            self.search.build_index([doc], ["first", "first"])

    def test_link_only_document_keeps_metadata_without_inventing_body(self):
        doc = {"slug": "link", "title": "外链标题", "metadata": "作者与标签", "text": ""}
        self.assertEqual(self.search.build_index([doc], ["link"])["documents"][0]["text"], "")

    def test_search_document_preserves_title_author_tags_and_full_body(self):
        import extract_and_build as builder
        self.assertTrue(hasattr(builder, "search_document"))
        doc = builder.search_document({
            "slug": "sample", "title": "**关键词**指南", "author_name": "萧禹",
            "author_username": "", "tags": ["标签一", "GSC"], "description": "旧摘要",
        }, "<p>正文独有词</p>")
        self.assertEqual(doc["title"], "关键词指南")
        for phrase in ["萧禹", "标签一", "GSC", "旧摘要"]:
            self.assertIn(phrase, doc["metadata"])
        self.assertEqual(doc["text"], "正文独有词")

    def test_title_search_keeps_literal_slash_and_backslash(self):
        import extract_and_build as builder
        doc = builder.search_document({"slug": "literal", "title": r"C/C++ 与 path\name"})
        self.assertEqual(doc['title'], r"C/C++ 与 path\name")

    def test_homepage_has_search_scopes_and_lazy_index_reference(self):
        from unittest.mock import patch
        from bs4 import BeautifulSoup
        import extract_and_build as builder
        meta = {
            "slug": "sample", "id": "sample", "title": "**关键词**指南",
            "author_name": "萧禹", "author_username": "", "category": "SEO获客",
            "published_utc": "2026-11-03T00:00:00Z", "published_local": "2026-11-03 08:00",
            "source_type": "note", "url": "", "description": "", "tags": ["标签一"],
        }
        with patch.object(builder, "asset_version", return_value="fixture"):
            html = builder.index_page([meta])
        soup = BeautifulSoup(html, "html.parser")
        search = soup.select_one('#q[data-search-index]')
        self.assertIsNotNone(search)
        self.assertEqual(search['data-search-index'], 'assets/search-index.json?v=fixture')
        self.assertEqual([option['value'] for option in soup.select('#search-scope option')], ['all', 'title'])
        card = soup.select_one('.card[data-slug="sample"]')
        self.assertEqual(card['data-title'], '关键词指南')
        self.assertIn('标签一', card['data-q'])
        self.assertIsNotNone(soup.select_one('#search-status[aria-live="polite"]'))
        scripts = [tag['src'].split('?')[0] for tag in soup.select('script[src]')]
        self.assertLess(scripts.index('assets/search.js'), scripts.index('assets/meta.js'))
        self.assertNotIn('assets/search-index.json', scripts)


if __name__ == "__main__":
    unittest.main()
