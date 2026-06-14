import os
import re
import shutil
import subprocess
import sys
import wave
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import path_config as paths
from log_utils import install_timestamped_print


install_timestamped_print()

# --- 路径配置 (已更新为绝对路径) ---
SRT_DIR = paths.SRT_CN_AFTER_DIR
INPUT_BASE = paths.BEFORE_SPEED_DIR
OUTPUT_BASE = paths.AFTER_SPEED_DIR

# --- FFmpeg 参数 ---
SILENCE_NOISE_DB = "-42dB"
SILENCE_DURATION = 0.18
SILENCE_PADDING = 0.10


def parse_srt_timestamp(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(srt_path: Path) -> list[dict]:
    try:
        text = srt_path.read_text(encoding="utf-8-sig")
    except:
        text = srt_path.read_text(encoding="gbk", errors="ignore")

    blocks = re.split(r"\n\s*\n+", text.strip())
    ts_re = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")
    entries = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2: continue
        try:
            seq = int(lines[0])
            m = ts_re.search(lines[1])
            if not m: continue
            start = parse_srt_timestamp(m.group(1))
            end = parse_srt_timestamp(m.group(2))
            entries.append({"seq": seq, "start": start, "end": end, "duration": end - start})
        except ValueError:
            continue
    return entries


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _run_ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def trim_trailing_silence(src: str, dst: str) -> None:
    filter_complex = (
        f"silenceremove=stop_periods=-1:"
        f"stop_duration={SILENCE_DURATION}:"
        f"stop_threshold={SILENCE_NOISE_DB}:"
        f"stop_silence={SILENCE_PADDING}:"
        f"detection=peak"
    )
    _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-af", filter_complex, "-c:a", "pcm_s16le", dst])


def pick_speed(audio_dur: float, sub_dur: float) -> float | None:
    if audio_dur <= sub_dur: return None
    speed = max(1.1, round(audio_dur / sub_dur, 1))
    if audio_dur / speed >= sub_dur:
        speed = round(speed + 0.1, 1)
    while speed <= 100.0 and audio_dur / speed >= sub_dur:
        speed = round(speed + 0.1, 1)
    return speed


def speed_up_audio(src: str, dst: str, speed: float) -> None:
    _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-filter:a", f"atempo={speed:.1f}", "-c:a", "pcm_s16le", dst])


def _prepare_one(args: tuple[int, dict, Path, Path]) -> dict:
    seq, entry, audio_dir, tmp_dir = args
    sub_dur = entry["duration"]
    wav_name = f"{seq:03d}.wav"
    src_path = audio_dir / wav_name
    tmp_path = tmp_dir / wav_name

    if not src_path.exists():
        return {"seq": seq, "missing": True}

    raw_dur = get_wav_duration(src_path)
    try:
        trim_trailing_silence(str(src_path), str(tmp_path))
        trimmed_dur = get_wav_duration(tmp_path)
    except Exception:
        shutil.copy2(src_path, tmp_path)
        trimmed_dur = raw_dur

    speed = pick_speed(trimmed_dur, sub_dur)
    return {
        "seq": seq, "missing": False, "tmp_path": str(tmp_path),
        "raw_dur": raw_dur, "trimmed_dur": trimmed_dur, "speed": speed,
    }


def format_time(seconds: float) -> str:
    """支持时:分:秒的格式化"""
    if seconds < 0: return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def show_progress(current: float, total: float, start_time: float, prefix=""):
    """使用统一修复版的进度条，防止99%卡住及残留"""
    width = 30
    elapsed = time.time() - start_time

    if current >= total:
        ratio = 1.0
        eta = 0.0
    else:
        ratio = current / total if total > 0 else 0
        eta = (elapsed / ratio - elapsed) if ratio > 0.05 else 0

    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)

    print(
        f"\r{prefix}: [{bar}] {int(current)}/{int(total)} ({ratio:.1%}) | 已用: {format_time(elapsed)} | 剩余: {format_time(eta)} ",
        end="", flush=True)


def main():
    if not SRT_DIR.exists():
        print(f"错误: 找不到字幕文件夹 '{SRT_DIR}'")
        sys.exit(1)

    # 修复：寻找 .srt 文件而不是 .srt_cn_before
    srt_files = sorted(list(SRT_DIR.glob("*.srt")))
    paths.ensure_unique_safe_stems(srt_files, str(SRT_DIR))
    if not srt_files:
        print(f"错误: 在 '{SRT_DIR}' 文件夹下没有找到任何 .srt 文件")
        sys.exit(1)

    print(f"检测到 {len(srt_files)} 个任务，准备开始处理...\n")

    for idx, srt_path in enumerate(srt_files, 1):
        folder_name = paths.safe_stem(srt_path) # 获取文件名作为文件夹名
        input_audio_dir = INPUT_BASE / folder_name
        output_audio_dir = OUTPUT_BASE / folder_name

        if not input_audio_dir.exists():
            print(f"[{idx}/{len(srt_files)}] 跳过: 找不到音频子目录 -> {input_audio_dir}")
            continue

        print(f"[{idx}/{len(srt_files)}] 正在处理: {folder_name}")
        output_audio_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = output_audio_dir / "_tmp"
        tmp_dir.mkdir(exist_ok=True)

        entries = parse_srt(srt_path)
        entries.sort(key=lambda x: x["seq"])
        total = len(entries)

        stats = {"unchanged": 0, "trimmed_only": 0, "sped_up": 0, "missing": 0}
        start_time = time.time()

        max_workers = min(4, (os.cpu_count() or 4))
        tasks = [(e["seq"], e, input_audio_dir, tmp_dir) for e in entries]
        results = []

        # 初始化进度条
        show_progress(0, total, start_time, prefix=" 子任务进度")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_prepare_one, t) for t in tasks]
            for f_idx, future in enumerate(as_completed(futures), start=1):
                results.append(future.result())
                show_progress(f_idx, total, start_time, prefix=" 子任务进度")

        results.sort(key=lambda x: x["seq"])
        print("\n 正在导出音频...")

        for res in results:
            if res.get("missing"):
                stats["missing"] += 1
                continue

            tmp_path, dst_path = Path(res["tmp_path"]), output_audio_dir / f"{res['seq']:03d}.wav"
            if res["speed"] is None:
                shutil.move(str(tmp_path), str(dst_path))
                stats["unchanged" if abs(res["raw_dur"] - res["trimmed_dur"]) < 0.01 else "trimmed_only"] += 1
            else:
                speed_up_audio(str(tmp_path), str(dst_path), res["speed"])
                stats["sped_up"] += 1
                if tmp_path.exists(): tmp_path.unlink()

        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f" 完成: 加速={stats['sped_up']}, 仅裁剪={stats['trimmed_only']}, 缺失={stats['missing']}")
        print("-" * 40)


if __name__ == "__main__":
    main()
