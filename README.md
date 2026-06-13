# voice_srt

一个本地视频字幕与中文配音流水线工具。项目用于批量处理英文视频：转录英文字幕、清理字幕、调用 DeepSeek 翻译为中文字幕、调用本地 GPT-SoVITS 生成中文配音、按字幕时长调整音频、合并音频并替换到视频中。

## 功能

- 批量扫描视频并生成英文 SRT 字幕
- 清理英文/中文字幕中的多余内容
- 使用 DeepSeek API 将英文字幕翻译为中文
- 调用本地 TTS 服务生成中文配音片段
- 根据字幕时间轴调整配音语速
- 合并配音片段为完整音轨
- 使用 FFmpeg 将中文音轨替换进视频
- 支持多个课程/项目根目录串行批量处理

## 处理流程

默认流水线顺序如下：

```text
video_en
  -> transcribe_batch.py
srt_en/srt_en_before
  -> clean_srt.py
srt_en/srt_en_after
  -> translate_batch.py
srt_cn/srt_cn_before
  -> clean_srt.py
srt_cn/srt_cn_after
  -> batch_tts.py
before_speed
  -> speed_audio.py
after_speed
  -> merge_audio.py
final_merged
  -> replace_audio.py
video_cn
```

## 目录结构

每个处理根目录默认使用下面的结构：

```text
VOICE_SRT_ROOT/
├─ video_en/                 # 原始英文视频
├─ video_cn/                 # 替换中文音轨后的视频
├─ srt_en/
│  ├─ srt_en_before/         # 转录出的英文字幕
│  └─ srt_en_after/          # 清理后的英文字幕
├─ srt_cn/
│  ├─ srt_cn_before/         # 翻译出的中文字幕
│  └─ srt_cn_after/          # 清理后的中文字幕
├─ before_speed/             # TTS 生成的原始配音片段
├─ after_speed/              # 调速后的配音片段
├─ final_merged/             # 合并后的完整音轨
└─ _merge_tmp/               # 合并过程临时目录
```

## 环境要求

- Python 3.10+
- FFmpeg，并确保 `ffmpeg` 可以在命令行中直接运行
- 本地 faster-whisper 模型
- 本地 GPT-SoVITS/TTS 服务，默认接口为 `http://127.0.0.1:23451/tts`
- DeepSeek API Key

Python 依赖大致包括：

```bash
pip install requests pysubs2 openai faster-whisper
```

如果在 Windows + CUDA 环境运行 faster-whisper，可能还需要安装对应的 NVIDIA CUDA Python 包，例如脚本中提示的 `nvidia-cublas-cu12`。

## 私有配置

不要把 API Key、本机路径、模型路径写进公开代码。项目已经提供模板：

```bash
copy private_config.example.py private_config.py
```

然后在 `private_config.py` 中填写自己的配置：

```python
from pathlib import Path

VOICE_SRT_ROOT = Path(r"path\to\one\course")

BATCH_VOICE_SRT_ROOTS = [
    VOICE_SRT_ROOT,
]

DEEPSEEK_API_KEY = ""

WHISPER_MODEL_PATH = Path(r"path\to\faster-whisper-large-v3")

TTS_PROMPT_AUDIO = r"path\to\prompt.wav"
TTS_PROMPT_AUDIO_TEXT = ""

GPT_MODEL_PATH = Path(r"path\to\s1bert25hz.ckpt")
SOVITS_MODEL_PATH = Path(r"path\to\s2G2333k.pth")
```

`private_config.py` 已经被 `.gitignore` 忽略，不会被上传到 GitHub。

也可以用环境变量覆盖部分配置：

- `VOICE_SRT_ROOT`
- `DEEPSEEK_API_KEY`
- `WHISPER_MODEL_PATH`
- `TTS_PROMPT_AUDIO`
- `TTS_PROMPT_AUDIO_TEXT`
- `GPT_MODEL_PATH`
- `SOVITS_MODEL_PATH`

## 使用方法

运行完整流水线：

```bash
python pipeline_runner.py
```

只运行指定任务：

```bash
python pipeline_runner.py --tasks transcribe_batch clean_srt_en translate_batch
```

运行全部任务：

```bash
python pipeline_runner.py --tasks all
```

指定多个处理根目录：

```bash
python pipeline_runner.py --roots path\to\course1 path\to\course2
```

预览将要执行的任务，不真正运行：

```bash
python pipeline_runner.py --dry-run
```

也可以单独运行某个阶段：

```bash
python transcribe_batch.py
python clean_srt.py
python translate_batch.py
python batch_tts.py
python speed_audio.py
python merge_audio.py
python replace_audio.py
```

## 任务说明

| 脚本 | 作用 |
| --- | --- |
| `transcribe_batch.py` | 读取 `video_en/` 中的视频，使用 faster-whisper 生成英文字幕 |
| `clean_srt.py` | 清理或复制字幕，支持英文和中文阶段 |
| `translate_batch.py` | 调用 DeepSeek 将英文字幕翻译为中文字幕 |
| `batch_tts.py` | 调用本地 TTS 服务，为中文字幕逐句生成 WAV 音频 |
| `speed_audio.py` | 根据字幕时间轴调整每句配音长度 |
| `merge_audio.py` | 将调速后的音频片段合并为完整音轨 |
| `replace_audio.py` | 用 FFmpeg 将中文音轨替换进原视频 |
| `pipeline_runner.py` | 按固定顺序串行调度所有任务 |
| `path_config.py` | 统一管理目录结构和私有配置读取 |

## 上传 GitHub 前检查

建议提交前运行：

```bash
git status --short --ignored
```

确认下面这些内容处于 ignored 状态，不要上传：

- `private_config.py`
- `.env`
- `.venv/`
- `__pycache__/`
- 视频、字幕、音频输出目录
- 本地临时脚本或临时目录

## 注意事项

- DeepSeek API Key 不应提交到 GitHub。如果曾经提交过，请立即去平台后台轮换 Key。
- `batch_tts.py` 默认请求本机 `http://127.0.0.1:23451/tts`，运行前需要先启动对应 TTS 服务。
- `replace_audio.py`、`merge_audio.py`、`speed_audio.py` 依赖 FFmpeg。
- 大视频、音频、字幕结果文件默认不进入 Git，只保留代码和配置模板。
