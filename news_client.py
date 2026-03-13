from __future__ import annotations

import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass


SSL_CONTEXT = ssl.create_default_context()


@dataclass
class NewsHeadline:
    title: str
    source: str
    link: str


def fetch_google_news(query: str, limit: int = 5) -> list[NewsHeadline]:
    encoded_query = urllib.parse.quote(query)
    url = (
        "https://news.google.com/rss/search"
        f"?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    )
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "user-agent": "stock-bithumb-assistant/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=8, context=SSL_CONTEXT) as response:
        xml_payload = response.read()

    root = ET.fromstring(xml_payload)
    items = root.findall("./channel/item")
    headlines: list[NewsHeadline] = []

    for item in items[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "Google News").strip()
        if title:
            headlines.append(NewsHeadline(title=title, source=source, link=link))
    return headlines
