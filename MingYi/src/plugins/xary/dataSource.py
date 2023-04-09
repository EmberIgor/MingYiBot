import json

import requests
from nonebot import get_driver

headers = {
    "authority": "firekeeper.top",
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "authorization": get_driver().config.nanocore_authorization,
    "dnt": "1",
    "referer": "https://firekeeper.top/adminUser",
}


def get_subscription_link(user_id: str):
    subscription_link = None
    try:
        subscription_links = requests.get("https://firekeeper.top/api/v1/adminUser/user/fetch?pageSize=10&current=1",
                                          headers=headers).json()
    except requests.exceptions.SSLError:
        return {"status": "error", "message": "无法连接到订阅链接服务器。"}
    for subscription_link_json in subscription_links["data"]:
        try:
            remarks = json.loads(subscription_link_json["remarks"])
            if remarks["qq"] == str(user_id):
                subscription_link = subscription_link_json["subscribe_url"]
                break
        except json.decoder.JSONDecodeError:
            continue
        except TypeError:
            continue
    return {"status": "success", "subscription_link": subscription_link}


def apply_subscription_link(user_id: str, nickname: str):
    subscription_link = get_subscription_link(user_id)
    if subscription_link["status"] == "error":
        return {"status": "error", "message": subscription_link["message"]}
    if subscription_link["subscription_link"] is not None:
        return {"status": "error", "message": "您已经申请过订阅链接。"}
    try:
        apply_sublink = requests.post("https://firekeeper.top/api/v1/adminUser/user/generate",
                                      headers=headers,
                                      data={"email_suffix": "firekeeper.top",
                                            "email_prefix": f"{nickname}",
                                            "plan_id": "1"
                                            }
                                      ).json()
        if apply_sublink["data"] == "true" or apply_sublink["data"] is True:
            subscription_info_list = requests.get(
                "https://firekeeper.top/api/v1/adminUser/user/fetch?pageSize=150&current=1",
                headers=headers).json()
            subscription_info = {}
            for subscription_info_json in subscription_info_list["data"]:
                if subscription_info_json["email"] == f"{nickname}@firekeeper.top":
                    subscription_info = subscription_info_json
                    break
            if subscription_info == {}:
                return {"status": "error", "message": "申请订阅链接失败。"}
            subscription_info["remarks"] = "{" + f'"qq": "{user_id}"' + "}"
            update_result = requests.post("https://firekeeper.top/api/v1/adminUser/user/update", headers=headers,
                                          data=subscription_info).json()
            if update_result["data"] == "true" or update_result["data"] is True:
                return {"status": "success", "message": "申请订阅链接成功。",
                        "subscription_link": subscription_info["subscribe_url"]}
            else:
                return {"status": "error", "message": "申请订阅链接失败。"}
        else:
            return {"status": "error", "message": "申请订阅链接失败。"}
    except requests.exceptions.SSLError:
        return {"status": "error", "message": "无法连接到订阅链接服务器。"}
