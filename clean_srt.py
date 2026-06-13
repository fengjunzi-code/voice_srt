import os
import pysubs2
import re
import shutil

import path_config as paths

# ==========================================
# --- 核心配置区 ---
# ==========================================
# 设置处理模式:
# "CN" 只处理中文字幕，"EN" 只处理英文字幕，"CNEN" 同时处理中文和英文字幕。
MODE = "CN"
MODE = os.environ.get("CLEAN_SRT_MODE", MODE).upper()

# 清理开关：
# True 表示执行字幕清理；False 表示不清理，直接把 before 目录内容复制到 after 目录。
# 注意 Python 布尔值必须写成 False，不要写成 Flase。
# MODE = "CNEN" 时会同时处理中文和英文；CLEAN_ENABLED=False 时会同时复制两套目录。
CLEAN_ENABLED = True
_clean_enabled_env = os.environ.get("CLEAN_ENABLED")
if _clean_enabled_env is not None:
    CLEAN_ENABLED = _clean_enabled_env.strip().lower() in {"1", "true", "yes", "y", "on"}

MODE_CONFIGS = {
    "CN": {
        "input_dir": paths.SRT_CN_BEFORE_DIR,
        "output_dir": paths.SRT_CN_AFTER_DIR,
        "limit": 50,  # 中文单句最大汉字数
        "base_speed": 3.0,
    },
    "EN": {
        "input_dir": paths.SRT_EN_BEFORE_DIR,
        "output_dir": paths.SRT_EN_AFTER_DIR,
        "limit": 30,  # 英文单句最大单词数
        "base_speed": 3.0,
    },
}

ACTIVE_MODE = "CN"
INPUT_DIR = MODE_CONFIGS[ACTIVE_MODE]["input_dir"]
OUTPUT_DIR = MODE_CONFIGS[ACTIVE_MODE]["output_dir"]
LIMIT = MODE_CONFIGS[ACTIVE_MODE]["limit"]
BASE_SPEED = MODE_CONFIGS[ACTIVE_MODE]["base_speed"]

# --- 通用阈值参数 ---
FLASH_THRESHOLD = 1000  # 一闪而逝阈值 (1000ms)
TARGET_DURATION = 10000  # 碎片合并后的目标时长 (10s)
SPEED_LIMIT = 3.0  # 最大允许加速倍数 (5x)


# ==========================================

def get_text_units(text):
    """统计字数(CN)或单词数(EN)"""
    if ACTIVE_MODE == "CN":
        return len(re.sub(r'\s+', '', text))
    else:
        return len(text.split())


def is_garbage_line(text):
    """判断是否为无意义行（空白或纯标点符号）"""
    txt = text.strip()
    if not txt or not re.search(r'[\w\u4e00-\u9fff]', txt):
        return True
    return False


def get_dur(line):
    return line.end - line.start


def check_speed_too_fast(line):
    """预判语速是否超标"""
    dur_sec = max(get_dur(line) / 1000.0, 0.1)
    units = get_text_units(line.text)
    return (units / dur_sec) / BASE_SPEED > SPEED_LIMIT


def merge_logic(subs, i, target_dur=None, mode="flash"):
    """贪婪合并：将碎片或超速行并入邻居"""
    while True:
        if mode == "flash" and get_dur(subs[i]) >= target_dur: break
        if mode == "speed" and not check_speed_too_fast(subs[i]): break

        prev_dur = get_dur(subs[i - 1]) if i > 0 else -1
        next_dur = get_dur(subs[i + 1]) if i < len(subs) - 1 else -1
        if prev_dur == -1 and next_dur == -1: break

        if prev_dur >= next_dur:
            target_idx = i - 1
            if subs[target_idx].text.strip() == subs[i].text.strip() or is_garbage_line(subs[i].text):
                new_text = subs[target_idx].text.strip()
            else:
                new_text = f"{subs[target_idx].text} {subs[i].text}".strip()
            subs[target_idx].text = new_text
            subs[target_idx].end = max(subs[target_idx].end, subs[i].end)
            subs.pop(i);
            i = target_idx
        else:
            target_idx = i + 1
            if subs[i].text.strip() == subs[target_idx].text.strip() or is_garbage_line(subs[i].text):
                new_text = subs[target_idx].text.strip()
            else:
                new_text = f"{subs[i].text} {subs[target_idx].text}".strip()
            subs[i].text = new_text
            subs[i].start = min(subs[i].start, subs[target_idx].start)
            subs[i].end = max(subs[i].end, subs[target_idx].end)
            subs.pop(target_idx)
    return subs, i


def split_line_recursive(line, limit):
    """强制递归拆分：确保最终字数/词数绝不超过 limit"""
    units = get_text_units(line.text)
    if units <= limit:
        return [line]

    # 寻找最佳拆分点（中间位置的标点）
    punc_regex = r'[，。！？；：, \.!\?;:]'
    matches = list(re.finditer(punc_regex, line.text))

    split_pos = -1
    if matches:
        mid = len(line.text) // 2
        best_match = min(matches, key=lambda m: abs(m.start() - mid))
        split_pos = best_match.end()

    # 无标点或标点位置极端则中拆
    if split_pos == -1 or split_pos < (len(line.text) * 0.2) or split_pos > (len(line.text) * 0.8):
        split_pos = len(line.text) // 2

    part1_text = line.text[:split_pos].strip()
    part2_text = line.text[split_pos:].strip()

    # 比例时间分配
    u1, u2 = get_text_units(part1_text), get_text_units(part2_text)
    total_u = u1 + u2
    ratio = u1 / total_u if total_u > 0 else 0.5

    total_dur = get_dur(line)
    mid_point = line.start + int(total_dur * ratio)

    l1 = line.copy();
    l1.text = part1_text;
    l1.end = mid_point
    l2 = line.copy();
    l2.text = part2_text;
    l2.start = mid_point

    return split_line_recursive(l1, limit) + split_line_recursive(l2, limit)


def process_srt(srt_path, save_path):
    subs = pysubs2.load(str(srt_path))
    if not subs: return

    # --- 1. 垃圾清理与完全去重 ---
    i = 0
    while i < len(subs):
        if is_garbage_line(subs[i].text):
            if i > 0:
                subs[i - 1].end = max(subs[i - 1].end, subs[i].end); subs.pop(i)
            elif i < len(subs) - 1:
                subs[i + 1].start = min(subs[i + 1].start, subs[i].start); subs.pop(i)
            else:
                subs.pop(i)
            continue
        if i < len(subs) - 1 and subs[i].text.strip() == subs[i + 1].text.strip():
            subs[i].end = subs[i + 1].end;
            subs.pop(i + 1)
            continue
        i += 1

    # --- 2. 碎片与语速合并 ---
    i = 0
    while i < len(subs):
        if get_dur(subs[i]) < FLASH_THRESHOLD:
            subs, i = merge_logic(subs, i, target_dur=TARGET_DURATION, mode="flash")
        elif check_speed_too_fast(subs[i]):
            subs, i = merge_logic(subs, i, mode="speed")
        else:
            i += 1

    # --- 3. 强制拆分长句 ---
    final_subs = pysubs2.SSAFile()
    for line in subs:
        parts = split_line_recursive(line, LIMIT)
        for p in parts: final_subs.append(p)

    final_subs.save(str(save_path), format_="srt")


def get_selected_modes() -> list[str]:
    selected_mode = MODE.upper()
    if selected_mode == "CNEN":
        return ["CN", "EN"]
    if selected_mode in MODE_CONFIGS:
        return [selected_mode]
    raise ValueError('MODE 只能设置为 "CN"、"EN" 或 "CNEN"')


def configure_mode(mode: str) -> None:
    global ACTIVE_MODE, INPUT_DIR, OUTPUT_DIR, LIMIT, BASE_SPEED

    config = MODE_CONFIGS[mode]
    ACTIVE_MODE = mode
    INPUT_DIR = config["input_dir"]
    OUTPUT_DIR = config["output_dir"]
    LIMIT = config["limit"]
    BASE_SPEED = config["base_speed"]


def copy_before_to_after(input_dir, output_dir) -> int:
    output_dir.mkdir(exist_ok=True, parents=True)
    copied_count = 0

    for src_path in input_dir.rglob("*"):
        relative_path = src_path.relative_to(input_dir)
        if src_path.is_file() and src_path.suffix.lower() == ".srt":
            relative_path = relative_path.with_name(f"{paths.safe_stem(src_path)}.srt")
        dst_path = output_dir / relative_path
        if src_path.is_dir():
            dst_path.mkdir(exist_ok=True, parents=True)
            continue

        dst_path.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(src_path, dst_path)
        copied_count += 1

    return copied_count


def run_mode(mode: str) -> None:
    configure_mode(mode)

    if not INPUT_DIR.exists():
        print(f"❌ 错误: 找不到输入文件夹 {INPUT_DIR}")
        return

    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

    if not CLEAN_ENABLED:
        copied_count = copy_before_to_after(INPUT_DIR, OUTPUT_DIR)
        print(f"📋 复制完成 | 模式: {ACTIVE_MODE} | 文件数: {copied_count}")
        print(f"📂 输入路径: {INPUT_DIR} -> 输出路径: {OUTPUT_DIR}")
        return

    srt_files = list(INPUT_DIR.glob("*.srt"))
    paths.ensure_unique_safe_stems(srt_files, str(INPUT_DIR))

    print(f"🚀 优化启动 | 模式: {ACTIVE_MODE}")
    print(f"📂 输入路径: {INPUT_DIR} -> 输出路径: {OUTPUT_DIR}")

    for srt_path in srt_files:
        save_path = OUTPUT_DIR / f"{paths.safe_stem(srt_path)}.srt"
        process_srt(srt_path, save_path)
        print(f"✅ 处理完成: {save_path.name}")


def main():
    try:
        selected_modes = get_selected_modes()
    except ValueError as e:
        print(f"❌ 配置错误: {e}")
        return

    print(f"当前设置: MODE={MODE.upper()}, CLEAN_ENABLED={CLEAN_ENABLED}")
    for mode in selected_modes:
        run_mode(mode)


if __name__ == "__main__":
    main()
