import os
import sys
import time
from pathlib import Path

import path_config as paths


# =================================================================
# 1. 深度环境补丁：解决 Windows 找不到 cublas64_12.dll 等问题
# =================================================================
def patch_nvidia_dlls():
    """针对 Python 3.8+ 在 Windows 上加载 CUDA DLL 的强制修复"""
    executable_path = Path(sys.executable)
    # 定位 site-packages 路径 (通常在 .venv/Lib/site-packages)
    site_pkg = executable_path.parent.parent / "Lib" / "site-packages"

    # 如果路径不对，尝试备选路径
    if not site_pkg.exists():
        site_pkg = executable_path.parent / "Lib" / "site-packages"

    # 需要扫描的 NVIDIA 二进制文件夹
    nvidia_dirs = [
        site_pkg / "nvidia" / "cublas" / "bin",
        site_pkg / "nvidia" / "cudnn" / "bin",
        site_pkg / "nvidia" / "cuda_nvrtc" / "bin",
        site_pkg / "nvidia" / "cuda_runtime" / "bin",
    ]

    print("--- DLL 环境检查 ---")
    found_any = False
    for d in nvidia_dirs:
        if d.exists():
            # 关键：os.add_dll_directory 是 Python 3.8+ 加载 DLL 的唯一有效方式
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
            print(f"✅ 已加载库路径: {d}")
            found_any = True

    if not found_any:
        print("❌ 警告：未在虚拟环境中找到 nvidia-*-cu12 库，请确保已运行 pip install nvidia-cublas-cu12")
    print("-------------------\n")


# 启动补丁
patch_nvidia_dlls()

# 确保补丁后再加载 faster_whisper
try:
    from faster_whisper import WhisperModel
    import pysubs2
except ImportError as e:
    print(f"❌ 导入失败，请检查是否安装了 faster-whisper 和 pysubs2: {e}")
    sys.exit(1)

# =================================================================
# 2. 基础路径配置 (已更新为指定的绝对路径)
# =================================================================
VIDEO_DIR = paths.VIDEO_EN_DIR
SRT_OUT_DIR = paths.SRT_EN_BEFORE_DIR

# 你手动下载的模型存放路径
MODEL_PATH_VALUE = os.environ.get("WHISPER_MODEL_PATH") or paths._private_value("WHISPER_MODEL_PATH", "")
MODEL_PATH = Path(MODEL_PATH_VALUE) if MODEL_PATH_VALUE else None


# =================================================================
# 3. 辅助函数
# =================================================================
def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def show_progress(current: float, total: float, start_time: float, prefix=""):
    width = 30
    elapsed = time.time() - start_time

    # 修复未满 100% 的 Bug：强制拦截完成状态
    if current >= total:
        ratio = 1.0
        eta = 0.0
    else:
        ratio = current / total if total > 0 else 0
        eta = (elapsed / ratio - elapsed) if ratio > 0.05 else 0

    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)

    # 末尾增加空格，防止前一次打印的内容残留覆盖不全
    print(f"\r{prefix}: [{bar}] {ratio:.1%} | 已用: {format_time(elapsed)} | 剩余: {format_time(eta)}     ", end="",
          flush=True)


# =================================================================
# 4. 主程序
# =================================================================
def main():
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    SRT_OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not MODEL_PATH or not MODEL_PATH.exists():
        print(f"❌ 错误：找不到模型目录: {MODEL_PATH}")
        return

    print(f"🚀 正在加载本地模型 (Large-v3)...")
    try:
        # RTX 4070 Ti 完美支持 cuda + float16
        model = WhisperModel(str(MODEL_PATH), device="cuda", compute_type="float16")
    except Exception as e:
        print(
            f"\n❌ 模型加载失败！\n可能的提示：如果你依然看到 cublas64_12.dll 错误，请尝试手动将该文件从虚拟环境 bin 目录复制到脚本根目录。\n详情: {e}")
        return

    video_files = [f for f in VIDEO_DIR.glob("*") if f.suffix.lower() in [".mp4", ".mkv", ".avi", ".mov"]]
    paths.ensure_unique_safe_stems(video_files, str(VIDEO_DIR))
    if not video_files:
        print(f"⚠️ 提示：请将要处理的视频放入 {VIDEO_DIR} 文件夹")
        return

    print(f"🎯 发现 {len(video_files)} 个任务，开始转录...\n")

    for idx, v_path in enumerate(video_files, 1):
        # 修复点：转录出来的是英文原始字幕，后缀改为标准的 .srt
        target_srt = SRT_OUT_DIR / f"{paths.safe_stem(v_path)}.srt"
        if target_srt.exists():
            print(f"⏩ [{idx}/{len(video_files)}] 跳过已存在: {v_path.name}")
            continue

        print(f"[{idx}/{len(video_files)}] 正在转录: {v_path.name}")
        start_t = time.time()

        try:
            # 执行转录，指定 language="en" 速度更快
            segments, info = model.transcribe(str(v_path), beam_size=5, language="en")

            subs = pysubs2.SSAFile()
            for segment in segments:
                event = pysubs2.SSAEvent(
                    start=int(segment.start * 1000),
                    end=int(segment.end * 1000),
                    text=segment.text.strip()
                )
                subs.append(event)
                show_progress(segment.end, info.duration, start_t, prefix="  进度")

            # 强制刷新一次 100% 进度条
            show_progress(info.duration, info.duration, start_t, prefix="  进度")

            subs.save(str(target_srt))
            print(f"\n✅ 已保存: {target_srt.name}\n" + "-" * 40)

        except Exception as e:
            print(f"\n❌ 处理出错 {v_path.name}: {e}")

    print("\n🎉 全部视频转录完成！")


if __name__ == "__main__":
    main()
