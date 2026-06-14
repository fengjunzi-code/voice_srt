from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import path_config as paths
from log_utils import install_timestamped_print


install_timestamped_print()


SCRIPT_DIR = Path(__file__).resolve().parent

# 固定前置任务：不受 DEFAULT_TASKS 控制，每次运行流水线都会先执行。
ALWAYS_ON_TASKS = [
    "convert_video",
]

# 内置任务顺序：用户可以跳过某些任务，但实际执行永远按这里的顺序。
TASK_ORDER = [
    "convert_video",
    "transcribe_batch",
    "clean_srt_en",
    "translate_batch",
    "clean_srt_cn",
    "batch_tts",
    "speed_audio",
    "merge_audio",
    "replace_audio",
]

TASK_SCRIPTS = {
    "convert_video": SCRIPT_DIR / "convert_video.py",
    "transcribe_batch": SCRIPT_DIR / "transcribe_batch.py",
    "clean_srt_en": SCRIPT_DIR / "clean_srt.py",
    "translate_batch": SCRIPT_DIR / "translate_batch.py",
    "clean_srt_cn": SCRIPT_DIR / "clean_srt.py",
    "batch_tts": SCRIPT_DIR / "batch_tts.py",
    "speed_audio": SCRIPT_DIR / "speed_audio.py",
    "merge_audio": SCRIPT_DIR / "merge_audio.py",
    "replace_audio": SCRIPT_DIR / "replace_audio.py",
}

TASK_ENV_OVERRIDES = {
    "clean_srt_en": {"CLEAN_SRT_MODE": "EN", "CLEAN_ENABLED": "True"},
    "clean_srt_cn": {"CLEAN_SRT_MODE": "CN", "CLEAN_ENABLED": "True"},
}

# 不传命令行参数时使用这里的默认任务开关。
# Python 布尔值必须写成 True/False，不要写成 true/false 或 flase。
DEFAULT_TASKS = {
    "transcribe_batch": True,  # 视频转英文字幕：video_en -> srt_en/srt_en_before
    "clean_srt_en": True,      # 清理或复制英文字幕：srt_en/srt_en_before -> srt_en/srt_en_after
    "translate_batch": True,   # 英文字幕翻译成中文字幕：srt_en/srt_en_after -> srt_cn/srt_cn_before
    "clean_srt_cn": True,      # 清理或复制中文字幕：srt_cn/srt_cn_before -> srt_cn/srt_cn_after
    "batch_tts": True,          # 批量生成配音片段：srt_cn/srt_cn_after -> before_speed
    "speed_audio": True,        # 调整配音片段语速：before_speed -> after_speed
    "merge_audio": True,       # 合并配音片段：after_speed 或 before_speed -> final_merged
    "replace_audio": True,     # 替换视频音轨：video_en + final_merged -> video_cn
}
DEFAULT_ROOTS = paths.BATCH_VOICE_SRT_ROOTS


def split_names(values: list[str] | None) -> list[str]:
    if not values:
        return []

    names = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                names.append(item)
    return names


def normalize_tasks(values: list[str] | None) -> list[str]:
    requested = split_names(values)
    if not requested:
        return [task for task in TASK_ORDER if DEFAULT_TASKS.get(task, False)]

    requested_lower = [name.lower() for name in requested]

    if "all" in requested_lower:
        return TASK_ORDER[:]

    unknown = sorted(set(requested_lower) - set(TASK_ORDER))
    if unknown:
        valid = ", ".join(TASK_ORDER)
        raise ValueError(f"未知任务: {', '.join(unknown)}。可选任务: {valid}")

    requested_set = set(requested_lower)
    return [task for task in TASK_ORDER if task in requested_set]


def prepend_always_on_tasks(tasks: list[str]) -> list[str]:
    ordered_tasks = []
    seen = set()

    for task in ALWAYS_ON_TASKS + tasks:
        if task not in seen:
            ordered_tasks.append(task)
            seen.add(task)

    return ordered_tasks


def normalize_roots(values: list[str] | None) -> list[Path]:
    raw_roots = values or [str(root) for root in DEFAULT_ROOTS]
    roots = []
    for value in raw_roots:
        root = Path(value).expanduser()
        roots.append(root)
    return roots


def validate_task_scripts(tasks: list[str]) -> None:
    missing = [str(TASK_SCRIPTS[task]) for task in tasks if not TASK_SCRIPTS[task].exists()]
    if missing:
        raise FileNotFoundError("找不到任务脚本: " + ", ".join(missing))


def get_task_env_overrides(task: str, selected_tasks: set[str]) -> dict[str, str]:
    overrides = dict(TASK_ENV_OVERRIDES.get(task, {}))
    if task == "translate_batch" and "clean_srt_en" in selected_tasks:
        overrides["TRANSLATE_SRT_STAGE"] = "after"
    return overrides


def run_task(root: Path, task: str, python_exe: str, dry_run: bool, selected_tasks: set[str]) -> None:
    script_path = TASK_SCRIPTS[task]
    env = os.environ.copy()
    env["VOICE_SRT_ROOT"] = str(root)
    task_env_overrides = get_task_env_overrides(task, selected_tasks)
    env.update(task_env_overrides)

    cmd = [python_exe, str(script_path)]
    prefix = f"[{root.name or root}] {task}"
    print(f"{prefix} -> 开始")

    if dry_run:
        if task_env_overrides:
            env_text = ", ".join(f"{key}={value}" for key, value in task_env_overrides.items())
            print(f"{prefix} -> env: {env_text}")
        print(f"{prefix} -> dry-run: {' '.join(cmd)}")
        return

    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR), env=env)
    if result.returncode != 0:
        raise RuntimeError(f"{prefix} 执行失败，退出码: {result.returncode}")

    print(f"{prefix} -> 完成")


def run_pipeline_for_root(
    root: Path,
    tasks: list[str],
    python_exe: str,
    dry_run: bool,
    continue_on_error: bool,
) -> tuple[Path, bool]:
    print(f"\n=== 根目录开始: {root} ===")
    ok = True
    selected_tasks = set(tasks)

    for task in tasks:
        try:
            run_task(root, task, python_exe, dry_run, selected_tasks)
        except Exception as exc:
            print(f"[{root.name or root}] {task} -> 失败: {exc}")
            ok = False
            if not continue_on_error:
                return root, False

    print(f"=== 根目录完成: {root} ===")
    return root, ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按内置顺序组合执行 voice_srt 处理脚本，并支持多个 VOICE_SRT_ROOT 串行批量处理。",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        help=(
            "要执行的任务，支持空格或逗号分隔；实际执行会自动按内置顺序排序。\n"
            "示例: --tasks batch_tts speed_audio\n"
            "示例: --tasks batch_tts,speed_audio\n"
            "示例: --tasks all"
        ),
    )
    parser.add_argument(
        "--roots",
        nargs="*",
        help=(
            "要处理的 VOICE_SRT_ROOT 列表；不同根目录之间按顺序串行执行。\n"
            r"示例: --roots path\to\voice_srt1 path\to\voice_srt2"
        ),
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="用于运行任务脚本的 Python 解释器；默认使用当前解释器。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的任务，不真正运行。",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="某个任务失败后继续执行同一根目录后续任务；默认失败后停止该根目录。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        tasks = normalize_tasks(args.tasks)
        tasks = prepend_always_on_tasks(tasks)
        roots = normalize_roots(args.roots)
        validate_task_scripts(tasks)
    except Exception as exc:
        print(f"配置错误: {exc}")
        return 2

    if not tasks:
        print("配置错误: 没有可执行任务")
        return 2

    print("任务顺序: " + " -> ".join(tasks))
    print("根目录数量: " + str(len(roots)))
    print("根目录执行方式: 串行")

    results: list[tuple[Path, bool]] = []
    for root in roots:
        result = run_pipeline_for_root(
            root,
            tasks,
            args.python,
            args.dry_run,
            args.continue_on_error,
        )
        results.append(result)

    failed = [root for root, ok in results if not ok]
    if failed:
        print("\n失败根目录:")
        for root in failed:
            print(f"- {root}")
        return 1

    print("\n全部处理完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
