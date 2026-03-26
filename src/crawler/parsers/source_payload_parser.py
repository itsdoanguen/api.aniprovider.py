from collections.abc import Iterable


def extract_sources(payload: dict) -> tuple[list[str], list[str]]:
    stream_links = _extract_stream_links(payload.get("sources", []))
    vtt_links = _extract_vtt_links(payload.get("tracks", []))
    return stream_links, vtt_links


def _extract_stream_links(sources: Iterable) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for item in sources or []:
        if not isinstance(item, dict):
            continue
        file_url = item.get("file")
        if isinstance(file_url, str) and file_url and file_url not in seen:
            links.append(file_url)
            seen.add(file_url)

    return links


def _extract_vtt_links(tracks: Iterable) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for item in tracks or []:
        if not isinstance(item, dict):
            continue

        kind = str(item.get("kind", "")).lower()
        if kind and kind != "captions":
            continue

        file_url = item.get("file")
        if isinstance(file_url, str) and file_url.endswith(".vtt") and file_url not in seen:
            links.append(file_url)
            seen.add(file_url)

    return links
