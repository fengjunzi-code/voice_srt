from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import wave
from array import array
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import path_config as paths
from log_utils import install_timestamped_print


install_timestamped_print()

# --- 根路径配置 ---
SRT_DIR = paths.SRT_CN_AFTER_DIR
INPUT_BASE = paths.BEFORE_SPEED_DIR # 注意：改为指向原始/处理后目录
OUTPUT_BASE = paths.FINAL_MERGED_DIR
TMP_DIR_ROOT = paths.MERGE_TMP_DIR

# --- 统一音频参数 ---
TARGET_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPWIDTH = 2

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
            entries.append({"seq": seq, "start": parse_srt_timestamp(m.group(1)), "end": parse_srt_timestamp(m.group(2))})
        except: continue
    entries.sort(key=lambda x: x["seq"])
    return entries

# 子进程任务：只负责格式转换
def _convert_task(args):
    seq, src_path, tmp_dir = args
    dst_path = tmp_dir / f"{seq:03d}.wav"
    if not src_path.exists(): return seq, None
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(src_path), "-ac", "1", "-ar", str(TARGET_RATE),
            "-c:a", "pcm_s16le", str(dst_path)
        ], check=True, capture_output=True)
        return seq, str(dst_path)
    except:
        return seq, None

def write_silence_stream(wf, frames):
    """流式写入静音，避免大数组占用内存"""
    if frames <= 0: return
    silence_chunk = b'\x00' * (TARGET_CHANNELS * TARGET_SAMPWIDTH * min(frames, 16000))
    written = 0
    while written < frames:
        to_write = min(16000, frames - written)
        wf.writeframes(silence_chunk[:to_write * TARGET_CHANNELS * TARGET_SAMPWIDTH])
        written += to_write

def main():
    if not SRT_DIR.exists(): return
    srt_files = sorted(list(SRT_DIR.glob("*.srt")))
    paths.ensure_unique_safe_stems(srt_files, str(SRT_DIR))
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

    # 限制并发数
    max_workers = min(4, os.cpu_count() or 4)

    for idx, srt_file in enumerate(srt_files, 1):
        folder_name = paths.safe_stem(srt_file)
        # 自动识别音频源（优先 after_speed, 否则 before_speed）
        input_audio_dir = paths.AFTER_SPEED_DIR / folder_name
        if not input_audio_dir.exists():
            input_audio_dir = paths.BEFORE_SPEED_DIR / folder_name

        output_wav_path = OUTPUT_BASE / f"{folder_name}.wav"
        if not input_audio_dir.exists(): continue

        print(f"[{idx}/{len(srt_files)}] 正在处理: {folder_name}")
        entries = parse_srt(srt_file)
        target_frames = int(round(entries[-1]["end"] * TARGET_RATE))

        # 1. 分批格式转换（防止内存爆表）
        curr_tmp = TMP_DIR_ROOT / folder_name
        curr_tmp.mkdir(parents=True, exist_ok=True)
        converted_map = {}
        tasks = [(e["seq"], input_audio_dir / f"{e['seq']:03d}.wav", curr_tmp) for e in entries]

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 使用 map 并设置 chunksize，流式处理任务
            for seq, path_str in executor.map(_convert_task, tasks, chunksize=20):
                converted_map[seq] = path_str

        # 2. 流式拼接（核心优化）
        print("  正在线性合成...")
        total_written = 0
        with wave.open(str(output_wav_path), "wb") as out:
            out.setnchannels(TARGET_CHANNELS)
            out.setsampwidth(TARGET_SAMPWIDTH)
            out.setframerate(TARGET_RATE)

            for entry in entries:
                seq = entry["seq"]
                start_f = int(round(entry["start"] * TARGET_RATE))
                path = converted_map.get(seq)

                # 填充静音
                if start_f > total_written:
                    write_silence_stream(out, start_f - total_written)
                    total_written = start_f

                # 写入音频
                if path and os.path.exists(path):
                    with wave.open(path, "rb") as rf:
                        frames_to_read = rf.getnframes()
                        # 防止写入超过目标总时长（修剪逻辑前置）
                        if total_written + frames_to_read > target_frames:
                            frames_to_read = target_frames - total_written

                        if frames_to_read > 0:
                            out.writeframes(rf.readframes(frames_to_read))
                            total_written += frames_to_read

                # 合并完一个删一个，节省磁盘空间
                if path and os.path.exists(path):
                    try: os.unlink(path)
                    except: pass

            # 补齐尾部静音
            if total_written < target_frames:
                write_silence_stream(out, target_frames - total_written)

        shutil.rmtree(curr_tmp, ignore_errors=True)
        print(f"  完成: {folder_name}.wav")

    if TMP_DIR_ROOT.exists(): shutil.rmtree(TMP_DIR_ROOT, ignore_errors=True)

if __name__ == "__main__":
    main()
