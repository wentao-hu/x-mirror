# X Mirror · 出海 SEO 收藏镜像

把收藏的 X（Twitter）长文做成**静态镜像站**：正文按原文顺序保留，**图片全部下载到仓库本地托管**（不热链 `pbs.twimg.com`），方便在打不开 x.com 的网络环境下阅读。

## 线上地址（主）

**Cloudflare Pages（推荐，国内更稳）：** https://x-mirror-af7.pages.dev/

备用 GitHub Pages：https://wentao-hu.github.io/x-mirror/

仓库：https://github.com/wentao-hu/x-mirror

> 说明：`x-mirror.pages.dev` 已被他人占用，本项目生产域名为 `x-mirror-af7.pages.dev`。

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
  deploy_cloudflare.sh  # 用 wrangler 部署到 Cloudflare Pages
assets/site.css
```

## 本地预览

```bash
cd /Users/steven/MyApps/x-mirror
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

## 部署到 Cloudflare Pages

本机已用 `wrangler`（账号 stevenhwt@gmail.com）直传静态资源，**当前未绑定 GitHub 自动构建**（绑定需在 Cloudflare Dashboard 点 Connect to Git）。

更新内容后发布：

```bash
./scripts/deploy_cloudflare.sh
# 等价于：
# npx wrangler pages deploy . --project-name x-mirror --branch main --commit-dirty=true
```

Dashboard：https://dash.cloudflare.com/076d9900e41523cdf41030af6f7d4326/pages/view/x-mirror

若要改成「push 到 GitHub 自动部署」，在 Dashboard → Workers & Pages → x-mirror → Settings → Builds & deployments → Connect to Git，选 `wentao-hu/x-mirror`，构建命令留空、输出目录填 `/`（或 `.`）。

## 新增一篇 X 长文

1. 用可访问 X 的环境打开文章，保存完整 HTML 为 `page.html`（需含 `.x-article-body`）。
2. 用 X API / `get_posts_by_id` 拉 metadata，合并进构建用的 API JSON。
3. 在 `scripts/extract_and_build.py` 的 `WORKDIRS` / `SLUGS` / `CATEGORIES` / `DESCS` 登记该 post id。
4. 运行 `python3 scripts/extract_and_build.py`
5. `git push` 后执行 `./scripts/deploy_cloudflare.sh`（或等 Git 绑定自动部署）。

## 分类

- 新词站实战复盘
- SEO基础
- 建站教程
- 外链推广

## 说明

- 个人阅读归档，与 X/Twitter 无关。
- 图片优先 `?format=jpg&name=orig`，失败再降级 `large`。
- 若原文在 X 上本身缺图，镜像也无法造出，会在文末 fidelity 说明里写明。
