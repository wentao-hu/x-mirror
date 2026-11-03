"""发布守门：遗漏、过期与回滚不能静默上线。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class SiteValidationTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("validate_site"), "发布需要可执行的完整性守门")
        import validate_site
        self.checker = validate_site
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ["data", "assets", "posts/first"]:
            (self.root / directory).mkdir(parents=True)
        self.meta = {"slug": "first", "title": "标题", "author_name": "甲", "author_username": "", "tags": []}
        self.write_json("data/first.json", {"meta": self.meta, "blocks": [{"type": "paragraph", "text": "完整正文"}]})
        self.write_json("posts.json", {"posts": [self.meta]})
        self.write_json("assets/search-index.json", {"version": 1, "documents": [{
            "slug": "first", "title": "标题", "metadata": "甲", "text": "完整正文",
        }]})
        (self.root / "posts/first/index.html").write_text('<article class="article"><p>完整正文</p></article>')
        self.refresh_homepage()

    def write_json(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False))

    def refresh_homepage(self):
        digest = hashlib.sha256((self.root / "assets/search-index.json").read_bytes()).hexdigest()[:8]
        (self.root / "index.html").write_text(
            f'<input id="q" data-search-index="assets/search-index.json?v={digest}">'
            '<div id="list"><a class="card" data-slug="first" href="posts/first/">标题</a></div>'
        )

    def test_complete_site_passes(self):
        self.assertEqual(self.checker.validate_local(self.root), {"first"})

    def test_missing_homepage_card_blocks_publish(self):
        path = self.root / "index.html"
        path.write_text(path.read_text().replace('class="card"', 'class="missing"'))
        with self.assertRaisesRegex(ValueError, "首页"):
            self.checker.validate_local(self.root)

    def test_duplicate_data_slug_blocks_publish(self):
        self.write_json("data/duplicate.json", {"meta": self.meta, "blocks": []})
        with self.assertRaisesRegex(ValueError, "重复"):
            self.checker.validate_local(self.root)

    def test_missing_search_document_blocks_publish(self):
        self.write_json("assets/search-index.json", {"version": 1, "documents": []})
        self.refresh_homepage()
        with self.assertRaisesRegex(ValueError, "索引"):
            self.checker.validate_local(self.root)

    def test_stale_body_or_stale_index_blocks_publish(self):
        page = self.root / "posts/first/index.html"
        page.write_text('<article class="article"><p>旧正文</p></article>')
        with self.assertRaisesRegex(ValueError, "正文|索引"):
            self.checker.validate_local(self.root)
        page.write_text('<article class="article"><p>完整正文</p></article>')
        self.write_json("data/first.json", {"meta": self.meta, "blocks": [{"type": "paragraph", "text": "改过的新正文"}]})
        with self.assertRaisesRegex(ValueError, "正文|索引"):
            self.checker.validate_local(self.root)

    def test_stale_hash_blocks_publish(self):
        path = self.root / "index.html"
        path.write_text(path.read_text().replace('?v=', '?v=old'))
        with self.assertRaisesRegex(ValueError, "版本"):
            self.checker.validate_local(self.root)

    def test_orphan_article_blocks_but_deleted_tombstone_is_allowed(self):
        orphan = self.root / "posts/orphan"
        orphan.mkdir()
        page = orphan / "index.html"
        page.write_text('<article class="article">遗漏文章</article>')
        with self.assertRaisesRegex(ValueError, "data|孤立"):
            self.checker.validate_local(self.root)
        page.write_text('<meta name="robots" content="noindex, nofollow"><p>文章已删除</p>')
        self.assertEqual(self.checker.validate_local(self.root), {"first"})

    def test_link_only_does_not_require_an_article_page(self):
        meta = {"slug": "external", "title": "外部文章", "author_name": "乙", "entry_type": "link_only", "url": "https://example.com"}
        self.write_json("posts.json", {"posts": [self.meta, meta]})
        index = json.loads((self.root / "assets/search-index.json").read_text())
        index['documents'].append({"slug": "external", "title": "外部文章", "metadata": "乙", "text": ""})
        self.write_json("assets/search-index.json", index)
        self.refresh_homepage()
        page = self.root / "index.html"
        page.write_text(page.read_text().replace('</div>', '<div class="card" data-slug="external"></div></div>'))
        self.assertEqual(self.checker.validate_local(self.root), {"first", "external"})

    def test_deploy_script_stops_before_upload_when_validation_fails(self):
        import os
        import subprocess
        import shutil
        scripts = self.root / 'scripts'
        scripts.mkdir()
        shutil.copy2(ROOT / 'scripts/deploy_cloudflare.sh', scripts / 'deploy_cloudflare.sh')
        tools = self.root / 'bin'
        tools.mkdir()
        (tools / 'git').write_text('#!/bin/sh\nif [ "$1" = branch ]; then printf "main\\n"; fi\n')
        (tools / 'python3').write_text('#!/bin/sh\ncase "$1" in *validate_site.py) exit 1;; esac\n')
        (tools / 'npx').write_text('#!/bin/sh\nprintf "unexpected upload" > "$UPLOAD_MARKER"\n')
        for tool in tools.iterdir():
            tool.chmod(0o755)
        marker = self.root / 'uploaded'
        result = subprocess.run(['bash', str(scripts / 'deploy_cloudflare.sh')],
                                env={**os.environ, 'PATH': f'{tools}:{os.environ["PATH"]}', 'UPLOAD_MARKER': str(marker)},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists(), '校验失败时不允许执行上传')

    def test_online_only_article_blocks_rollback_without_guessing_deletion(self):
        with self.assertRaisesRegex(ValueError, "线上.*missing"):
            self.checker.ensure_no_loss({"first"}, {"first", "missing"})
        self.checker.ensure_no_loss({"first", "new"}, {"first"})
        with self.assertRaisesRegex(ValueError, "线上"):
            self.checker.ensure_no_loss({"first", "new"}, {"first"}, exact=True)


if __name__ == "__main__":
    unittest.main()
