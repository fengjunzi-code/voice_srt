from pathlib import Path

# Copy this file to private_config.py and fill in your own local values.
# private_config.py is ignored by Git.

VOICE_SRT_ROOT = Path(r"path\to\one\course")

BATCH_VOICE_SRT_ROOTS = [
    VOICE_SRT_ROOT,
]

DEEPSEEK_API_KEY = ""

WHISPER_MODEL_PATH = Path(r"path\to\faster-whisper-large-v3")

GPT_SOVITS_ROOT = Path(r"path\to\GPT-SoVITS")
GPT_SOVITS_API_PORT = 23451
AUTO_START_TTS_API = True

TTS_PROMPT_AUDIO = r"path\to\prompt.wav"
TTS_PROMPT_AUDIO_TEXT = ""

GPT_MODEL_PATH = Path(r"path\to\s1bert25hz.ckpt")
SOVITS_MODEL_PATH = Path(r"path\to\s2G2333k.pth")
