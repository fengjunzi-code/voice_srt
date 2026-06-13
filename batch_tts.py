import requests
import re
import atexit
import os
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import path_config as paths

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==========================================
# --- 基础路径配置 ---
# ==========================================
SRT_INPUT_DIR = paths.SRT_CN_AFTER_DIR
BEFORE_SPEED_DIR = paths.BEFORE_SPEED_DIR
API_HOST = os.environ.get("GPT_SOVITS_API_HOST") or paths._private_value("GPT_SOVITS_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("GPT_SOVITS_API_PORT") or paths._private_value("GPT_SOVITS_API_PORT", 23451))
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
API_URL = f"{API_BASE_URL}/tts"
AUTO_START_TTS_API = str(
    os.environ.get("AUTO_START_TTS_API") or paths._private_value("AUTO_START_TTS_API", True)
).lower() not in {"0", "false", "no", "off"}
TTS_API_START_TIMEOUT = int(
    os.environ.get("TTS_API_START_TIMEOUT") or paths._private_value("TTS_API_START_TIMEOUT", 180)
)
MAX_WORKERS = 4

# ==========================================
# --- 严格遵循迪卢克参数设置 ---
# ==========================================
TTS_CONFIG = {
    "prompt_audio": paths.TTS_PROMPT_AUDIO,
    "prompt_audio_text": paths.TTS_PROMPT_AUDIO_TEXT,
    "prompt_audio_lang": "zh",
    "text_lang": "zh",
    "gpt_model_path": str(os.environ.get("GPT_MODEL_PATH") or paths._private_value("GPT_MODEL_PATH", "")),
    "sovits_model_path": str(os.environ.get("SOVITS_MODEL_PATH") or paths._private_value("SOVITS_MODEL_PATH", "")),
    "top_k": 15,
    "top_p": 1.0,
    "temperature": 0.8,
    "text_split_method": "cut5",
    "batch_size": 20,
    "batch_threshold": 0.75,
    "split_bucket": True,
    "speed_factor": 1.0,
    "fragment_interval": 0.3,
    "seed": -1,
    "media_type": "wav",
    "streaming_mode": False,
    "parallel_infer": True,
    "repetition_penalty": 1.35,
    "sample_steps": 32,
    "super_sampling": False
}

_started_tts_process: subprocess.Popen | None = None
_started_tts_log_file = None


# ==========================================
# --- 辅助函数 ---
# ==========================================
def format_time(seconds: float) -> str:
    """将秒数格式化为时:分:秒"""
    if seconds < 0: return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def show_progress(current: float, total: float, start_time: float, prefix=""):
    """显示进度条，包含耗时、剩余时间与当前数量"""
    width = 30
    elapsed = time.time() - start_time

    # 强制拦截完成状态，解决 99% 的问题
    if current >= total:
        ratio = 1.0
        eta = 0.0
    else:
        ratio = current / total if total > 0 else 0
        eta = (elapsed / ratio - elapsed) if ratio > 0.05 else 0

    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)

    # 进度条格式：[███░░░] 2/83 (2.2%) | 已用: 00:10 | 剩余: 00:00
    print(
        f"\r{prefix}: [{bar}] {int(current)}/{int(total)} ({ratio:.1%}) | 已用: {format_time(elapsed)} | 剩余: {format_time(eta)}     ",
        end="", flush=True)


def is_tts_api_ready() -> bool:
    try:
        response = requests.get(f"{API_BASE_URL}/openapi.json", timeout=2)
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    body = response.text
    return "StarBox API" in body or '"/tts"' in body


def wait_for_tts_api(timeout_seconds: int) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if is_tts_api_ready():
            return True
        time.sleep(2)
    return False


def stop_started_tts_api() -> None:
    global _started_tts_process, _started_tts_log_file

    process = _started_tts_process
    _started_tts_process = None

    if process and process.poll() is None:
        print("Stopping GPT-SoVITS API started by this run...")
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    if _started_tts_log_file:
        _started_tts_log_file.close()
        _started_tts_log_file = None


def ensure_tts_api_running() -> None:
    global _started_tts_process, _started_tts_log_file

    if is_tts_api_ready():
        print(f"TTS API already running: {API_BASE_URL}")
        return

    if not AUTO_START_TTS_API:
        raise RuntimeError(f"TTS API is not running: {API_BASE_URL}")

    root_value = os.environ.get("GPT_SOVITS_ROOT") or paths._private_value("GPT_SOVITS_ROOT", "")
    if not root_value:
        raise RuntimeError("GPT_SOVITS_ROOT is not configured in private_config.py or the environment")

    gpt_sovits_root = Path(root_value)
    python_exe = Path(
        os.environ.get("GPT_SOVITS_PYTHON")
        or paths._private_value("GPT_SOVITS_PYTHON", gpt_sovits_root / "runtime" / "python.exe")
    )
    api_script = Path(
        os.environ.get("GPT_SOVITS_API_SCRIPT")
        or paths._private_value("GPT_SOVITS_API_SCRIPT", gpt_sovits_root / "starbox-gpt-sovits-api-v3.py")
    )

    if not python_exe.exists():
        raise FileNotFoundError(f"GPT-SoVITS Python not found: {python_exe}")
    if not api_script.exists():
        raise FileNotFoundError(f"GPT-SoVITS API script not found: {api_script}")

    log_path = Path(
        os.environ.get("GPT_SOVITS_API_LOG")
        or paths._private_value("GPT_SOVITS_API_LOG", Path(__file__).with_name("gpt_sovits_api.log"))
    )
    _started_tts_log_file = log_path.open("a", encoding="utf-8", errors="replace")

    cmd = [str(python_exe), str(api_script), "-p", str(API_PORT)]
    print(f"Starting GPT-SoVITS API: {API_BASE_URL}")
    _started_tts_process = subprocess.Popen(
        cmd,
        cwd=str(gpt_sovits_root),
        stdout=_started_tts_log_file,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    atexit.register(stop_started_tts_api)

    if not wait_for_tts_api(TTS_API_START_TIMEOUT):
        stop_started_tts_api()
        raise RuntimeError(
            f"GPT-SoVITS API did not become ready within {TTS_API_START_TIMEOUT}s. "
            f"Check log: {log_path}"
        )

    print(f"GPT-SoVITS API is ready: {API_BASE_URL}")


def parse_srt(srt_path: Path) -> list[dict]:
    """解析 SRT 文件，提取序号和文本"""
    try:
        text = srt_path.read_text(encoding="utf-8-sig")
    except:
        text = srt_path.read_text(encoding="gbk", errors="ignore")

    blocks = re.split(r'\n\s*\n', text.strip())
    entries = []

    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) >= 3:
            try:
                seq = int(lines[0])
                content = " ".join(lines[2:])
                entries.append({"seq": seq, "text": content})
            except:
                continue
    return entries


def process_line(entry: dict, target_dir: Path) -> tuple[bool, int, str]:
    """处理单行文本，请求 API 并存入对应目录"""
    seq = entry["seq"]
    text = entry["text"]
    save_path = target_dir / f"{seq:03d}.wav"

    if save_path.exists() and save_path.stat().st_size > 44:
        return True, seq, "已存在"

    payload = {**TTS_CONFIG, "text": text}
    try:
        response = requests.post(API_URL, json=payload, timeout=120)
        if response.status_code != 200:
            body = response.text[:200].replace("\r", " ").replace("\n", " ")
            return False, seq, f"HTTP {response.status_code}: {body}"

        if not response.content:
            return False, seq, "接口返回空内容"

        if TTS_CONFIG.get("media_type") == "wav" and not response.content.startswith(b"RIFF"):
            preview = response.content[:120].decode("utf-8", errors="replace")
            preview = preview.replace("\r", " ").replace("\n", " ")
            return False, seq, f"返回内容不是 WAV: {preview}"

        target_dir.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(response.content)
        return True, seq, "生成成功"
    except Exception as exc:
        return False, seq, f"{type(exc).__name__}: {exc}"


# ==========================================
# --- 主程序 ---
# ==========================================
def main():
    # 1. 确保输出根目录存在
    BEFORE_SPEED_DIR.mkdir(parents=True, exist_ok=True)
    ensure_tts_api_running()

    # 2. 获取所有的 .srt 文件
    srt_files = sorted(list(SRT_INPUT_DIR.glob("*.srt")))
    paths.ensure_unique_safe_stems(srt_files, str(SRT_INPUT_DIR))
    if not srt_files:
        print(f"❌ 错误: 在 {SRT_INPUT_DIR} 下没找到任何 .srt 文件")
        return

    print(f"🎯 发现共 {len(srt_files)} 个字幕文件，准备开始处理...\n")

    any_failure = False

    # 3. 遍历处理每个文件
    for index, srt_path in enumerate(srt_files, 1):
        srt_name = paths.safe_stem(srt_path)
        current_save_dir = BEFORE_SPEED_DIR / srt_name
        current_save_dir.mkdir(parents=True, exist_ok=True)

        entries = parse_srt(srt_path)
        total_lines = len(entries)

        print(f"[{index}/{len(srt_files)}] 正在处理: {srt_name}")
        if srt_name != srt_path.stem:
            print(f"  提示: 已将文件名 '{srt_path.stem}' 归一化为 '{srt_name}'")

        srt_start_time = time.time()
        done_count = 0
        failures: list[tuple[int, str]] = []

        # 初始化进度条 (0%)
        show_progress(0, total_lines, srt_start_time, prefix="  当前进度")

        # 多线程并发请求 TTS
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_line, e, current_save_dir): e for e in entries}
            for future in as_completed(futures):
                entry = futures[future]
                done_count += 1
                try:
                    ok, seq, message = future.result()
                except Exception as exc:
                    ok = False
                    seq = entry.get("seq", -1)
                    message = f"{type(exc).__name__}: {exc}"

                if not ok:
                    failures.append((seq, message))

                # 实时刷新进度条
                show_progress(done_count, total_lines, srt_start_time, prefix="  当前进度")

        # 换行，防止下一次循环的 print 覆盖当前满的进度条
        print()
        if failures:
            any_failure = True
            failures.sort(key=lambda item: item[0])
            print(f"  失败: {len(failures)}/{total_lines}")
            for seq, message in failures[:10]:
                print(f"    - {seq:03d}: {message}")
            if len(failures) > 10:
                print(f"    ... 还有 {len(failures) - 10} 条失败未显示")

    if any_failure:
        print(f"\n存在生成失败的音频，请根据上面的失败原因处理后重新运行。输出文件夹: {BEFORE_SPEED_DIR}")
        sys.exit(1)

    print(f"\n🎉 所有任务处理完成！请查看文件夹: {BEFORE_SPEED_DIR}")


if __name__ == "__main__":
    main()
