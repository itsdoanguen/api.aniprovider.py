import html
import re
from urllib.parse import parse_qs, urljoin, urlparse

BEGIN_EPS = "<!--Begin: Section eps-list-->"
END_EPS = "<!--End: Section eps-list-->"

ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<inner>.*?)</a>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
WRAPPER_ID_RE = re.compile(r"<div\s+id=[\"']wrapper[\"'][^>]*\bdata-id=[\"'](\d+)[\"']", re.IGNORECASE)
ORDER_RE = re.compile(r"<div\s+class=[\"']order[\"']>\s*(\d+)\s*</div>", re.IGNORECASE)


def extract_eps_list_section(raw_html: str) -> str:
    start = raw_html.find(BEGIN_EPS)
    if start == -1:
        return raw_html

    start += len(BEGIN_EPS)
    end = raw_html.find(END_EPS, start)
    if end == -1:
        next_begin = raw_html.find("<!--Begin:", start)
        end = next_begin if next_begin != -1 else len(raw_html)

    return raw_html[start:end]


def extract_anime_numeric_id(raw_html: str) -> str | None:
    match = WRAPPER_ID_RE.search(raw_html)
    return match.group(1) if match else None


def parse_episodes_from_watch_html(base_url: str, raw_html: str) -> list[dict]:
    section_html = extract_eps_list_section(raw_html)
    episodes = _parse_episodes(base_url=base_url, html_blob=section_html)

    if episodes or section_html == raw_html:
        episodes.sort(key=lambda item: (item["order"] if item["order"] > 0 else 10**9, item["data_id"]))
        return episodes

    fallback_episodes = _parse_episodes(base_url=base_url, html_blob=raw_html)
    fallback_episodes.sort(key=lambda item: (item["order"] if item["order"] > 0 else 10**9, item["data_id"]))
    return fallback_episodes


def _parse_episodes(base_url: str, html_blob: str) -> list[dict]:
    episodes: list[dict] = []
    seen_data_ids: set[str] = set()

    for match in ANCHOR_RE.finditer(html_blob):
        attrs_blob = match.group("attrs")
        inner_html = match.group("inner")
        attrs = {name.lower(): html.unescape(value) for name, _, value in ATTR_RE.findall(attrs_blob)}
        class_name = attrs.get("class", "")
        if "ep-item" not in class_name:
            continue

        href = attrs.get("href", "")
        if not href:
            continue

        data_id = attrs.get("data-id", "")
        data_number = attrs.get("data-number", "")
        title = attrs.get("title", "").strip()

        episode_url = urljoin(base_url, href)

        parsed = urlparse(episode_url)
        ep_query = parse_qs(parsed.query).get("ep", [""])[0]
        order = _extract_order(inner_html=inner_html, data_number=data_number, ep_query=ep_query)

        if data_id and data_id in seen_data_ids:
            continue
        if data_id:
            seen_data_ids.add(data_id)

        if not data_id:
            data_id = ep_query or href

        episodes.append(
            {
                "data_id": data_id,
                "order": order,
                "title": title or f"Episode {order or '?'}",
                "episode_url": episode_url,
                "data_number": data_number,
                "ep_query": ep_query,
            }
        )

    return episodes


def _extract_order(inner_html: str, data_number: str, ep_query: str) -> int:
    order_match = ORDER_RE.search(inner_html or "")
    if order_match:
        return _safe_int(order_match.group(1))

    order = _safe_int(data_number)
    if order > 0:
        return order

    return _safe_int(ep_query)


def _safe_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
