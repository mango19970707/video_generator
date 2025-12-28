from ffmpy import FFmpeg
import os
import uuid
import subprocess

file_list = ['登高\风急天高猿啸哀，渚清沙白鸟飞回.mp4', '登高\无边落木萧萧下，不尽长江滚滚来.mp4', 
'登高\万里悲秋常作客，百年多病独登台.mp4', '登高\艰难苦恨繁霜鬓，潦倒新停浊酒杯.mp4']

def merge_videos(input_files, output_file):
    input_args = ""
    for file in input_files:
        input_args += f"-i {file} "
    command = f"ffmpeg {input_args} -filter_complex concat=n={len(input_files)}:v=1:a=1 -f mp4 {output_file}"
    subprocess.run(command, shell=True)

if __name__ == "__main__":
    input_files = file_list  # 输入视频文件列表
    output_file = "new.mp4"  # 输出合并后的视频文件名
    merge_videos(input_files, output_file)
