# coding=utf-8
import time
import ffmpeg
import tempfile
import dashscope
from dashscope.audio.tts_v2 import *
import shutil
from datetime import datetime
import os
from openai import OpenAI
from http import HTTPStatus
from dashscope import VideoSynthesis
import requests
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip, concatenate_videoclips
from moviepy.config import change_settings
import threading
# API_KEY = 'sk-e5a2cf9c95de4b628a35daa9975ef608'
API_KEY = os.environ['API_KEY']
# ==================================================step 1 拆分诗词
def splitPoetry(poetry):
    tmpSentences = poetry.split('\n')
    finalSentences = []
    for sentence in tmpSentences:
        tmp = sentence.split('。')
        for t in tmp:
            if t != '':
                finalSentences.append(t)
    return finalSentences

# ==================================================step 2 把每一句诗词转化为audio
dashscope.api_key = API_KEY
model = "cosyvoice-v3-flash" # 模型
voice = "longanyang" # 音色
USE_CONNECTION_POOL = True
connectionPool = SpeechSynthesizerObjectPool(max_size=3)

def get_timestamp():
    now = datetime.now()
    formatted_timestamp = now.strftime("[%Y-%m-%d %H:%M:%S.%f]")
    return formatted_timestamp

def copy_file(src_path, dest_path):
    """
    将文件从源路径复制到目标路径
    如果目标目录不存在，则创建目录

    参数:
    src_path (str): 源文件路径
    dest_path (str): 目标文件路径

    返回:
    bool: 复制成功返回True，失败返回False
    """
    try:
        # 获取目标目录路径
        dest_dir = os.path.dirname(dest_path)

        # 检查目标目录是否存在，如果不存在则创建
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        # 复制文件
        shutil.copy2(src_path, dest_path)
        print(f"文件已成功从 {src_path} 复制到 {dest_path}")
        return True

    except FileNotFoundError:
        print(f"错误：源文件 {src_path} 不存在")
        return False
    except PermissionError:
        print(f"错误：没有权限访问文件或目录")
        return False
    except Exception as e:
        print(f"复制文件时发生错误: {str(e)}")
        return False

def synthesis_text_to_speech_and_play_by_streaming_mode(title, sentence):
    global USE_CONNECTION_POOL, connectionPool
    '''
    Synthesize speech with given text by streaming mode, async call and play the synthesized audio in real-time.
    for more information, please refer to https://help.aliyun.com/document_detail/2712523.html
    '''

    complete_event = threading.Event()

    # Define a callback to handle the result

    class Callback(ResultCallback):
        def on_open(self):
            # when using object pool, on_open will be called after task start
            # 获取目标目录路径
            dest_path = f"./{title}/audio/{sentence}.mp3"
            dest_dir = os.path.dirname(dest_path)

            # 检查目标目录是否存在，如果不存在则创建
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)

            self.file = open(dest_path, 'wb')
            print(f'[task_{sentence}] start')

        def on_complete(self):
            print(f'[task_{sentence}] speech synthesis task complete successfully.')
            complete_event.set()

        def on_error(self, message: str):
            print(f'[task_{sentence}] speech synthesis task failed, {message}')

        def on_close(self):
            # when using object pool, on_open will be called after task finished
            print(f'[task_{sentence}] finished')

        def on_event(self, message):
            # print(f'recv speech synthsis message {message}')
            pass

        def on_data(self, data: bytes) -> None:
            # send to player
            # save audio to file
            self.file.write(data)

    # Call the speech synthesizer callback
    synthesizer_callback = Callback()

    # Initialize the speech synthesizer
    # you can customize the synthesis parameters, like voice, format, sample_rate or other parameters
    if USE_CONNECTION_POOL:
        speech_synthesizer = connectionPool.borrow_synthesizer(
            model='cosyvoice-v3-flash',
            voice='longanyang',
            seed=12382,
            callback=synthesizer_callback
        )
    else:
        speech_synthesizer = SpeechSynthesizer(model='cosyvoice-v3-flash',
                                               voice='longanyang',
                                               seed=12382,
                                               callback=synthesizer_callback)
    try:
        speech_synthesizer.call(sentence)
    except Exception as e:
        print(f'[task_{sentence}] speech synthesis task failed, {e}')
        if USE_CONNECTION_POOL:
            # close the synthesizer connection manually if task failed when using connection pool.
            speech_synthesizer.close()
        return

    complete_event.wait()
    print('[task_{}][Metric] requestId: {}, first package delay ms: {}'.format(
        sentence,
        speech_synthesizer.get_last_request_id(),
        speech_synthesizer.get_first_package_delay()))
    if USE_CONNECTION_POOL:
        connectionPool.return_synthesizer(speech_synthesizer)

def generate_audio(title, sentences):
    task_thread_list = []
    for i in range(len(sentences)):
        file_path = f"./{title}/audio/{sentences[i]}.mp3"
        if os.path.exists(file_path):
            continue
        thread = threading.Thread(
            target=synthesis_text_to_speech_and_play_by_streaming_mode,
            args=(title, sentences[i]))
        task_thread_list.append(thread)

    for task_thread in task_thread_list:
        task_thread.start()

    for task_thread in task_thread_list:
        task_thread.join()

    if USE_CONNECTION_POOL:
        connectionPool.shutdown()

# ==================================================step 3 分析每一句诗词，每一句对应一个镜头场景
def write_text_to_file(file_path, content):
    """
    将指定文本写入指定文件
    如果文件路径不存在，则创建目录

    参数:
    file_path (str): 目标文件路径
    content (str): 要写入的文本内容
    """
    try:
        # 获取文件所在目录
        directory = os.path.dirname(file_path)

        # 如果目录不存在，则创建目录
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"文本已成功写入文件: {file_path}")
        return True

    except Exception as e:
        print(f"写入文件时发生错误: {str(e)}")
        return False

client = OpenAI(
    # 若没有配置环境变量，请用阿里云百炼API Key将下行替换为：api_key="sk-xxx",
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    api_key=API_KEY,
    # 以下是北京地域base_url，如果使用新加坡地域的模型，需要将base_url替换为：https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

def generate_lens(title, sentences):
    messages = [{"role": "system", "content": """你是一位精通中国古典诗词与视觉艺术的导演。请根据用户提供的诗句，用一段不超过200字的中文描述，精准还原其核心画面。要求：
    聚焦单一镜头（适合5秒短视频）；
    画面：唯美、空灵、富有诗意，强调构图留白、柔和光影、细腻动态（如衣袂轻扬、花瓣旋落、烛火摇曳）；
    场景元素：时间（晨/夜/黄昏/晌午）、主场景（庭院/江岸/山林等）、关键视觉元素（如纸伞、灯笼、飞鸟、流水）、主色调（如青绿、月白、朱砂、黛蓝等）；
    输出格式：镜头角度：画面描述。
    示例：
    输入1：“孤舟蓑笠翁，独钓寒江雪。”（柳宗元《江雪》）
    输出1：“广角远景：灰白色调的冬日江面，雪花缓缓飘落，水面泛起细碎涟漪；一叶乌篷小舟泊于江心，船头坐着披棕褐色蓑衣、戴斗笠的老翁，手持竹竿垂钓，身影渺小却坚定，四周空无一人，天地苍茫。”

    输入2：“月落乌啼霜满天，江枫渔火对愁眠。”（张继《枫桥夜泊》）
    输出2：“夜景中景：深蓝夜空下弦月西沉，几只乌鸦掠过枯枝；江边枫树红叶半凋，岸边渔船挂着一盏昏黄油灯，灯火在寒雾中晕染出暖光，水面倒影随波晃动，远处隐约可见石桥轮廓。”
    """}]
    for sentence in sentences:
        file_path = f"./{title}/lens/{sentence}.txt"
        if os.path.exists(file_path):
            continue
        messages.append( {"role": "user", "content": sentence})
        completion = client.chat.completions.create(
            model="qwen-plus",
            messages=messages
        )
        messages.append({"role": "assistant", "content": completion.choices[0].message.content})
        write_text_to_file(file_path, "风格：二次元动漫，中式古风，水墨画。\n"+completion.choices[0].message.content)

# ==================================================step 4 根据镜头场景生成视频
def download_video(url, save_path):
    """
    将指定URL的视频下载到指定路径
    如果路径不存在，则创建目录

    参数:
    url (str): 视频URL地址
    save_path (str): 保存路径

    返回:
    bool: 下载成功返回True，失败返回False
    """
    try:
        # 获取文件所在目录
        directory = os.path.dirname(save_path)

        # 如果目录不存在，则创建目录
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        # 发送HTTP请求下载视频
        response = requests.get(url, stream=True)
        response.raise_for_status()  # 检查请求是否成功

        # 写入文件
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # 过滤掉保持连接的空块
                    f.write(chunk)

        print(f"视频已成功下载到: {save_path}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"下载视频时发生网络错误: {str(e)}")
        return False
    except Exception as e:
        print(f"下载视频时发生错误: {str(e)}")
        return False


def read_file_content(file_path):
    """
    从指定路径读取文件内容，如果文件不存在则返回空字符串

    参数:
    file_path (str): 文件路径

    返回:
    str: 文件内容，如果文件不存在则返回空字符串
    """
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"读取文件时发生错误: {str(e)}")
            return ""
    else:
        return ""

# 以下为北京地域url，若使用新加坡地域的模型，需将url替换为：https://dashscope-intl.aliyuncs.com/api/v1
dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

# 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
# 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
api_key = API_KEY

def generate_video(title, sentence, lens):
    file_path = f"./{title}/video/{sentence}.mp4"
    if os.path.exists(file_path) or lens == "":
        return

    rsp = VideoSynthesis.call(api_key=api_key,
                              model='wanx2.1-t2v-plus',
                              prompt=lens,
                              # audio_url='https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250923/hbiayh/%E4%BB%8E%E5%86%9B%E8%A1%8C.mp3',
                              size='1088*832',
                              duration=3,
                              negative_prompt="",
                              # audio=True,
                              prompt_extend=True,
                              watermark=False,
                              seed=12345)
    # print(rsp)
    if rsp.status_code == HTTPStatus.OK:
        print("%s %s" % (sentence, rsp.output.video_url))
        download_video(rsp.output.video_url, file_path)
    else:
        print('%s Failed, status_code: %s, code: %s, message: %s' %
              (sentence, rsp.status_code, rsp.code, rsp.message))

def generate_videos(title, sentences):
    for sentence in sentences:
        lens=read_file_content(f"./{title}/lens/{sentence}.txt")
        generate_video(title, sentence, lens)

# ==================================================step 5 拼接视频、音频和字幕
# 配置ImageMagick路径
change_settings({"IMAGEMAGICK_BINARY": r"D:\apps\ImageMagick-7.1.2-11-portable-Q16-HDRI-x64\magick.exe"})


def merge_videos(video_paths, output_path):
    """
    健壮的视频合并函数，处理各种编码问题
    """
    # 验证文件路径
    for path in video_paths:
        if not os.path.exists(path):
            print(f"错误: 文件不存在 - {path}")
            return False

    # 检查输出路径的编码兼容性
    try:
        output_path.encode('utf-8')
    except UnicodeEncodeError:
        print("输出路径包含不兼容的字符，请使用英文路径")
        return False

    temp_file = None
    try:
        # 创建临时文件列表
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            temp_file = f.name
            for path in video_paths:
                abs_path = os.path.abspath(path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")

        # 尝试使用ffmpeg-python
        try:
            stream = ffmpeg.input(temp_file, format='concat', safe=0)
            stream = ffmpeg.output(stream, output_path, c='copy')
            ffmpeg.run(stream, overwrite_output=True, quiet=True)
        except ffmpeg.Error as e:
            # 处理错误输出的编码问题
            if e.stderr:
                try:
                    error_msg = e.stderr.decode('utf-8', errors='replace')
                except:
                    error_msg = str(e.stderr)
                print(f"FFmpeg错误: {error_msg}")
            return False

        print(f"视频合并成功，输出文件: {output_path}")
        return True

    except UnicodeError as e:
        print(f"编码错误: {str(e)}")
        print("建议：确保文件路径不包含特殊字符或使用英文路径")
        return False
    except Exception as e:
        print(f"合并视频时出错: {str(e)}")
        return False
    finally:
        # 清理临时文件
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except:
                pass

def add_audio_and_subtitles(video_path, audio_path=None, subtitles=None, output_path="output.mp4",
                            subtitle_position='bottom', subtitle_font=None, subtitle_size=50,
                            subtitle_color='white', subtitle_bg_color='transparent'):
    """
    为视频添加音频和文本字幕
    """
    # 设置默认中文字体
    if subtitle_font is None:
        if os.name == 'nt':  # Windows
            subtitle_font = 'C:/Windows/Fonts/simhei.ttf'  # 黑体，通常支持中文效果好
        else:
            subtitle_font = 'Arial'

    # 加载原始视频
    video = VideoFileClip(video_path)

    # 如果提供了音频文件，则加载音频
    final_video = video
    if audio_path:
        audio = AudioFileClip(audio_path)
        final_video = video.set_audio(audio)

    # 创建字幕列表
    subtitle_clips = []

    if subtitles:
        for subtitle in subtitles:
            text = subtitle['text']
            start_time = subtitle['start']
            end_time = subtitle['end']

            # 创建字幕文本剪辑 - 关键设置
            txt_clip = TextClip(
                text,
                fontsize=subtitle_size,
                color=subtitle_color,
                font=subtitle_font,
                method='label',  # 使用label方法，确保文字水平排列
                align='center',
                bg_color=subtitle_bg_color
            ).set_duration(end_time - start_time)

            # 设置字幕的位置和持续时间，确保在底部居中
            txt_clip = txt_clip.set_position(subtitle_position).set_start(start_time).set_end(end_time)
            subtitle_clips.append(txt_clip)

    if subtitle_clips:
        final_video = CompositeVideoClip([final_video] + subtitle_clips)

    final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')

    video.close()
    if audio_path:
        audio.close()
    final_video.close()

    print(f"视频已保存到: {output_path}")

def generate_final_video(title, sentences):
    videos = []
    for sentence in sentences:
        video_file = f"./{title}/video/{sentence}.mp4"
        audio_file = f"./{title}/audio/{sentence}.mp3"
        print(f"{video_file} --> {audio_file}")
        subtitles = [{'text': sentence, 'start': 0, 'end': 5}]
        output_path = f"{title}/{sentence}.mp4"
        videos.append(output_path)
        add_audio_and_subtitles(
            video_path=video_file,
            audio_path=audio_file,
            subtitles=subtitles,
            output_path=output_path,
            subtitle_font='C:/Windows/Fonts/simhei.ttf'  # 使用黑体
        )
    merge_videos(videos, f"{title}/{title}.mp4")







if __name__ == '__main__':
    # title = "春晓"
    # content = "春晓，孟浩然。春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。"
    title = "虞美人"
    content = "虞美人·春花秋月何时了，李煜。春花秋月何时了？往事知多少。小楼昨夜又东风，故国不堪回首月明中。雕栏玉砌应犹在，只是朱颜改。问君能有几多愁？恰似一江春水向东流。"
    # title = "如梦令"
    # content = "如梦令，高清清。高天云淡风初暖，清溪照人面。清歌一曲过桥东，柳外纸鸢飞上、碧空中。桃花笑靥迎新雨，燕语穿林舞。此身合是画中行，不负春光十里、满襟晴。"

    # step 1. 拆分诗词
    print("step 1. 开始拆分诗词...")
    sentences = splitPoetry(content)
    for sentence in sentences:
        print(sentence)
    print()

    # # step 2. 把每一句诗词转化为audio
    # print("step 2. 开始把每一句诗词转化为audio...")
    # generate_audio(title, sentences)
    # time.sleep(20)
    # print()
    #
    # # step 3. 分析每一句诗词，每一句对应一个镜头场景
    # print("step 3. 开始分析每一句诗词，每一句对应一个镜头场景...")
    # generate_lens(title, sentences)
    # print()
    #
    # # step 4. 根据镜头场景生成视频
    # print("step 4. 开始根据镜头场景生成视频...")
    # generate_videos(title, sentences)
    # print()
    #
    # # step 5. 拼接视频、音频和字幕
    # print("step 5. 开始拼接视频、音频和字幕...")
    # generate_final_video(title, sentences)