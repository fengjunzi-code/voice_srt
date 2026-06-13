import os
import time
import pysubs2
from pathlib import Path
from openai import OpenAI
import random

import path_config as paths

# ==========================================
# --- 核心配置区 ---
# ==========================================
# 模式设置："CN" 为仅中文，"BOTH" 为中英双语
SUBTITLE_MODE = "CN"

# 路径配置 (已修改为你指定的绝对路径，使用 r 前缀防转义)
TRANSLATE_SRT_STAGE = os.environ.get("TRANSLATE_SRT_STAGE", "before").lower()
SRT_IN_DIR = paths.SRT_EN_AFTER_DIR if TRANSLATE_SRT_STAGE == "after" else paths.SRT_EN_BEFORE_DIR
SRT_OUT_DIR = paths.SRT_CN_BEFORE_DIR

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or paths._private_value("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

# 容错与频率配置
BATCH_SIZE = 10
MAX_RETRIES = 5
RPM_DELAY = 0.2
RETRY_DELAY = 5
# ==========================================

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)


def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def show_progress(done: int, total: int, start_time: float, prefix=""):
    width = 30
    ratio = done / total if total > 0 else 1
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    elapsed = time.time() - start_time
    eta = (elapsed / done * (total - done)) if done > 0 else 0
    print(f"\r{prefix}: [{bar}] {done}/{total} ({ratio:.1%}) | 剩余: {format_time(eta)} ", end="", flush=True)


def translate_with_retry(texts):
    expected_count = len(texts)
    # 使用 start=1，让编号从 [1] 开始
    prompt_content = "\n".join([f"[{i}] {t}" for i, t in enumerate(texts, start=1)])

    # 更新提示词中的示例和逻辑说明
    system_msg = (
        "你是一个专业的影视翻译专家。请将英文视频字幕翻译为中文。\n"
        f"要求：1. 必须返回且仅返回正好 {expected_count} 行翻译结果。\n"
        "2. 风格自然。\n"
        "3. 严禁省略行或合并行：每一行英文必须对应一行中文。\n"
        "4. 保持原有编号格式 [i]，每行必须以对应的 [编号] 开头，例如：[1] 翻译内容。\n"
        "5. 只输出翻译结果，不解释。"
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt_content},
                ],
                timeout=60
            )

            raw_result = response.choices[0].message.content.strip()
            lines = raw_result.split('\n')

            results = []
            for line in lines:
                if ']' in line:
                    # 提取 ] 之后的内容
                    results.append(line.split(']', 1)[-1].strip())

            if len(results) != expected_count:
                raise ValueError(f"返回行数不匹配: 预期 {expected_count}, 实际 {len(results)}")

            return results

        except Exception as e:
            wait_time = RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
            print(f"\n⚠️ 警告: 第 {attempt + 1} 次尝试失败 ({e})。{wait_time:.1f}s 后重试...")
            time.sleep(wait_time)

    return texts


def main():
    if not DEEPSEEK_API_KEY:
        print("错误: 请在 private_config.py 或环境变量 DEEPSEEK_API_KEY 中配置 DeepSeek API Key")
        return

    SRT_OUT_DIR.mkdir(exist_ok=True, parents=True)
    # 修复点 1：读取输入文件夹的后缀改为 *.srt
    srt_files = sorted(list(SRT_IN_DIR.glob("*.srt")))

    paths.ensure_unique_safe_stems(srt_files, str(SRT_IN_DIR))
    if not srt_files:
        print(f"❌ 错误: 未在 {SRT_IN_DIR} 找到 .srt 文件")
        return

    print(f"🚀 当前模式: {'【仅中文】' if SUBTITLE_MODE == 'CN' else '【中英双语】'}")
    print(f"🚀 准备处理 {len(srt_files)} 个任务...")

    for srt_path in srt_files:
        target_path = SRT_OUT_DIR / f"{paths.safe_stem(srt_path)}.srt"
        if target_path.exists():
            print(f"⏩ 跳过已存在文件: {srt_path.name}")
            continue

        # 加载字幕并显示总句数
        subs = pysubs2.load(str(srt_path))
        total_lines = len(subs)
        print(f"\n🎬 开始处理: {srt_path.name} (共 {total_lines} 句)")

        start_time = time.time()
        original_texts = [line.text for line in subs]

        for i in range(0, total_lines, BATCH_SIZE):
            batch = original_texts[i: i + BATCH_SIZE]
            translated_batch = translate_with_retry(batch)

            for j, translated_text in enumerate(translated_batch):
                line_index = i + j
                if line_index < total_lines:
                    if SUBTITLE_MODE == "BOTH":
                        # 中英双语
                        subs[line_index].text = f"{translated_text}\\N{original_texts[line_index]}"
                    else:
                        # 仅中文
                        subs[line_index].text = translated_text

            # 修复点 2：保存格式必须是标准字幕格式 "srt"，不能是 "srt_cn_before"
            subs.save(str(target_path) + ".tmp", format_="srt")

            show_progress(min(i + BATCH_SIZE, total_lines), total_lines, start_time, prefix="  翻译进度")
            time.sleep(RPM_DELAY)

        # 替换正式文件
        if os.path.exists(str(target_path) + ".tmp"):
            os.replace(str(target_path) + ".tmp", str(target_path))

        print(f"\n✅ 处理完成并保存: {target_path.name}")

    print("\n🎉 全部任务已圆满完成！")


if __name__ == "__main__":
    main()
