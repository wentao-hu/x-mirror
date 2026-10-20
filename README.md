# X Mirror · 出海 SEO 收藏镜像

把收藏的 X（Twitter）长文做成**静态镜像站**：正文按原文顺序保留，**图片全部下载到仓库本地托管**（不热链 `pbs.twimg.com`），方便在打不开 x.com 的网络环境下阅读。

线上地址（GitHub Pages）：https://wentao-hu.github.io/x-mirror/

## 结构

```
index.html          # 目录页（分类 + 搜索）
posts.json          # 清单（标题/作者/分类/图片统计）
posts/<slug>/
  index.html        # 单篇阅读页
  assets/           # 该篇头像 + 正文图片（本地文件）
data/<slug>.json    # 抽取后的结构化数据（便于重建）
scripts/
  extract_and_build.py  # 从已抓取的 page.html + API JSON 构建
  rebuild_from_data.py  # 仅用 data/*.json + 已有 assets 重建 HTML
assets/site.css     # 共享样式（页面内也内联了一份）
```

## 本地预览

```bash
cd x-mirror
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

或直接用浏览器打开 `index.html`（`file://` 亦可）。

## 新增一篇 X 长文

1. 用可访问 X 的环境打开文章，保存完整 HTML 为 `page.html`（需含 `.x-article-body`）。
2. 用 X API / `get_posts_by_id` 拉 metadata（`article.title/plain_text/media_entities`、作者、时间），写入或合并进 `x-posts-api.json`。
3. 在 `scripts/extract_and_build.py` 的 `WORKDIRS` / `SLUGS` / `CATEGORIES` / `DESCS` 登记该 post id。
4. 运行：

```bash
python3 scripts/extract_and_build.py
```

5. 提交推送；GitHub Pages 会自动更新。

若只改了模板、数据已在 `data/` 且 `assets/` 齐：

```bash
python3 scripts/rebuild_from_data.py
```

## 分类

- 新词站实战复盘
- SEO基础
- 建站教程
- 外链推广

## 说明

- 个人阅读归档，与 X/Twitter 无关。
- 图片优先 `?format=jpg&name=orig`，失败再降级 `large`。
- 若原文在 X 上本身缺图（例如作者注明上传失败），镜像也无法造出图片，会在文末 fidelity 说明里写明。
