# x-mirror 项目规则

## 部署优先级（硬规则）

- **Cloudflare Pages 是主站**：https://x-mirror-af7.pages.dev/。任何改动完成后默认只部署 Cloudflare：`./scripts/deploy_cloudflare.sh`。
- **GitHub Pages 是备用站**，默认不同步、不验证、不等待。只有用户明确要求「同步 GitHub Pages」时，才 `git push` 到 `main` 并确认 GH Pages 构建完成。
- **不要为了 GitHub Pages 单独改代码或加兼容逻辑**。共享脚本里已有的 `*.github.io` 走 Cloudflare `/api/meta` 的兜底（`assets/meta.js`）保持不变。
- 部署 Cloudflare 后，GH Pages 是否为最新**不作为完成标准**；不检查两边内容一致性。

## 笔记类型（原创整理）

- 用户要求主动整理、记住的图文内容（不来自外部站点）用 `source_type: "note"`，徽标显示「自建笔记」。
- 作者统一为「萧禹」（`author_name`），`author_username` 留空，页面不显示 @handle。
- 日期写创建日期，不用内容里提到的日期。
- 不填 `url`，页面不显示「查看原文」，也不显示镜像说明。
- 数据放 `data/<slug>.json`（meta + blocks），图片放 `posts/<slug>/assets/`，然后运行 `python3 scripts/rebuild_from_data.py`。

## 副标题（description）

- 不在页面展示，只用于文章页 `meta description` 和搜索索引；**不要为它单独总结**，留空即可，构建时自动取正文前 80 字。
