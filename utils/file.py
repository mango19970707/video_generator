import os

import requests


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