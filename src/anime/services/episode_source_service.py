from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta, timezone as dt_timezone
import logging
import re
import time
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from anime.models import Episode, EpisodeSource
from core.error_codes import ErrorCode
from core.exceptions import AniProviderException, UpstreamServiceException, UpstreamTimeoutException
from crawler.parsers.source_payload_parser import extract_sources

logger = logging.getLogger(__name__)

SERVER_ID_RE = re.compile(r'data-id\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
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
        self.retry_count = int(getattr(settings, "ANIPROVIDER_UPSTREAM_RETRY_COUNT", 2))
        self.cache_ttl_seconds = int(getattr(settings, "ANIPROVIDER_SOURCE_TTL_SECONDS", 600))
        self.max_parallel_fetch = int(getattr(settings, "ANIPROVIDER_SOURCE_FETCH_MAX_WORKERS", "4"))

        self.http_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self.http_session.mount("http://", adapter)
        self.http_session.mount("https://", adapter)

    def get_sources(self, episode_id: str, refresh: bool = False) -> dict:
        started_at = time.perf_counter()
        episode = self._get_episode_or_raise(episode_id)

        if not refresh:
            cached = self._load_from_cache(episode)
            if cached is not None:
                logger.info(
                    "sources_request_complete episode_id=%s refreshed=%s source=%s duration_ms=%s",
                    episode_id,
                    False,
                    "mysql_cache",
                    int((time.perf_counter() - started_at) * 1000),
                )
                return {
                    "episode_id": episode_id,
                    "stream_links": cached["stream_links"],
                    "vtt_links": cached["vtt_links"],
                    "captured_at": cached["captured_at"],
                    "meta": {"refreshed": False, "source": "mysql_cache"},
                }

        source_urls = self._discover_source_urls(episode)
        aggregate = self._capture_and_upsert(episode=episode, source_urls=source_urls)
        logger.info(
            "sources_request_complete episode_id=%s refreshed=%s source=%s duration_ms=%s discovered_urls=%s stream_links=%s vtt_links=%s",
            episode_id,
            True,
            "rapidcloud_capture",
            int((time.perf_counter() - started_at) * 1000),
            len(source_urls),
            len(aggregate["stream_links"]),
            len(aggregate["vtt_links"]),
        )
        return {
            "episode_id": episode_id,
            "stream_links": aggregate["stream_links"],
            "vtt_links": aggregate["vtt_links"],
            "captured_at": aggregate["captured_at"],
            "meta": {"refreshed": True, "source": "rapidcloud_capture"},
        }

    def get_cached_sources(self, episode_id: str) -> dict | None:
        episode = self._get_episode_or_raise(episode_id)
        cached = self._load_from_cache(episode)
        if cached is None:
            return None
        return {
            "episode_id": episode_id,
            "stream_links": cached["stream_links"],
            "vtt_links": cached["vtt_links"],
            "captured_at": cached["captured_at"],
            "meta": {"refreshed": False, "source": "mysql_cache"},
        }

    def capture_sources_for_task(self, episode_id: str) -> dict:
        episode = self._get_episode_or_raise(episode_id)
        source_urls = self._discover_source_urls(episode)
        aggregate = self._capture_and_upsert(episode=episode, source_urls=source_urls)
        return {
            "episode_id": episode_id,
            "stream_links": aggregate["stream_links"],
            "vtt_links": aggregate["vtt_links"],
            "captured_at": aggregate["captured_at"],
            "meta": {"refreshed": True, "source": "rapidcloud_capture_async"},
        }

    def _get_episode_or_raise(self, episode_id: str) -> Episode:
        episode = Episode.objects.filter(data_id=episode_id).first()
        if not episode:
            raise EpisodeNotFoundException(
                detail=f"Episode '{episode_id}' not found",
                details={"episode_id": episode_id},
            )
        return episode

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
        started_at = time.perf_counter()
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
            servers_response = self._http_get(
                servers_url,
                headers=headers,
                params={"episodeId": episode.data_id},
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

        logger.info(
            "sources_discovery_complete episode_id=%s server_ids=%s source_urls=%s duration_ms=%s",
            episode.data_id,
            len(server_ids),
            len(source_urls),
            int((time.perf_counter() - started_at) * 1000),
        )

        return source_urls

    def _fetch_getsources_url(self, server_id: str, headers: dict) -> str | None:
        source_url = f"{self.base_url}/ajax/episode/sources"
        attempts = 2

        for attempt in range(1, attempts + 1):
            try:
                response = self._http_get(
                    source_url,
                    headers=headers,
                    params={"id": server_id},
                )
            except requests.RequestException:
                if attempt < attempts:
                    time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

            if response.status_code >= 400:
                if attempt < attempts:
                    time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

            try:
                payload = response.json()
            except ValueError:
                if attempt < attempts:
                    time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

            link = payload.get("link")
            if not isinstance(link, str):
                data = payload.get("data")
                if isinstance(data, dict):
                    link = data.get("link")

            if isinstance(link, str) and link:
                return self._to_getsources_url(link)

        logger.info("sources_discovery_skip_server server_id=%s", server_id)
        return None

    def _to_getsources_url(self, embed_link: str) -> str | None:
        match = EMBED_ID_RE.search(embed_link)
        if not match:
            return None
        source_id = match.group(1)
        return f"https://rapid-cloud.co/embed-2/v2/e-1/getSources?id={source_id}"

    @transaction.atomic
    def _capture_and_upsert(self, episode: Episode, source_urls: list[str]) -> dict:
        started_at = time.perf_counter()
        now = timezone.now()
        expires_at = now + timedelta(seconds=self.cache_ttl_seconds)

        stream_links: list[str] = []
        vtt_links: list[str] = []
        stream_seen: set[str] = set()
        vtt_seen: set[str] = set()

        fetched_rows: list[dict] = []

        workers = min(max(1, self.max_parallel_fetch), max(1, len(source_urls)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(self._fetch_payload, url, episode.data_id): url
                for url in source_urls
            }

            for future in as_completed(future_map):
                url = future_map[future]
                payload = future.result()
                row_streams, row_vtts = extract_sources(payload)
                fetched_rows.append(
                    {
                        "url": url,
                        "payload": payload,
                        "stream_links": row_streams,
                        "vtt_links": row_vtts,
                    }
                )

        for row in fetched_rows:
            row_streams = row["stream_links"]
            row_vtts = row["vtt_links"]

            for link in row_streams:
                if link not in stream_seen:
                    stream_seen.add(link)
                    stream_links.append(link)

            for link in row_vtts:
                if link not in vtt_seen:
                    vtt_seen.add(link)
                    vtt_links.append(link)

            EpisodeSource.objects.update_or_create(
                source_url=row["url"],
                defaults={
                    "episode": episode,
                    "source_type": EpisodeSource.SOURCE_RAPIDCLOUD,
                    "response_status": 200,
                    "response_data": {
                        "raw_payload": row["payload"],
                        "stream_links": row_streams,
                        "vtt_links": row_vtts,
                    },
                    "last_fetched_at": now,
                    "expires_at": expires_at,
                },
            )

        logger.info(
            "sources_capture_complete episode_id=%s source_urls=%s workers=%s stored_rows=%s duration_ms=%s",
            episode.data_id,
            len(source_urls),
            workers,
            len(fetched_rows),
            int((time.perf_counter() - started_at) * 1000),
        )

        return {
            "stream_links": stream_links,
            "vtt_links": vtt_links,
            "captured_at": _isoformat_utc(now),
        }

    def _fetch_payload(self, url: str, episode_id: str) -> dict:
        try:
            response = self._http_get(url)
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

    def _http_get(self, url: str, headers: dict | None = None, params: dict | None = None) -> requests.Response:
        attempts = self.retry_count + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return self.http_session.get(url, headers=headers, params=params, timeout=self.request_timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt == attempts:
                    raise
                time.sleep(0.3 * (2 ** (attempt - 1)))
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == attempts:
                    raise
                time.sleep(0.2)

        if last_exc:
            raise last_exc
        raise requests.RequestException("Unknown request failure")


def _isoformat_utc(value) -> str:
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
