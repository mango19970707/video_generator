import os
import sys
import time
from dataclasses import replace

import yaml
import shutil
import threading
import subprocess
import requests
import json
from typing import List, Dict, Optional
from datetime import datetime
from http import HTTPStatus

# Third-party libraries
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, SpeechSynthesizerObjectPool, ResultCallback
from dashscope import VideoSynthesis
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip
from moviepy.config import change_settings

# Agno framework
from agno.agent import Agent
from agno.models.dashscope import DashScope as DashScopeModel
from openai import OpenAI

current_script_dir = os.path.dirname(os.path.abspath(__file__))
utils_dir = os.path.dirname(current_script_dir)
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

# Local libraries
from utils.file import *
from utils.string import *
from utils.video import *

# ==================================================
# Step 1: 加载配置
# ==================================================
def load_config(config_path: str = None) -> dict:
    if config_path is None:
        # Default to config.yaml in the same directory as this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# ==================================================
# Step 2: 生成科普内容，保证分隔符只包含“”《》，。等内容
# ==================================================
client = OpenAI(
    api_key=CONFIG["api"]["dashscope_key"],
    base_url=CONFIG["api"]["base_url"],
)

def generate_content(title):
    prompt = read_file_content("prompts/生成科普内容.md")
    messages = [{"role": "system", "content": prompt}]

    file_path = f"./{title}/{title}.json"
    if os.path.exists(file_path):
        return
    messages.append( {"role": "user", "content": title})
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=messages
    )
    # messages.append({"role": "assistant", "content": completion.choices[0].message.content})
    write_text_to_file(file_path, completion.choices[0].message.content)

# ==================================================
# Step 3: 解析科普内容
# ==================================================
def parse_herb_video_script(json_str: str) -> Optional[Dict]:
    """
    解析中医药材科普视频JSON脚本

    Args:
        json_str: 符合指定格式的JSON字符串

    Returns:
        解析后的结构化字典，包含video_basic_info和storyboard_list两个key；
        若解析失败（格式错误/字段缺失），返回None

    Raises:
        无显式抛出异常，错误信息通过print打印
    """
    # 1. 基础JSON解析与格式校验
    try:
        script_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"JSON格式错误：{e}")
        return None

    # 2. 核心字段完整性校验
    required_root_fields = ["video_basic_info", "storyboard_list"]
    for field in required_root_fields:
        if field not in script_data:
            print(f"缺失核心字段：{field}")
            return None

    # 3. 解析视频基础信息（校验必选子字段）
    basic_info = script_data["video_basic_info"]
    required_basic_fields = ["theme", "style"]
    for field in required_basic_fields:
        if field not in basic_info:
            print(f"video_basic_info缺失字段：{field}")
            return None

    # 4. 解析分镜列表（校验每个分镜的必选字段）
    storyboard_list = script_data["storyboard_list"]
    required_storyboard_fields = [
        "duration", "voice_text", "picture_content", "shot_type"
    ]

    # 存储解析后的分镜信息（可按需扩展处理逻辑）
    parsed_storyboards = []
    for idx, storyboard in enumerate(storyboard_list, 1):
        # 校验单分镜字段完整性
        missing_fields = [f for f in required_storyboard_fields if f not in storyboard]
        if missing_fields:
            print(f"第{idx}个分镜缺失字段：{', '.join(missing_fields)}")
            return None

        # 可选：对分镜数据进行格式转换（如时长转为int、序号校验连续性）
        try:
            storyboard["duration"] = int(storyboard["duration"])
        except ValueError:
            print(f"第{idx}个分镜字段格式错误：duration需为数字")
            return None

        parsed_storyboards.append(storyboard)

    # 5. 格式化打印解析结果（提升可读性）
    print("=" * 50)
    print("📽️  中医药材科普视频脚本解析结果")
    print("=" * 50)
    print(f"视频主题：{basic_info['theme']}")
    print(f"视频风格：{basic_info['style']}")
    print(f"总分镜数量：{len(parsed_storyboards)}个")
    print("\n🎬 分镜详情：")
    print("-" * 50)
    for sb in parsed_storyboards:
        print(f"时长：{sb['duration']}秒")
        print(f"口播文本：{sb['voice_text']}")
        print(f"画面内容：{sb['picture_content']}")
        print(f"镜头类型：{sb['shot_type']}")
        print("-" * 50)

    # 6. 返回结构化数据（供后续业务调用，如导入剪辑软件、生成报表等）
    return {
        "video_basic_info": basic_info,
        "parsed_storyboards": parsed_storyboards
    }

# ==================================================
# Step 4: 合成语音
# ==================================================
def synthesis_callback(title, sentence, complete_event):
    class Callback(ResultCallback):
        def on_open(self):
            dest_path = f"./{title}/audio/{sentence}.mp3"
            ensure_dir(dest_path)
            self.file = open(dest_path, 'wb')
            print(f'[TTS] Start: {sentence}')

        def on_complete(self):
            print(f'[TTS] Complete: {sentence}')
            complete_event.set()

        def on_error(self, message: str):
            print(f'[TTS] Failed: {sentence}, {message}')
            complete_event.set()  # Ensure we don't block forever

        def on_close(self):
            if hasattr(self, 'file'):
                self.file.close()

        def on_event(self, message):
            pass

        def on_data(self, data: bytes) -> None:
            if hasattr(self, 'file'):
                self.file.write(data)

    return Callback()


def generate_single_audio(title, sentence):
    dashscope.api_key = CONFIG["api"]["dashscope_key"]
    connection_pool = SpeechSynthesizerObjectPool(max_size=3)

    complete_event = threading.Event()
    callback = synthesis_callback(title, sentence, complete_event)

    tts_config = CONFIG["tts"]

    synthesizer = connection_pool.borrow_synthesizer(
        model=tts_config["model"],
        voice=tts_config["voice"],
        volume=tts_config["volume"],
        speech_rate=tts_config["speech_rate"],
        callback=callback
    )

    try:
        synthesizer.call(sentence)
        complete_event.wait()
    except Exception as e:
        print(f"[TTS] Error: {e}")
    finally:
        connection_pool.return_synthesizer(synthesizer)


def generate_audio_batch(title, sentences):
    threads = []
    for sentence in sentences:
        file_path = f"./{title}/audio/{sentence}.mp3"
        if os.path.exists(file_path):
            print(f"[TTS] Skipping existing: {sentence}")
            continue
        t = threading.Thread(target=generate_single_audio, args=(title, sentence))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

# ==================================================
# Step 5: 生成视频
# ==================================================
def generate_single_video(title, content, duration):
    file_path = f"./{title}/video/{content.replace(' ','').replace(':', '')}.mp4"

    if os.path.exists(file_path) or content == "":
        print(f"[Video] Skipping existing: {content}")
        return

    video_config = CONFIG["video"]
    print(f"[Video] Generating for: {content}")

    try:
        rsp = VideoSynthesis.call(
            api_key=CONFIG["api"]["dashscope_key"],
            model=video_config["model"],
            prompt=content,
            size=video_config["size"],
            duration=duration,
            prompt_extend=True,
            watermark=False,
            seed=12345
        )

        if rsp.status_code == HTTPStatus.OK:
            print(f"[Video] Success: {content}, url: {rsp.output.video_url}")
            download_video(rsp.output.video_url, file_path)
        else:
            print(f"[Video] Failed: {content}, {rsp.message}")
    except Exception as e:
        print(f"[Video] Exception: {e}")


def generate_video_batch(title, lens):
    for len in lens:
        generate_single_video(title, len.get('content'), len.get('duration'))

# ==================================================
# Step 6: 根据科普内容，生成背景音乐
# ==================================================


# ==================================================
# Step 7: 合并语音、视频、字幕、背景音乐
# ==================================================
# 配置ImageMagick路径
change_settings({"IMAGEMAGICK_BINARY": r"D:\apps\ImageMagick-7.1.2-11-portable-Q16-HDRI-x64\magick.exe"})

def generate_final_video(title, audio_texts, video_texts):
    segment_videos = []

    for i, audio_text in enumerate(audio_texts):
        video_file = f"./{title}/video/{video_texts[i].get('content').replace(' ', '').replace(':', '')}.mp4"
        audio_file = f"./{title}/audio/{audio_text}.mp3"
        output_path = f"./{title}/{audio_text.replace(' ', '').replace(':', '')}.mp4"

        if not os.path.exists(video_file):
            print(f"Missing video file: {video_file}")
            continue

        segment_videos.append(output_path)

        # Assume 5 seconds duration per clip roughly, or use audio duration
        # Original code used fixed 5s end time for subtitle.
        add_audio_and_subtitles(
            video_path=video_file,
            audio_path=audio_file,
            subtitles=[{'text': audio_text, 'start': 0, 'end': 5}],
            output_path=output_path,
            subtitle_font='C:/Windows/Fonts/simhei.ttf'
        )

    if not segment_videos:
        print("No segments created.")
        return

    tmp_merged = f"./{title}/tmp_{title}.mp4"
    merge_videos_ffmpeg(segment_videos, tmp_merged)

    final_output = f"./{title}/{title}.mp4"

    # bg_music = CONFIG["paths"]["bg_music"]
    # add_bg_music(tmp_merged, bg_music, final_output)



if __name__ == '__main__':
    title = "金银花"
    # step 1. 加载配置

    # step 2. 生成科普内容，保证分隔符只包含“”《》，。等内容
    generate_content(title)

    # step 3. 解析科普内容
    jsonContent = parse_herb_video_script(read_file_content(f"./{title}/{title}.json"))

    # step 4. 合成语音
    audio_texts = []
    for item in jsonContent["parsed_storyboards"]:
        if item["voice_text"] == "":
            continue
        audio_texts.append(item["voice_text"])
    generate_audio_batch(title, audio_texts)

    # step 5. 根据分镜镜头，生成视频
    video_texts = []
    for item in jsonContent["parsed_storyboards"]:
        video_text = dict()
        if item["picture_content"] == "":
            continue
        video_text["duration"] = item["duration"]
        video_text["content"] = f"镜头角度: {item["shot_type"]}。画面: {item["picture_content"]}"
        video_texts.append(video_text)
    generate_video_batch(title, video_texts)

    # step 6. 根据科普内容，生成背景音乐

    # step 7. 合并语音、视频、字幕、背景音乐
    generate_final_video(title, audio_texts, video_texts)