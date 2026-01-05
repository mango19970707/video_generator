import os
import subprocess
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip

# def add_audio_and_subtitles(subtitle_font, video_path, audio_path, subtitles, output_path):
#     try:
#         video = VideoFileClip(video_path)
#         final_video = video
#
#         if os.path.exists(audio_path):
#             audio = AudioFileClip(audio_path)
#             final_video = video.set_audio(audio)
#
#         subtitle_clips = []
#         if subtitles:
#             for sub in subtitles:
#                 txt_clip = TextClip(
#                     sub['text'],
#                     fontsize=50,
#                     color='white',
#                     font=subtitle_font,
#                     method='label',
#                     align='center',
#                     bg_color='transparent'
#                 ).set_duration(sub['end'] - sub['start'])
#
#                 txt_clip = txt_clip.set_position('bottom').set_start(sub['start']).set_end(sub['end'])
#                 subtitle_clips.append(txt_clip)
#
#         if subtitle_clips:
#             final_video = CompositeVideoClip([final_video] + subtitle_clips)
#
#         final_video.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
#
#         video.close()
#         if 'audio' in locals(): audio.close()
#         final_video.close()
#         print(f"[Merge] Saved segment: {output_path}")
#
#     except Exception as e:
#         print(f"[Merge] Error processing {video_path}: {e}")

def add_audio_and_subtitles(subtitle_font, video_path, audio_path, subtitles, output_path):
    try:
        video = VideoFileClip(video_path)
        audio = None  # 提前初始化audio变量，避免locals()判断失败
        final_video = video

        # 读取音频并绑定（若音频文件存在）
        if os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            final_video = video.set_audio(audio)

        # 计算原视频与音频的长度，取最小值作为最终视频长度
        video_duration = video.duration  # 获取原视频时长
        audio_duration = audio.duration if (audio is not None and os.path.exists(audio_path)) else video_duration
        final_duration = min(video_duration, audio_duration)  # 取两者最小值

        # 生成字幕片段
        subtitle_clips = []
        if subtitles:
            for sub in subtitles:
                # 过滤超出最终视频时长的字幕，避免无效渲染
                sub_start = max(0, sub['start'])
                sub_end = min(sub['end'], final_duration)
                if sub_start >= sub_end:
                    continue  # 跳过无效字幕

                txt_clip = TextClip(
                    sub['text'],
                    fontsize=50,
                    color='white',
                    font=subtitle_font,
                    method='label',
                    align='center',
                    bg_color='transparent'
                ).set_duration(sub_end - sub_start)

                txt_clip = txt_clip.set_position('bottom').set_start(sub_start).set_end(sub_end)
                subtitle_clips.append(txt_clip)

        # 合成视频与字幕
        if subtitle_clips:
            final_video = CompositeVideoClip([final_video] + subtitle_clips)

        # 裁剪最终视频到目标时长（核心修改：确保长度为两者最小值）
        final_video = final_video.subclip(0, final_duration)

        # 写入输出文件
        final_video.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)

        # 关闭资源，避免内存泄漏
        video.close()
        if audio is not None:
            audio.close()
        final_video.close()
        print(f"[Merge] Saved segment: {output_path}")

    except Exception as e:
        print(f"[Merge] Error processing {video_path}: {e}")

def merge_videos_ffmpeg(input_files, output_file):
    # Use ffmpeg via subprocess for robustness
    input_args = ""
    for file in input_files:
        input_args += f"-i \"{file}\" "

    # Simple concat filter
    command = f"ffmpeg {input_args} -filter_complex concat=n={len(input_files)}:v=1:a=1 -f mp4 -y \"{output_file}\""
    print(f"[Merge] Executing ffmpeg concat...")
    subprocess.run(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def add_bg_music(video_path, bg_music_path, output_path):
    if not os.path.exists(video_path) or not os.path.exists(bg_music_path):
        print("Missing video or background music file.")
        return False

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", bg_music_path,
        "-filter_complex",
        "[0:a]volume=1.0[v_audio];[1:a]volume=0.25[bg_audio];[v_audio][bg_audio]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-y",
        output_path
    ]

    try:
        subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        print(f"[Final] Video saved to: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Final] FFmpeg error: {e}")
        return False