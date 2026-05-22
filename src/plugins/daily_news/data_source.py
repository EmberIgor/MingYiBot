from urllib.parse import urlencode


class DailyNewsError(RuntimeError):
    pass


def build_daily_news_image_url(api_url: str, encoding: str) -> str:
    if encoding not in {"image", "image-proxy"}:
        raise DailyNewsError("每日新闻图片编码配置无效。")

    separator = "&" if "?" in api_url else "?"
    return f"{api_url}{separator}{urlencode({'encoding': encoding})}"
