import os
import re
import requests
import uuid
import http.client
from nonebot import get_driver

voiceList = {
    "默认": "default",
    "愤怒": "angry",
    "平静": "calm",
    "开朗": "cheerful",
    "不满": "disgruntled",
    "惊恐": "fearful",
    "温柔": "gentle",
    "抒情": "lyrical",
    "一般": "general",
    "助理": "assistant",
    "聊天": "chat",
    "客户服务": "customer service",
    "播音": "newscast",
    "悲伤": "sad",
    "严肃": "serious",
    "撒娇": "affectionate",
    "阅读": "reading",
}


def print_voice_list():
    print("语音列表：")
    for key in voiceList:
        print(key)


def get_access_token():
    fetch_token_url = 'https://eastus.api.cognitive.microsoft.com/sts/v1.0/issuetoken'
    headers = {
        'Ocp-Apim-Subscription-Key': get_driver().config.tts_subscription_key
    }
    response = requests.post(fetch_token_url, headers=headers)
    access_token = str(response.text)
    return access_token


def message_to_ssml(message, voice_name="zh-CN-XiaoxiaoNeural", voice_type="default", rate="0%", pitch="0%"):
    message = message_to_unicode(message)
    ssml = f"<voice name='{voice_name}'>" \
           f"<mstts:express-as style='{voice_type}'>" \
           f"<prosody rate='{rate}' pitch='{pitch}'>{message}</prosody>" \
           "</mstts:express-as>" \
           "</voice>"
    return ssml


def get_speech(ssml, waveName=None):
    # 如果子目录Recording不存在则创建
    if not os.path.exists("./src/tools/voiceHandler/Recording"):
        os.makedirs("./src/tools/voiceHandler/Recording")
    waveName = waveName or str(uuid.uuid4()) + ".wav"
    access_token = get_access_token()
    headers = {
        "Content-type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
        "Authorization": "Bearer " + access_token,
        "User-Agent": "TTSForPython"
    }
    body = "<speak xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' " \
           "xmlns:emo='http://www.w3.org/2009/10/emotionml' version='1.0' xml:lang='zh-CN'>" \
           f"{ssml}" \
           "</speak>"
    conn = http.client.HTTPSConnection("eastus.tts.speech.microsoft.com")
    conn.request("POST", "/cognitiveservices/v1", body, headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    with open("./src/tools/voiceHandler/Recording/" + waveName, "wb") as f:
        f.write(data)
    return f"{str(os.path.dirname(os.path.abspath(__file__)))}/Recording/{waveName}"


def message_to_unicode(message):
    text = ''
    for i in message:
        if i == '\n':
            pass
        elif re.match("[^\u4e00-\u9fa5]", i):
            if re.match("[\u3002\uff1b\uff0c\uff1a\u201c\u201d\uff08\uff09\u3001\uff1f\u300a\u300b\u2014\uFF01]", i):
                text += i.encode("unicode_escape").decode('utf-8').replace('\\u', '&#x') + ';'
            else:
                text += i
        else:
            text += i.encode("unicode_escape").decode('utf-8').replace('\\u', '&#x') + ';'
    return text
