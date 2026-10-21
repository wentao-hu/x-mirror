# X Mirror · 出海 SEO 收藏镜像

把收藏的 X（Twitter）长文做成**静态镜像站**：正文按原文顺序保留，**图片全部下载到仓库本地托管**（不热链 `pbs.twimg.com`），方便在打不开 x.com 的网络环境下阅读。

## 线上地址

**日常阅读（快）：** https://wentao-hu.github.io/x-mirror/

**评分同步 / 备用：** https://x-mirror-af7.pages.dev/

GitHub Pages 只托管静态页面；评分与已读在浏览器本机即时生效，并通过 CORS 后台同步到 Cloudflare `/api/meta` 的 KV。Cloudflare 不通时退回本机，联网后自动补传。

仓库：https://github.com/wentao-hu/x-mirror

> 说明：`x-mirror.pages.dev` 已被他人占用，本项目生产域名为 `x-mirror-af7.pages.dev`。

## 结构

```
index.html            # 文章页（分类 + 搜索 + 评分/已读筛选）
sites.html            # 网站收藏页（按分类分组，logo + 标题链接）
sites.json            # 网站收藏清单（标题/链接/分类/logo）
posts.json            # 清单（标题/作者/分类/来源类型/图片统计，entry_type: mirror | link_only）
posts/<slug>/
  index.html          # 单篇阅读页（内置评分 + 已读完控件）
  assets/             # 该篇头像 + 正文图片（本地文件）
data/<slug>.json      # 抽取后的结构化数据（便于重建）
assets/
  site.css            # 共享样式（模板以 ?v=<content-hash> 引用）
  meta.js             # 评分/已读共享脚本（KV + localStorage）
  sites/              # 收藏网站的 logo，全部本地托管
functions/api/meta.js # Pages Function：GET/PUT 评分与已读
_headers              # Cloudflare Pages 缓存策略
wrangler.toml         # Pages 配置 + ARTICLE_META KV 绑定
scripts/
  extract_and_build.py  # 从已抓取的 page.html + API JSON 构建
  rebuild_from_data.py  # 仅用 data/*.json + 已有 assets 重建 HTML
  generate_webp.py      # 为 jpg/jpeg/png 生成同名 WebP 副本
  deploy_cloudflare.sh  # 用 wrangler 部署到 Cloudflare Pages
```

## 本地预览

```bash
cd /Users/steven/MyApps/x-mirror
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

## 加载与缓存

- **尾斜杠链接**：目录卡片指向 `posts/<slug>/`，文章页品牌/目录链接指向 `../../`，由 Pages 直接返回 `index.html`。
- **静态资源版本化**：`assets/site.css`、`assets/meta.js` 以 `?v=<sha256 前 8 位>` 引用，哈希在构建时按文件内容计算。
- **WebP**：`scripts/generate_webp.py` 为 `assets/` 和 `posts/*/assets/` 下的 jpg/jpeg/png 生成同名 `.webp`（`cwebp -q 90 -metadata none`，保留原图，源图更新才重建）。模板在 WebP 存在时输出 `<picture><source type="image/webp">`，并保留原 `<img>` 属性；`picture { display: contents; }` 保证布局不变。正文图片和封面使用 `loading="lazy" decoding="async"`，头像保持 eager。`rebuild_from_data.py` 与提取流程会在生成 HTML 前自动调用。
- **`_headers`**：`/`、`/*.html`、`/posts/*/`、`/posts/*/index.html` 为 `max-age=0, must-revalidate`；`/assets/*`、`/posts/:slug/assets/*` 为一年 `immutable`；`/api/*` 为 `no-store`（Functions 响应本身也在 `functions/api/meta.js` 里设置了 `no-store`）。Cloudflare 每条规则只允许一个 `*`，文章资源规则用 `:slug` 占位符避免与 HTML 规则重叠。

## 评分与已读

每篇文章都可以标记：

- **1–5 星评分**：再点一次当前分数即清除（回到未评分）；文章页还提供「清除」按钮。
- **已读完**：标题下方的胶囊按钮一键切换。

目录页支持按类型（全部 / 帖子 / 长文 / 网页 / 仅链接）、评分（全部 / 未评分 / ≥1★…5★）、阅读状态（全部 / 已读完 / 未读）筛选，以及默认 / 评分高→低 / 未读优先排序，各条件可叠加。镜像卡片上显示只读星级和「已读」徽标；`link_only` 卡片（无详情页）直接在卡片上提供可点击的星级与「已读完」按钮。

数据持久化：

| 层 | 位置 | 作用 |
| --- | --- | --- |
| 主存储 | Cloudflare KV `ARTICLE_META`，单 key `meta:v1` | 跨设备同步，`PUT /api/meta` 写入 |
| 本地缓存 | `localStorage` key `x-mirror-meta-v1` | 立即生效、离线可读；页面加载时与服务端合并 |

合并规则是 **last-write-wins**：每条记录带 `updatedAt`（ISO 时间），本地与服务端逐 slug 比较，保留更新时间较新的一条。离线期间产生的本地修改会在下次正常联网打开页面时自动补传到 KV。

直接用 `file://` 打开页面时不会请求 API，只在 `localStorage` 里保存，页面会显示一行灰色提示。GitHub Pages 站点没有 Pages Functions，`assets/meta.js` 会在 `*.github.io` 上改调 Cloudflare 的 `/api/meta`（已开 CORS）同步评分；Cloudflare 不可达时退回本机，联网后自动补传。

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

评分与已读控件由 `extract_and_build.py` 里的 `post_page` / `index_page` 模板生成。只想用 `data/*.json` 重建页面时运行 `python3 scripts/rebuild_from_data.py`，会同时重写 `assets/site.css`、补齐 WebP 副本并保留所有文章页的控件。

## 网站收藏

目录页顶部有「文章 / 网站」两个 tab：`index.html` 是文章列表，`sites.html` 是网站收藏。网站页按分类分组，每个网站显示本地 logo、标题（超链接，新窗口打开）和域名。

收藏数据在根目录 `sites.json`，新增一个网站加一条即可：

```json
{
  "slug": "stripe",
  "title": "Stripe",
  "url": "https://stripe.com/cn",
  "category": "支付",
  "logo": "assets/sites/stripe.svg"
}
```

- `category` 决定分组。分组顺序由 `scripts/extract_and_build.py` 的 `SITE_CATEGORY_ORDER` 控制，未列出的分类排在后面。
- `logo` 可省略，省略时显示标题首字母。图片下载到 `assets/sites/`，与文章图片一样本地托管。
- 改完运行 `python3 scripts/rebuild_from_data.py`，会重新生成 `sites.html`。

## 内容类型（source_type）

`data/*.json` 的 `meta` 与 `posts.json` 的每条记录都带 `source_type`，用于目录卡片/文章页标题旁的徽标和目录页「类型」筛选：

| source_type | 徽标 | 说明 |
| --- | --- | --- |
| `x_post` | 𝕏 帖子 | 普通 X 推文镜像 |
| `x_article` | 𝕏 长文 | X 长文/Article 镜像 |
| `web_article` | 🌐 网页 | 外部网页镜像 |
| `webcafe_link` | web.cafe · 仅链接 | web.cafe 仅链接条目，同时保留 `entry_type: link_only` |

构建时卡片会输出 `data-source-type`，`assets/meta.js` 据此与分类、搜索、评分、已读、排序条件叠加过滤；缺失该字段的旧数据按 `entry_type` 回退（链接条目 → `webcafe_link`，其余 → `x_post`）。抽取脚本默认写入 `x_post`，其他类型在 `data/*.json` 中标注。

## 仅链接条目（web.cafe / 好友 VIP 站）

`new.web.cafe` 是朋友的 VIP 站点，站内文章**永远只做目录条目，不做镜像**：

- **不抓取正文、不镜像、不下载/存储图片、不自动对该 host 发起任何 HTTP 请求**。
- 目录里只保留：标题、作者、日期、原文 URL。
- 卡片标题直接外链原文（`target="_blank" rel="noopener noreferrer"`），并显示徽标 `web.cafe · 仅链接`。
- 不生成 `posts/<slug>/` 目录，也不生成 `data/<slug>.json`。
- 评分 1–5★、已读完、筛选/排序都在**目录卡片上**操作，复用同一个 `assets/meta.js` 与 KV slug key。
- 分类使用 `web.cafe 精选`。

`posts.json` 中这类条目标记 `"entry_type": "link_only"`；X 镜像条目默认是 `mirror`（可省略）。

### 新增一个 link_only 条目

1. 在 `posts.json` 的 `posts` 数组里追加一条（不要创建 `posts/` 或 `data/` 文件）：

```json
{
  "id": "w6k45cpc42",
  "slug": "webcafe-w6k45cpc42",
  "title": "入群15个月，月入万刀走过的那些弯路",
  "url": "https://new.web.cafe/topic/w6k45cpc42",
  "author_name": "浩承yang",
  "author_username": "web.cafe",
  "published_utc": "2026-10-19T13:20:00.000Z",
  "published_local": "2026-10-19 21:20",
  "category": "web.cafe 精选",
  "description": "web.cafe 仅链接 · 不镜像正文",
  "source_type": "webcafe_link",
  "entry_type": "link_only",
  "avatar_local": "",
  "images_total": 0,
  "images_ok": 0,
  "api_media_count": 0,
  "fidelity_note": "link_only: no body mirror",
  "plain_text_len": 0,
  "blocks_count": 0
}
```

2. 运行 `python3 scripts/rebuild_from_data.py`。脚本会从旧 `posts.json` 收集 `entry_type == "link_only"` 的条目并按 slug 合并回去，再重建 `index.html`、`posts.json` 与 `assets/site.css`。
3. `git push` 后执行 `./scripts/deploy_cloudflare.sh`，回复 https://x-mirror-af7.pages.dev/ 。

> 注意：`slug` 必须匹配 `^[a-z0-9][a-z0-9-]{0,79}$`（与 `assets/meta.js` 的 `SLUG_RE` 一致），否则评分/已读不会生效。

## 分类

- 新词站实战复盘
- SEO基础
- 建站教程
- 外链推广
- web.cafe 精选（仅链接）

## 说明

- 个人阅读归档，与 X/Twitter 无关。
- 图片优先 `?format=jpg&name=orig`，失败再降级 `large`。
- 若原文在 X 上本身缺图，镜像也无法造出，会在文末 fidelity 说明里写明。
