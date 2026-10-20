# X Mirror · 出海 SEO 收藏镜像

把收藏的 X（Twitter）长文做成**静态镜像站**：正文按原文顺序保留，**图片全部下载到仓库本地托管**（不热链 `pbs.twimg.com`），方便在打不开 x.com 的网络环境下阅读。

## 线上地址（主）

**Cloudflare Pages（推荐，国内更稳）：** https://x-mirror-af7.pages.dev/

备用 GitHub Pages：https://wentao-hu.github.io/x-mirror/

仓库：https://github.com/wentao-hu/x-mirror

> 说明：`x-mirror.pages.dev` 已被他人占用，本项目生产域名为 `x-mirror-af7.pages.dev`。

## 结构

```
index.html            # 目录页（分类 + 搜索 + 评分/已读筛选）
posts.json            # 清单（标题/作者/分类/图片统计）
posts/<slug>/
  index.html          # 单篇阅读页（内置评分 + 已读完控件）
  assets/             # 该篇头像 + 正文图片（本地文件）
data/<slug>.json      # 抽取后的结构化数据（便于重建）
assets/
  site.css            # 共享样式（页面实际内联同一份 CSS）
  meta.js             # 评分/已读共享脚本（KV + localStorage）
functions/api/meta.js # Pages Function：GET/PUT 评分与已读
wrangler.toml         # Pages 配置 + ARTICLE_META KV 绑定
scripts/
  extract_and_build.py  # 从已抓取的 page.html + API JSON 构建
  rebuild_from_data.py  # 仅用 data/*.json + 已有 assets 重建 HTML
  deploy_cloudflare.sh  # 用 wrangler 部署到 Cloudflare Pages
```

## 本地预览

```bash
cd /Users/steven/MyApps/x-mirror
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

## 评分与已读

每篇文章都可以标记：

- **1–5 星评分**：再点一次当前分数即清除（回到未评分）；文章页还提供「清除」按钮。
- **已读完**：标题下方的胶囊按钮一键切换。

目录页支持按评分（全部 / 未评分 / ≥1★…5★）、阅读状态（全部 / 已读完 / 未读）筛选，以及默认 / 评分高→低 / 未读优先排序。卡片上直接显示星级和「已读」徽标。

数据持久化：

| 层 | 位置 | 作用 |
| --- | --- | --- |
| 主存储 | Cloudflare KV `ARTICLE_META`，单 key `meta:v1` | 跨设备同步，`PUT /api/meta` 写入 |
| 本地缓存 | `localStorage` key `x-mirror-meta-v1` | 立即生效、离线可读；页面加载时与服务端合并 |

合并规则是 **last-write-wins**：每条记录带 `updatedAt`（ISO 时间），本地与服务端逐 slug 比较，保留更新时间较新的一条。离线期间产生的本地修改会在下次正常联网打开页面时自动补传到 KV。

直接用 `file://` 打开页面时不会请求 API，只在 `localStorage` 里保存，页面会显示一行灰色提示。GitHub Pages 备用站点没有 Functions，同样自动降级为本地模式。

KV 绑定写在 `wrangler.toml`：

```toml
[[kv_namespaces]]
binding = "ARTICLE_META"
id = "9de02bd9638042c0b0289fb3022f8ddd"
```

## 部署到 Cloudflare Pages

本机已用 `wrangler`（账号 stevenhwt@gmail.com）直传静态资源，**当前未绑定 GitHub 自动构建**（绑定需在 Cloudflare Dashboard 点 Connect to Git）。

更新内容后发布：

```bash
./scripts/deploy_cloudflare.sh
# 等价于：
# npx wrangler pages deploy . --project-name x-mirror --branch main --commit-dirty=true
```

`wrangler pages deploy` 会同时上传根目录的 `functions/`，并按 `wrangler.toml` 绑定 KV。若部署时报 namespace 不存在，先到 Dashboard → Workers & Pages → KV 确认 `9de02bd9638042c0b0289fb3022f8ddd` 属于当前账号。

Dashboard：https://dash.cloudflare.com/076d9900e41523cdf41030af6f7d4326/pages/view/x-mirror

若要改成「push 到 GitHub 自动部署」，在 Dashboard → Workers & Pages → x-mirror → Settings → Builds & deployments → Connect to Git，选 `wentao-hu/x-mirror`，构建命令留空、输出目录填 `/`（或 `.`）。

## 新增一篇 X 长文

1. 用可访问 X 的环境打开文章，保存完整 HTML 为 `page.html`（需含 `.x-article-body`）。
2. 用 X API / `get_posts_by_id` 拉 metadata，合并进构建用的 API JSON。
3. 在 `scripts/extract_and_build.py` 的 `WORKDIRS` / `SLUGS` / `CATEGORIES` / `DESCS` 登记该 post id。
4. 运行 `python3 scripts/extract_and_build.py`
5. `git push` 后执行 `./scripts/deploy_cloudflare.sh`（或等 Git 绑定自动部署）。

评分与已读控件由 `extract_and_build.py` 里的 `post_page` / `index_page` 模板生成。只想用 `data/*.json` 重建页面时运行 `python3 scripts/rebuild_from_data.py`，会同时重写 `assets/site.css` 并保留所有文章页的控件。

## 分类

- 新词站实战复盘
- SEO基础
- 建站教程
- 外链推广

## 说明

- 个人阅读归档，与 X/Twitter 无关。
- 图片优先 `?format=jpg&name=orig`，失败再降级 `large`。
- 若原文在 X 上本身缺图，镜像也无法造出，会在文末 fidelity 说明里写明。
