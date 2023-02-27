import requests
import http.client
import wave
import re
from nonebot import get_driver

subscription_key = get_driver().config.tts_subscription_key
voiceList = {"愤怒": "angry",
             "镇静": "calm",
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
             "严肃": "serious"
             }


def get_token(subscription_key_value):
    fetch_token_url = 'https://eastus.api.cognitive.microsoft.com/sts/v1.0/issuetoken'
    headers = {
        'Ocp-Apim-Subscription-Key': subscription_key_value
    }
    response = requests.post(fetch_token_url, headers=headers)
    access_token = str(response.text)
    return access_token


def get_speech(access_token, text, waveName, voice_type):
    headers = {"Content-type": "application/ssml+xml",
               "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
               "Authorization": "Bearer " + access_token,
               "User-Agent": "TTSForPython"}
    body = "<speak xmlns='http://www.w3.org/2001/10/synthesis' " \
           "xmlns:mstts='http://www.w3.org/2001/mstts' " \
           "xmlns:emo='http://www.w3.org/2009/10/emotionml' " \
           "version='1.0' " \
           "xml:lang='en-US'>" \
           "<voice name='zh-CN-XiaoxiaoNeural'>" \
           f"<mstts:express-as style='{voice_type}'>" \
           f"<prosody rate='0%' pitch='0%'>{text}</prosody>" \
           "</mstts:express-as></voice></speak>"
    conn = http.client.HTTPSConnection("eastus.tts.speech.microsoft.com")
    conn.request("POST", "/cognitiveservices/v1", body, headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    f = wave.open("./src/plugins/Yu-Ying/" + waveName, "wb")
    f.setnchannels(1)  # 单声道
    f.setframerate(24000)  # 采样率
    f.setsampwidth(2)  # sample width 2 bytes(16 bits)
    f.writeframes(data)
    f.close()


async def get_YuYing(test, wave_name, typeOfVoice):
    global subscription_key
    text = ''
    for i in test:
        if i == '\n':
            pass
        elif re.match("[^\u4e00-\u9fa5]", i):
            if re.match("[\u3002\uff1b\uff0c\uff1a\u201c\u201d\uff08\uff09\u3001\uff1f\u300a\u300b\u2014\uFF01]", i):
                text += i.encode("unicode_escape").decode('utf-8').replace('\\u', '&#x') + ';'
            else:
                text += i
        else:
            text += i.encode("unicode_escape").decode('utf-8').replace('\\u', '&#x') + ';'
    access_token = get_token(subscription_key)
    get_speech(access_token, text, wave_name, typeOfVoice)
