---
name: x-article-mirror
description: >-
  将 X / Reddit / web.cafe / 微信及境外受阻页面镜像到 x-mirror。
  机器人只抓图片，生成桌面素材包和本地 mc prompt；视频绝不下载、绝不用
  `<video>` 嵌入或 type=video 播放器块，只保留原视频普通超链接，可选本地封面图。
  全英文正文完整翻译成中文并保留专有名词。用于“映射/镜像”请求。
---
# X Article Mirror

## Goal

Create a **faithful content mirror** (not a summary):

- Full original meaning preserved (not a summary). See **Language** below for when to translate.
- **Every image** in original order, highest resolution, **downloaded into the repo** (never hotlink remote image CDNs like `pbs.twimg.com` / `mmbiz.qpic.cn` / `s.web.cafe`)
- **视频硬规则**：绝不下载；绝不用 `<video>` 嵌入；绝不使用 `type=video` 播放器块。只用普通段落链接（如 `观看原视频：<原视频 URL>`），可选把封面 / thumbnail 作为独立的 `type=image` 本地图片。原因：视频文件大、链路慢，且 Mac/twimg 传输经常失败。
- Author name, @handle or site author, avatar when available (downloaded), publish time in Asia/Shanghai (UTC+8)
- Link back to original URL
- Catalog page with Chinese categories
- Per-article **1–5 star rating** and **已读完** toggle
- **Content-type badge** next to every title + catalog type filter

## Default workflow（提速硬规则 — 外网 / 墙外链接）

Steven’s Mac often **cannot open** X, Reddit, and similar abroad sites. When he sends such a link (X, Reddit, or any other site he can’t reach locally — not limited to those two):

### Role split（可执行性）

- **Bot = 下载插件**：在 box 上抓正文 + **图片**（Mac 常打不开 twimg 等 CDN）。**不要下视频文件**；只记录原视频 URL + 下载封面图。
- **Mac 本地 `mc --code` = 写镜像**：读 scrape 包 → `data/<slug>.json` → rebuild → push → deploy。
- **不要**默认依赖 `CopyFromBox` 传大包。Scrape 完成后用 **machine Shell 把包写到 Mac 桌面**（`~/Desktop/<site>-scrape-<id>/`），再给可粘贴本地 prompt。
- 只有 Steven 明确说「你远程做 / 你代跑」才用远程 Codex / 远程 `mc --code`。

### What 代码bot / Grok Bot does (remote)

1. **Scrape only** — content pack on the box: body markdown/JSON, **images** (incl. video poster), **video remote URLs only** (no mp4/webm in the pack), optional comments, original URL, author, date, metrics.
2. **Land the pack on Mac Desktop** via machine Shell (not CopyFromBox for large media): `~/Desktop/<site>-scrape-<short-id>/`.
3. **Hand off a paste-ready local prompt** (and the Desktop folder path) for `/Users/steven/MyApps/x-mirror`.
4. **Stop.** Do **not** remotely write mirror code, rebuild, commit, push, or deploy unless he explicitly says「你远程做 / 你代跑」.

### What Steven does (local — fastest)

```bash
cd /Users/steven/MyApps/x-mirror
mc --code   # paste the prompt from the bot
```

Local CLI: read the scrape pack → write `data/<slug>.json` → `rebuild_from_data.py` → push `main` → `./scripts/deploy_cloudflare.sh`. No browser QA by the CLI. 视频只写成普通段落超链接；不得创建 `type=video` 播放器块，也不得使用本地 `assets/*.mp4`。

### Why this lives in the skill

Put the rule **here** (not only in bot memory): every assistant that opens this skill for 映射/镜像 follows the same handoff. Bot profile/memory can point here, but the recipe must be in this skill so local `mc --code` also sees it.

## Language（硬规则）

If the **post body**, **web page body**, or **included comments** are **entirely English** (or overwhelmingly English with only incidental non-English tokens):

1. **Translate the mirrored body / comments into Chinese** for the site display text (`blocks` / `plain_text` and any「精选评论」section).
2. **Keep proper nouns** in the original form when natural: product names, brand names, person names, company names, place names, tickers, URLs, code identifiers, SEO acronyms (e.g. SEO, Stripe, Cloudflare), and similar.
3. Do **not** invent facts; translation must track the source. Mixed Chinese–English content stays as-is (no forced full translation).
4. Still keep a clear link to the original URL. Optional: note in `fidelity_note` that display text was translated from English.
5. Titles: prefer a concise **Chinese** title (invent one for untitled `x_post` as before).

## Prefer local `mc --code`

When working on Steven’s Mac:

1. Open repo `/Users/steven/MyApps/x-mirror`.
2. Use this skill (project `.claude/skills/x-article-mirror/` or a copy under `~/.claude/skills/` / Desktop `x-article-mirror/`).
3. Run **local** `mc --code` for scrape-pack → `data/<slug>.json` → rebuild → commit → push → `./scripts/deploy_cloudflare.sh`.
4. Do **not** open browsers / Playwright for visual QA; user checks the live site by eye.
5. Push straight to `main` (no PR, never force-push) unless user says otherwise.

Grok Bot / 代码bot should **scrape + land pack on Desktop + write the local prompt**; heavy mirroring is **always** faster when Steven runs local `mc --code`. Remote Codex / remote `mc --code` only when he explicitly asks to 代跑. Never touch `~/.claude/quota-state`.

### Paste-ready prompt template (bot fills paths)

```
按 .claude/skills/x-article-mirror/SKILL.md（或桌面 x-article-mirror/SKILL.md）：
用 <SCRAPE_DIR> 里的内容镜像原文 <ORIGINAL_URL>。
- source_type: <TYPE>；slug: <SLUG>
- 标题：「<CHINESE_TITLE>」；分类用仓库里已有中文类目
- 正文/评论按 Language 规则（全英文则译中文，专有名词保留）
- 图片从 scrape 包拷入 posts/<slug>/assets/，禁止热链外网图片 CDN
- 视频绝不下载进仓库，也不要用 `<video>` 或 `type=video` 播放器块；只用普通段落链接（如「观看原视频：<原视频 URL>」）。封面可选，作为独立 `type=image`
- 写 data/<slug>.json → python3 scripts/rebuild_from_data.py → 只提交相关文件（包括 `.claude/skills/x-article-mirror/SKILL.md`）→ push main → ./scripts/deploy_cloudflare.sh
- 不要开浏览器验证
```

## Content type (`source_type`) — required

| source_type | Meaning | Badge |
|---|---|---|
| `x_article` | X long-form **Article** | 𝕏 长文（紫） |
| `x_post` | Normal X tweet / note_tweet / thread (no Article) | 𝕏 帖子（橙） |
| `web_article` | Ordinary web page (non-X, non-web.cafe, non-WeChat, non-Reddit) | 🌐 网页（灰青） |
| `webcafe` | Content from `new.web.cafe` (full mirror **or** link-only) | **web.cafe**（蓝系） |
| `wechat` | WeChat 公众号 (`mp.weixin.qq.com`) | **微信**（绿系） |
| `reddit` | Reddit post (`reddit.com` / `old.reddit.com`) | **Reddit**（橙红 #FF4500） |

**Migrate legacy:** `webcafe_link` / `entry_type: link_only` → normalize display type to `webcafe`.

**X detection (hard rule — never guess by length):**

1. Call X API with article expansions → `x_article`.
2. Else tweet / `note_tweet` / thread → `x_post`.
3. Never classify by character count or image count.

Catalog type filter: **全部 / 帖子 / 长文 / 网页 / web.cafe / 微信 / Reddit**（另有评分 / 已读 / 排序）。

Templates live in `scripts/extract_and_build.py`, `assets/meta.js`, `assets/site.css` — **never hand-edit generated HTML**.

For an `x_post` with no title, invent a concise Chinese title and tell the user.

### Badge implementation notes

Touch `SOURCE_TYPE_LABELS`, `source_type_of()`, `source_badge()`, index filter `data-type` buttons, and `.source-badge[data-source-type="…"]` colors:

- `x_article`: purple · `x_post`: orange · `web_article`: grey-teal
- `webcafe`: blue · `wechat`: green · `reddit`: **#FF4500**

## new.web.cafe / 微信 / Reddit

- 用户点名某篇才映射；禁止批量抓取。
- web.cafe：默认全文，`source_type: webcafe`；link-only 仍用 `entry_type: link_only` + 同徽标。
- 微信：去广告/文末联系方式 CTA；`source_type: wechat`。
- Reddit：正文 + 可选「精选评论」；`source_type: reddit`。
- 三者都走 **Default workflow**：Mac 打不开时先 scrape 包落到桌面，再给本地 prompt。

## Hosting

- **Primary:** https://x-mirror-af7.pages.dev/
- **Backup:** https://wentao-hu.github.io/x-mirror/
- **Repo:** https://github.com/wentao-hu/x-mirror
- **Local:** `/Users/steven/MyApps/x-mirror`
- Deploy: `cd /Users/steven/MyApps/x-mirror && ./scripts/deploy_cloudflare.sh`

## Performance

- Slash links `posts/<slug>/`；原图 + webp/lazy；`_headers` 按现有约定。
- **绝不**把视频文件提交到 `posts/*/assets/`；视频只展示为原站普通超链接，不下载、不嵌入。

## Pipeline

1. 外网链接 → **box scrape（图下、视频只记 URL）** → **Desktop 落地** → **本地 prompt** → Steven 本地 `mc --code`。
2. 写对 `source_type`；`data/<slug>.json`；`python3 scripts/rebuild_from_data.py`。
3. Commit、push main、Cloudflare deploy（本地完成）。
4. 回复：站内 URL、标题、作者、type、分类；英译中则说明。

`data/<slug>.json` shape: `{ "meta": {...}, "blocks": [...], "plain_text": "...", "entities": {} }`。`meta.source_type` 必填。视频优先写成普通 `paragraph` 链接；封面另写 `type=image`。旧数据若仍含 `type=video`，渲染器只能输出普通链接，绝不输出播放器。

## Rating / read / filters

- Stars + 已读完；KV `ARTICLE_META` / `meta:v1` / namespace `9de02bd9638042c0b0289fb3022f8ddd`；不随意改 KV 语义。

## Fidelity

Not webpage-to-html 精读. Missing images stated honestly. Translation (when Language applies) allowed; summarizing is not. 视频只以原帖普通超链接展示；不下载、不使用 `<video>` 嵌入或 `type=video` 播放器块。这是硬规则，不算 fidelity failure。
