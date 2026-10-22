#!/usr/bin/env python3
"""聊天记录换行渲染回归测试。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import extract_and_build as builder


class ChatNewlineRenderingTest(unittest.TestCase):
    def test_single_blank_line_becomes_exactly_two_breaks(self):
        rendered = builder.linkify("第一段\n\n第二段")
        self.assertEqual(rendered, "第一段<br><br>第二段")
        self.assertNotIn("\n", rendered)

    def test_mixed_single_and_blank_lines_do_not_double_render(self):
        rendered = builder.linkify("第一段\n\n第二段\n第三段")
        self.assertEqual(rendered, "第一段<br><br>第二段<br>第三段")
        self.assertNotIn("\n", rendered)

    def test_content_tags_render_and_ignore_empty_values(self):
        rendered = builder.tags_html(
            {"tags": ["海外收款", "", None, "Stripe"]},
            show_label=True,
        )
        self.assertIn("内容标签", rendered)
        self.assertIn("海外收款", rendered)
        self.assertIn("Stripe", rendered)
        self.assertNotIn("None", rendered)


if __name__ == "__main__":
    unittest.main()
