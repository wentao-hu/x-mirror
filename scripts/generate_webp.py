#!/usr/bin/env python3
"""为镜像图片生成同目录 WebP 副本（保留原图，源文件更新时才重建）。

每张源图生成三档：原尺寸 <name>.webp、960px <name>-960.webp、640px <name>-640.webp。
模板按原图宽度输出 srcset；原图不足 960/640 时不生成对应档，避免放大。
调整 QUALITY 后旧文件会全量重建（根目录 .webp-quality 记录当前质量）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CWEBP = Path("/opt/homebrew/bin/cwebp")
QUALITY = "82"
WIDTHS = (640, 960, 1280)
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


def image_width(path: Path) -> int:
    """读取图片像素宽度；读不到返回 0。"""
    try:
        out = subprocess.check_output(
            ["sips", "-g", "pixelWidth", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(out.strip().split()[-1])
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 0


def _encode(src: Path, dest: Path, width: int | None) -> None:
    cmd = [str(CWEBP), "-q", QUALITY, "-metadata", "none", "-quiet"]
    if width:
        cmd += ["-resize", str(width), "0"]
    cmd += [str(src), "-o", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"cwebp 失败: {src}\n{proc.stderr.strip()}")


def ensure_variants(src: Path, force: bool = False) -> int:
    """生成原尺寸与各宽度档，返回实际转换的文件数。"""
    changed = 0
    width = image_width(src)
    targets: list[tuple[Path, int | None]] = [(src.with_suffix(".webp"), None)]
    if width:
        for w in WIDTHS:
            if width > w:
                targets.append((src.with_name(f"{src.stem}-{w}.webp"), w))
    for dest, w in targets:
        fresh = dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime
        if fresh and not force:
            continue
        _encode(src, dest, w)
        changed += 1
    return changed


def generate_all(root: Path = ROOT) -> int:
    """为全部源图补齐 WebP 副本，返回本次转换数量。"""
    if not CWEBP.exists():
        print(f"[warn] 未找到 cwebp: {CWEBP}，跳过 WebP 生成")
        return 0

    stamp = root / ".webp-quality"
    try:
        force = stamp.read_text(encoding="utf-8").strip() != QUALITY
    except OSError:
        force = True

    converted = 0
    skipped = 0
    for src in iter_sources(root):
        n = ensure_variants(src, force)
        converted += n
        if n == 0:
            skipped += 1
    stamp.write_text(QUALITY + "\n", encoding="utf-8")
    print(f"webp: 转换 {converted}，已是最新 {skipped}")
    return converted


if __name__ == "__main__":
    generate_all()
