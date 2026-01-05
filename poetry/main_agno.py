import os
import time
import yaml
import shutil
import threading
import subprocess
import requests
from typing import List, Dict
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

# Load configuration
def load_config(config_path: str = None) -> dict:
    if config_path is None:
        # Default to config.yaml in the same directory as this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.yaml")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# Set Global Settings
API_KEY = CONFIG["api"]["dashscope_key"]
dashscope.api_key = API_KEY
dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1' # Default for video

# Configure ImageMagick
change_settings({"IMAGEMAGICK_BINARY": CONFIG["paths"]["imagemagick"]})

# ==================================================
# Tools / Helper Functions
# ==================================================

def split_poetry(poetry: str) -> List[str]:
    """Splits poetry into sentences."""
    tmp_sentences = poetry.split('\n')
    final_sentences = []
    for sentence in tmp_sentences:
        # Split by Chinese period
        tmp = sentence.split('。')
        for t in tmp:
            if t.strip() != '':
                final_sentences.append(t.strip())
    return final_sentences

def ensure_dir(file_path: str):
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

def write_text_to_file(file_path: str, content: str):
    ensure_dir(file_path)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def read_file_content(file_path: str) -> str:
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return ""
    return ""

def download_video(url: str, save_path: str) -> bool:
    try:
        ensure_dir(save_path)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"Video downloaded to: {save_path}")
        return True
    except Exception as e:
        print(f"Error downloading video: {e}")
        return False

# ==================================================
# Step 2: TTS (Text to Speech)
# ==================================================
connection_pool = SpeechSynthesizerObjectPool(max_size=3)
USE_CONNECTION_POOL = True

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
            complete_event.set() # Ensure we don't block forever

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
    file_path = f"./{title}/audio/{sentence}.mp3"
    if os.path.exists(file_path):
        print(f"[TTS] Skipping existing: {sentence}")
        return

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
        t = threading.Thread(target=generate_single_audio, args=(title, sentence))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()

# ==================================================
# Step 3: Lens Generation (Agno Agent)
# ==================================================

def create_director_agent():
    return Agent(
        model=DashScopeModel(
            id=CONFIG["llm"]["model"],
            api_key=API_KEY,
            base_url=CONFIG["api"]["base_url"]
        ),
        description="You are a director expert in Chinese classical poetry and visual arts.",
        instructions=[
            "Focus on a single shot (suitable for a 5-second short video).",
            "Visuals: Aesthetic, ethereal, poetic, emphasizing composition blank space, soft lighting, and delicate dynamics.",
            "Scene elements: Time, main scene, key visual elements, main color tone.",
            "Output format: 'Lens Angle: Visual Description'.",
            "Keep the description under 200 words.",
            "Output ONLY the description."
        ],
        markdown=True
    )

def generate_lens_prompts(title, sentences):
    agent = create_director_agent()
    
    for sentence in sentences:
        file_path = f"./{title}/lens/{sentence}.txt"
        if os.path.exists(file_path):
            continue
            
        print(f"[Lens] Generating prompt for: {sentence}")
        response = agent.run(sentence)
        
        content = response.content
        # Prepend style as in original code
        full_content = "风格：二次元动漫，中式古风，水墨画。\n" + content
        write_text_to_file(file_path, full_content)

# ==================================================
# Step 4: Video Generation
# ==================================================

def generate_single_video(title, sentence):
    file_path = f"./{title}/video/{sentence}.mp4"
    lens_path = f"./{title}/lens/{sentence}.txt"
    
    if os.path.exists(file_path):
        print(f"[Video] Skipping existing: {sentence}")
        return

    lens = read_file_content(lens_path)
    if not lens:
        print(f"[Video] No lens prompt found for: {sentence}")
        return

    video_config = CONFIG["video"]
    print(f"[Video] Generating for: {sentence}")
    
    try:
        rsp = VideoSynthesis.call(
            api_key=API_KEY,
            model=video_config["model"],
            prompt=lens,
            size=video_config["size"],
            duration=video_config["duration"],
            prompt_extend=True,
            watermark=False,
            seed=12345
        )

        if rsp.status_code == HTTPStatus.OK:
            print(f"[Video] Success: {sentence}")
            download_video(rsp.output.video_url, file_path)
        else:
            print(f"[Video] Failed: {sentence}, {rsp.message}")
    except Exception as e:
        print(f"[Video] Exception: {e}")

def generate_video_batch(title, sentences):
    for sentence in sentences:
        generate_single_video(title, sentence)

# ==================================================
# Step 5: Merge & Post-processing
# ==================================================

def add_audio_and_subtitles(video_path, audio_path, subtitles, output_path):
    subtitle_font = CONFIG["paths"]["font"]
    
    try:
        video = VideoFileClip(video_path)
        final_video = video
        
        if os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            final_video = video.set_audio(audio)
        
        subtitle_clips = []
        if subtitles:
            for sub in subtitles:
                txt_clip = TextClip(
                    sub['text'],
                    fontsize=50,
                    color='white',
                    font=subtitle_font,
                    method='label',
                    align='center',
                    bg_color='transparent'
                ).set_duration(sub['end'] - sub['start'])
                
                txt_clip = txt_clip.set_position('bottom').set_start(sub['start']).set_end(sub['end'])
                subtitle_clips.append(txt_clip)
        
        if subtitle_clips:
            final_video = CompositeVideoClip([final_video] + subtitle_clips)
            
        final_video.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
        
        video.close()
        if 'audio' in locals(): audio.close()
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

def generate_final_video(title, sentences):
    segment_videos = []
    
    for sentence in sentences:
        video_file = f"./{title}/video/{sentence}.mp4"
        audio_file = f"./{title}/audio/{sentence}.mp3"
        output_path = f"./{title}/{sentence.replace(' ','')}.mp4"
        
        if not os.path.exists(video_file):
            print(f"Missing video file: {video_file}")
            continue
            
        segment_videos.append(output_path)
        
        # Assume 5 seconds duration per clip roughly, or use audio duration
        # Original code used fixed 5s end time for subtitle.
        add_audio_and_subtitles(
            video_path=video_file,
            audio_path=audio_file,
            subtitles=[{'text': sentence, 'start': 0, 'end': 5}],
            output_path=output_path
        )
    
    if not segment_videos:
        print("No segments created.")
        return

    tmp_merged = f"./{title}/tmp_{title}.mp4"
    merge_videos_ffmpeg(segment_videos, tmp_merged)
    
    final_output = f"./{title}/{title}.mp4"
    bg_music = CONFIG["paths"]["bg_music"]
    
    add_bg_music(tmp_merged, bg_music, final_output)

# ==================================================
# Main Execution Flow
# ==================================================

def main():
    poetry_config = CONFIG["poetry"]
    title = poetry_config["title"]
    content = poetry_config["content"]
    
    print(f"Processing Poetry: {title}")
    
    # Step 1: Split
    sentences = split_poetry(content)
    print(f"Sentences: {sentences}\n")
    
    # Step 2: Audio
    print(">>> Generating Audio...")
    generate_audio_batch(title, sentences)
    
    # Step 3: Lens Prompts (Agno)
    print("\n>>> Generating Lens Prompts...")
    generate_lens_prompts(title, sentences)
    
    # Step 4: Video
    print("\n>>> Generating Video...")
    generate_video_batch(title, sentences)
    
    # Step 5: Merge
    print("\n>>> Finalizing Video...")
    generate_final_video(title, sentences)

if __name__ == "__main__":
    main()
