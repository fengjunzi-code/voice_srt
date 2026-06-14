from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import path_config as paths
from log_utils import install_timestamped_print


install_timestamped_print()


VIDEO_DIR = paths.VIDEO_EN_DIR
SUPPORTED_INPUT_EXTS = {
    ".avi",
    ".flv",
    ".m4k",
    ".m4v",
    ".mkv",
    ".mov",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}


def build_stream_copy_cmd(src_path: Path, dst_path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(dst_path),
    ]


def build_transcode_cmd(src_path: Path, dst_path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(dst_path),
    ]


def convert_to_mp4(src_path: Path, dst_path: Path) -> str:
    try:
        subprocess.run(build_stream_copy_cmd(src_path, dst_path), check=True, capture_output=True)
        return "封装转换"
    except subprocess.CalledProcessError:
        if dst_path.exists():
            dst_path.unlink()
        print("  封装转换失败，改用重编码，耗时会明显变长...")
        subprocess.run(build_transcode_cmd(src_path, dst_path), check=True)
        return "重编码"


def delete_source_after_success(src_path: Path, dst_path: Path) -> None:
    if not dst_path.exists() or dst_path.stat().st_size == 0:
        raise RuntimeError(f"转换后的 MP4 不存在或为空，保留原文件: {src_path.name}")

    src_path.unlink()


def find_convertible_videos() -> list[Path]:
    if not VIDEO_DIR.exists():
        return []

    files = [
        path
        for path in VIDEO_DIR.glob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_EXTS
    ]
    return sorted(files, key=lambda path: path.name.lower())


def main() -> int:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    video_files = find_convertible_videos()
    if not video_files:
        print(f"未发现需要转换的非 MP4 视频: {VIDEO_DIR}")
        return 0

    print(f"发现 {len(video_files)} 个非 MP4 视频，准备转换为 MP4...\n")

    success_count = 0
    fail_count = 0
    skipped_count = 0

    for index, src_path in enumerate(video_files, 1):
        file_stem = paths.safe_stem(src_path)
        dst_path = VIDEO_DIR / f"{file_stem}.mp4"

        if dst_path.exists():
            print(f"[{index}/{len(video_files)}] 跳过已存在: {dst_path.name}")
            skipped_count += 1
            continue

        tmp_path = VIDEO_DIR / f"{file_stem}.mp4.tmp"
        if tmp_path.exists():
            tmp_path.unlink()

        print(f"[{index}/{len(video_files)}] 正在转换: {src_path.name} -> {dst_path.name}")
        try:
            convert_mode = convert_to_mp4(src_path, tmp_path)
            tmp_path.replace(dst_path)
            delete_source_after_success(src_path, dst_path)
            success_count += 1
            print(f"  [成功] {convert_mode}完成，已删除原视频")
        except subprocess.CalledProcessError as exc:
            fail_count += 1
            if tmp_path.exists():
                tmp_path.unlink()
            stderr = exc.stderr.decode("utf-8", errors="replace").strip()
            print(f"  [失败] FFmpeg 错误: {stderr[-1000:]}")
        except Exception as exc:
            fail_count += 1
            if tmp_path.exists():
                tmp_path.unlink()
            print(f"  [失败] {type(exc).__name__}: {exc}")

    print("\n转换任务完成")
    print(f"成功: {success_count}")
    print(f"跳过: {skipped_count}")
    print(f"失败: {fail_count}")
    print(f"目录: {VIDEO_DIR}")

    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
