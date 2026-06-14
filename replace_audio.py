import subprocess
import os

import path_config as paths
from log_utils import install_timestamped_print


install_timestamped_print()


def batch_replace_audio():
    # 1. 定义基础路径和子目录
    base_dir = paths.VOICE_SRT_ROOT

    video_dir = paths.VIDEO_EN_DIR
    audio_dir = paths.FINAL_MERGED_DIR
    output_dir = paths.VIDEO_CN_DIR

    # 2. 检查并创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 3. 统计计数
    success_count = 0
    fail_count = 0

    # 4. 遍历原始视频文件夹中的所有 mp4 文件
    video_files = list(video_dir.glob("*.mp4"))
    paths.ensure_unique_safe_stems(video_files, str(video_dir))
    print(f"发现 {len(video_files)} 个视频文件，准备处理...\n")

    for video_path in video_files:
        # 获取不带后缀的文件名
        file_name = paths.safe_stem(video_path)
        # 构建对应的音频路径 (假设配音文件名与视频文件名完全一致)
        audio_path = audio_dir / f"{file_name}.wav"
        # 构建输出路径
        output_path = output_dir / f"{file_name}.mp4"

        # 检查配音文件是否存在
        if not audio_path.exists():
            print(f"[跳过] 找不到配音文件: {file_name}.wav")
            fail_count += 1
            continue

        print(f"正在处理: {file_name}...")

        # 5. 调用 FFmpeg 命令
        # -i video_path: 第 0 号输入（视频）
        # -i audio_path: 第 1 号输入（音频）
        # -map 0:v:0: 使用第一个输入的视频流
        # -map 1:a:0: 使用第二个输入的音频流
        # -c:v copy: 视频流直接拷贝，不重编码（极快）
        # -c:a aac: 将 wav 音频转换为 aac 编码以适配 mp4 容器
        # -shortest: 如果音视频长度不一，以短的为准（可选）
        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-i', str(audio_path),
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-shortest',
            str(output_path)
        ]

        try:
            # 运行命令，不显示繁琐的输出，只捕捉错误
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"  [成功] -> 已保存至处理后文件夹")
            success_count += 1
        except subprocess.CalledProcessError as e:
            print(f"  [失败] 处理 {file_name} 时发生错误: {e.stderr.decode()}")
            fail_count += 1

    print(f"\n{'=' * 30}")
    print(f"任务完成！")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    batch_replace_audio()
