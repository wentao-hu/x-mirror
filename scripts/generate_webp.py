#!/usr/bin/env python3
"""为镜像图片生成同目录 WebP 副本（保留原图，源文件更新时才重建）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CWEBP = Path("/opt/homebrew/bin/cwebp")
QUALITY = "90"
SOURCE_EXTS = {".jpg", ".jpeg", ".png"}


def iter_sources(root: Path):
    """遍历 assets/ 与 posts/*/assets/ 下的 jpg/jpeg/png。"""
    dirs = [root / "assets"]
    dirs.extend(sorted((root / "posts").glob("*/assets")))
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SOURCE_EXTS:
                continue
            # 站点图标/favicon 由浏览器和 manifest 直接引用 PNG，不需要 WebP 副本
            if (directory == root / "assets"
                    and path.name.startswith(("favicon", "icon-", "apple-touch-icon"))):
                continue
            yield path


def ensure_webp(src: Path) -> bool:
    """生成 src 对应的 .webp。已是最新则跳过，返回是否实际转换。"""
    dest = src.with_suffix(".webp")
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return False

    proc = subprocess.run(
        [str(CWEBP), "-q", QUALITY, "-metadata", "none", "-quiet", str(src), "-o", str(dest)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"cwebp 失败: {src}\n{proc.stderr.strip()}")
    return True


def generate_all(root: Path = ROOT) -> int:
    """为全部源图补齐 WebP 副本，返回本次转换数量。"""
    if not CWEBP.exists():
        print(f"[warn] 未找到 cwebp: {CWEBP}，跳过 WebP 生成")
        return 0

    converted = 0
    skipped = 0
    for src in iter_sources(root):
        if ensure_webp(src):
            converted += 1
        else:
            skipped += 1
    print(f"webp: 转换 {converted}，已是最新 {skipped}")
    return converted


if __name__ == "__main__":
    generate_all()
