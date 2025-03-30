import os
import subprocess
from http import HTTPStatus
from notion_client import Client
import dashscope
from dashscope import AudioRecognition  # 明确导入模块
import spacy

# 初始化中文NLP模型
nlp = spacy.load("zh_core_web_sm")

def get_sample_rate(audio_url):
    """使用FFmpeg检测音频采样率"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'a',
            '-show_entries', 'stream=sample_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_url
        ]
        output = subprocess.check_output(cmd).decode().strip()
        return int(output)
    except Exception as e:
        print(f"采样率检测失败，使用默认16000Hz: {str(e)}")
        return 16000

def transcribe_audio(audio_url):
    """调用DashScope语音转文字"""
    try:
        dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
        sample_rate = get_sample_rate(audio_url)
        print(f"检测到采样率: {sample_rate}Hz")
        
        # 修正后的API调用
        response = AudioRecognition.call(
            model='paraformer-v2',
            audio_url=audio_url,
            sample_rate=sample_rate
        )
        
        if response.status_code == HTTPStatus.OK:
            return response.output['sentences'][0]['text']  # 根据实际响应结构调整
        return f"识别失败: {response.message}"
    except Exception as e:
        return f"处理异常: {str(e)}"

def extract_summary(text):
    """提取摘要"""
    doc = nlp(text)
    keywords = [token.text for token in doc if token.pos_ in ["NOUN", "PROPN"]][:5]
    summary = " ".join([sent.text for sent in doc.sents][:3])
    return {
        "summary": summary,
        "keywords": ", ".join(keywords)
    }

def update_notion(page_id, transcript, summary):
    """更新Notion页面"""
    notion = Client(auth=os.getenv("NOTION_API_KEY"))
    notion.pages.update(
        page_id=page_id,
        properties={
            "Transcript": {"rich_text": [{"text": {"content": transcript}}]},
            "Summary": {"rich_text": [{"text": {"content": summary}}]}
        }
    )

if __name__ == "__main__":
    try:
        # 1. 获取Notion最新录音
        notion = Client(auth=os.getenv("NOTION_API_KEY"))
        db_id = "1c5c37fee47480a3b857fe141c8d1aa9"
        
        # 添加分页查询防止超时
        query_result = notion.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Audio File", "files": {"is_not_empty": True}},
                    {"property": "Transcript", "rich_text": {"is_empty": True}}
                ]
            }
        ).get("results")
        
        if not query_result:
            print("没有待处理的录音文件")
            exit()
            
        new_audio = query_result[0]
        audio_url = new_audio["properties"]["Audio File"]["files"][0]["file"]["url"]
        print(f"开始处理音频: {audio_url}")

        # 2. 处理音频
        transcript = transcribe_audio(audio_url)
        if any(err in transcript for err in ["识别失败", "处理异常"]):
            raise Exception(transcript)
            
        # 3. 更新Notion
        analysis = extract_summary(transcript)
        update_notion(new_audio["id"], transcript, analysis["summary"])
        print("处理完成！")
        
    except Exception as e:
        print(f"运行错误: {str(e)}")
        raise  # 抛出异常以便CI/CD捕获
