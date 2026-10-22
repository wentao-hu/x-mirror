# x-mirror 项目规则

## 部署优先级（硬规则）

- **Cloudflare Pages 是主站**：https://x-mirror-af7.pages.dev/。任何改动完成后默认只部署 Cloudflare：`./scripts/deploy_cloudflare.sh`。
- **GitHub Pages 是备用站**，默认不同步、不验证、不等待。只有用户明确要求「同步 GitHub Pages」时，才 `git push` 到 `main` 并确认 GH Pages 构建完成。
- **不要为了 GitHub Pages 单独改代码或加兼容逻辑**。共享脚本里已有的 `*.github.io` 走 Cloudflare `/api/meta` 的兜底（`assets/meta.js`）保持不变。
- 部署 Cloudflare 后，GH Pages 是否为最新**不作为完成标准**；不检查两边内容一致性。
