import os
from collections.abc import Iterable
from pathlib import Path

try:
    import private_config
except ImportError:
    private_config = None


def _private_value(name: str, default=None):
    return getattr(private_config, name, default) if private_config else default


def safe_stem(path: Path) -> str:
    """Return a Windows-safe stem for derived output files/folders."""
    stem = path.stem.strip(" .")
    if not stem:
        raise ValueError(f"Filename becomes empty after trimming spaces/dots: {path.name}")
    return stem


def ensure_unique_safe_stems(file_paths: Iterable[Path], context: str = "files") -> None:
    """Raise if different input files would produce the same derived stem."""
    by_stem: dict[str, list[Path]] = {}
    for file_path in file_paths:
        by_stem.setdefault(safe_stem(file_path), []).append(file_path)

    collisions = {stem: paths for stem, paths in by_stem.items() if len(paths) > 1}
    if not collisions:
        return

    details = "; ".join(
        f"{stem}: " + ", ".join(path.name for path in paths)
        for stem, paths in collisions.items()
    )
    raise ValueError(f"Normalized filename collision in {context}: {details}")


DEFAULT_ROOT = Path(__file__).resolve().parent

# Environment variables override private_config.py. Without private_config.py,
# the project directory is used so the public repo still runs in a basic setup.
VOICE_SRT_ROOT = Path(
    os.environ.get("VOICE_SRT_ROOT") or _private_value("VOICE_SRT_ROOT", DEFAULT_ROOT)
)

BATCH_VOICE_SRT_ROOTS = [
    Path(root) for root in _private_value("BATCH_VOICE_SRT_ROOTS", [VOICE_SRT_ROOT])
]

# Subtitle directories
SRT_CN_AFTER_DIR = VOICE_SRT_ROOT / "srt_cn" / "srt_cn_after"
SRT_CN_BEFORE_DIR = VOICE_SRT_ROOT / "srt_cn" / "srt_cn_before"
SRT_EN_BEFORE_DIR = VOICE_SRT_ROOT / "srt_en" / "srt_en_before"
SRT_EN_AFTER_DIR = VOICE_SRT_ROOT / "srt_en" / "srt_en_after"

# Video directories
VIDEO_EN_DIR = VOICE_SRT_ROOT / "video_en"
VIDEO_CN_DIR = VOICE_SRT_ROOT / "video_cn"

# Audio intermediate/output directories
BEFORE_SPEED_DIR = VOICE_SRT_ROOT / "before_speed"
AFTER_SPEED_DIR = VOICE_SRT_ROOT / "after_speed"
FINAL_MERGED_DIR = VOICE_SRT_ROOT / "final_merged"
MERGE_TMP_DIR = VOICE_SRT_ROOT / "_merge_tmp"

# TTS prompt voice settings
TTS_PROMPT_AUDIO = os.environ.get("TTS_PROMPT_AUDIO") or _private_value("TTS_PROMPT_AUDIO", "")
TTS_PROMPT_AUDIO_TEXT = os.environ.get("TTS_PROMPT_AUDIO_TEXT") or _private_value("TTS_PROMPT_AUDIO_TEXT", "")
