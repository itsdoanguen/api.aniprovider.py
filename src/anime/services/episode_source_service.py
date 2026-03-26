from datetime import timedelta, timezone as dt_timezone
import re
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from anime.models import Episode, EpisodeSource
from core.error_codes import ErrorCode
from core.exceptions import AniProviderException, UpstreamServiceException, UpstreamTimeoutException
from crawler.parsers.source_payload_parser import extract_sources

SERVER_ID_RE = re.compile(r'data-id="([^\"]+)"', re.IGNORECASE)
EMBED_ID_RE = re.compile(r"/embed-2/v2/e-1/([^/?#]+)")


class EpisodeNotFoundException(AniProviderException):
    status_code = 404
    default_code = ErrorCode.EPISODE_NOT_FOUND
    default_detail = "Episode not found"


class CaptureFailedException(AniProviderException):
    status_code = 502
    default_code = ErrorCode.CAPTURE_FAILED
    default_detail = "Capture failed"


class EpisodeSourceService:
    def __init__(self) -> None:
        self.base_url = getattr(settings, "ANIPROVIDER_UPSTREAM_BASE_URL", "https://9animetv.to").rstrip("/")
        self.request_timeout = int(getattr(settings, "ANIPROVIDER_UPSTREAM_TIMEOUT_SECONDS", 20))
        self.cache_ttl_seconds = int(getattr(settings, "ANIPROVIDER_SOURCE_TTL_SECONDS", 600))

    def get_sources(self, episode_id: str, refresh: bool = False) -> dict:
        episode = Episode.objects.filter(data_id=episode_id).first()
        if not episode:
            raise EpisodeNotFoundException(
                detail=f"Episode '{episode_id}' not found",
                details={"episode_id": episode_id},
            )

        if not refresh:
            cached = self._load_from_cache(episode)
            if cached is not None:
                return {
                    "episode_id": episode_id,
                    "stream_links": cached["stream_links"],
                    "vtt_links": cached["vtt_links"],
                    "captured_at": cached["captured_at"],
                    "meta": {"refreshed": False, "source": "mysql_cache"},
                }

        source_urls = self._discover_source_urls(episode)
        aggregate = self._capture_and_upsert(episode=episode, source_urls=source_urls)
        return {
            "episode_id": episode_id,
            "stream_links": aggregate["stream_links"],
            "vtt_links": aggregate["vtt_links"],
            "captured_at": aggregate["captured_at"],
            "meta": {"refreshed": True, "source": "rapidcloud_capture"},
        }

    def _load_from_cache(self, episode: Episode) -> dict | None:
        now = timezone.now()
        rows = list(
            EpisodeSource.objects.filter(episode=episode, expires_at__gt=now, response_status=200)
            .order_by("updated_at")
            .values("response_data", "last_fetched_at")
        )
        if not rows:
            return None

        stream_links: list[str] = []
        vtt_links: list[str] = []
        stream_seen: set[str] = set()
        vtt_seen: set[str] = set()
        captured_at = None

        for row in rows:
            payload = row["response_data"] or {}
            row_streams = payload.get("stream_links", [])
            row_vtts = payload.get("vtt_links", [])

            if not row_streams and isinstance(payload.get("raw_payload"), dict):
                row_streams, row_vtts = extract_sources(payload.get("raw_payload", {}))

            for link in row_streams:
                if link not in stream_seen:
                    stream_seen.add(link)
                    stream_links.append(link)
            for link in row_vtts:
                if link not in vtt_seen:
                    vtt_seen.add(link)
                    vtt_links.append(link)

            last_fetched = row.get("last_fetched_at")
            if last_fetched and (captured_at is None or last_fetched > captured_at):
                captured_at = last_fetched

        if captured_at is None:
            captured_at = now

        return {
            "stream_links": stream_links,
            "vtt_links": vtt_links,
            "captured_at": _isoformat_utc(captured_at),
        }

    def _discover_source_urls(self, episode: Episode) -> list[str]:
        watch_path = urlparse(episode.episode_url).path
        watch_url = f"{self.base_url}{watch_path}" if watch_path.startswith("/") else episode.episode_url

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": watch_url,
            "X-Requested-With": "XMLHttpRequest",
        }

        servers_url = f"{self.base_url}/ajax/episode/servers"
        try:
            servers_response = requests.get(
                servers_url,
                params={"episodeId": episode.data_id},
                headers=headers,
                timeout=self.request_timeout,
            )
        except requests.Timeout as exc:
            raise UpstreamTimeoutException("Cannot fetch server list in time", details={"episode_id": episode.data_id}) from exc
        except requests.RequestException as exc:
            raise UpstreamServiceException("Cannot fetch server list", details={"episode_id": episode.data_id}) from exc

        if servers_response.status_code >= 400:
            raise UpstreamServiceException(
                f"Server list status code: {servers_response.status_code}",
                details={"episode_id": episode.data_id, "status_code": servers_response.status_code},
            )

        try:
            servers_payload = servers_response.json()
        except ValueError as exc:
            raise UpstreamServiceException("Invalid server list response", details={"episode_id": episode.data_id}) from exc

        html_content = str(servers_payload.get("html", ""))
        server_ids = SERVER_ID_RE.findall(html_content)
        if not server_ids:
            raise CaptureFailedException("No streaming servers found", details={"episode_id": episode.data_id})

        source_urls: list[str] = []
        seen: set[str] = set()

        for server_id in server_ids:
            url = self._fetch_getsources_url(server_id=server_id, headers=headers)
            if url and url not in seen:
                source_urls.append(url)
                seen.add(url)

        if not source_urls:
            raise CaptureFailedException("No getSources URLs discovered", details={"episode_id": episode.data_id})

        return source_urls

    def _fetch_getsources_url(self, server_id: str, headers: dict) -> str | None:
        source_url = f"{self.base_url}/ajax/episode/sources"
        try:
            response = requests.get(
                source_url,
                params={"id": server_id},
                headers=headers,
                timeout=self.request_timeout,
            )
        except requests.RequestException:
            return None

        if response.status_code >= 400:
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        link = payload.get("link")
        if not isinstance(link, str):
            data = payload.get("data")
            if isinstance(data, dict):
                link = data.get("link")

        if not isinstance(link, str) or not link:
            return None

        return self._to_getsources_url(link)

    def _to_getsources_url(self, embed_link: str) -> str | None:
        match = EMBED_ID_RE.search(embed_link)
        if not match:
            return None
        source_id = match.group(1)
        return f"https://rapid-cloud.co/embed-2/v2/e-1/getSources?id={source_id}"

    @transaction.atomic
    def _capture_and_upsert(self, episode: Episode, source_urls: list[str]) -> dict:
        now = timezone.now()
        expires_at = now + timedelta(seconds=self.cache_ttl_seconds)

        stream_links: list[str] = []
        vtt_links: list[str] = []
        stream_seen: set[str] = set()
        vtt_seen: set[str] = set()

        for url in source_urls:
            payload = self._fetch_payload(url=url, episode_id=episode.data_id)
            row_streams, row_vtts = extract_sources(payload)

            for link in row_streams:
                if link not in stream_seen:
                    stream_seen.add(link)
                    stream_links.append(link)

            for link in row_vtts:
                if link not in vtt_seen:
                    vtt_seen.add(link)
                    vtt_links.append(link)

            EpisodeSource.objects.update_or_create(
                source_url=url,
                defaults={
                    "episode": episode,
                    "source_type": EpisodeSource.SOURCE_RAPIDCLOUD,
                    "response_status": 200,
                    "response_data": {
                        "raw_payload": payload,
                        "stream_links": row_streams,
                        "vtt_links": row_vtts,
                    },
                    "last_fetched_at": now,
                    "expires_at": expires_at,
                },
            )

        return {
            "stream_links": stream_links,
            "vtt_links": vtt_links,
            "captured_at": _isoformat_utc(now),
        }

    def _fetch_payload(self, url: str, episode_id: str) -> dict:
        try:
            response = requests.get(url, timeout=self.request_timeout)
        except requests.Timeout as exc:
            raise UpstreamTimeoutException("getSources request timeout", details={"episode_id": episode_id, "url": url}) from exc
        except requests.RequestException as exc:
            raise UpstreamServiceException("getSources request failed", details={"episode_id": episode_id, "url": url}) from exc

        if response.status_code >= 400:
            raise UpstreamServiceException(
                f"getSources status code: {response.status_code}",
                details={"episode_id": episode_id, "url": url, "status_code": response.status_code},
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise CaptureFailedException("Invalid getSources payload", details={"episode_id": episode_id, "url": url}) from exc

        if not isinstance(payload, dict):
            raise CaptureFailedException("Unexpected getSources payload type", details={"episode_id": episode_id, "url": url})

        return payload


def _isoformat_utc(value) -> str:
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
