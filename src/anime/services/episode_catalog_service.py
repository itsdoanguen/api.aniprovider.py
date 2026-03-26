from datetime import timedelta
import logging
import re
import time
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from anime.models import Anime, Episode
from core.exceptions import AniProviderException, UpstreamServiceException, UpstreamTimeoutException
from core.error_codes import ErrorCode
from crawler.parsers.episode_html_parser import extract_anime_numeric_id, parse_episodes_from_watch_html

logger = logging.getLogger(__name__)


class AnimeNotFoundException(AniProviderException):
    status_code = 404
    default_code = ErrorCode.ANIME_NOT_FOUND
    default_detail = "Anime not found"


class EpisodeCatalogService:
    def __init__(self) -> None:
        self.base_url = getattr(settings, "ANIPROVIDER_UPSTREAM_BASE_URL", "https://9animetv.to").rstrip("/")
        self.request_timeout = int(getattr(settings, "ANIPROVIDER_UPSTREAM_TIMEOUT_SECONDS", 20))
        self.retry_count = int(getattr(settings, "ANIPROVIDER_UPSTREAM_RETRY_COUNT", 2))
        self.cache_ttl_seconds = int(getattr(settings, "ANIPROVIDER_EPISODE_TTL_SECONDS", 600))
        self.http_session = requests.Session()

    def list_episodes(self, anime_id: str, refresh: bool = False) -> dict:
        if not refresh:
            cached = self._load_from_cache(anime_id)
            if cached is not None:
                return {
                    "anime_id": anime_id,
                    "total": len(cached),
                    "items": cached,
                    "meta": {"refreshed": False, "source": "mysql_cache"},
                }

        crawled = self._crawl_episode_list(anime_id)
        persisted = self._upsert(anime_id=anime_id, crawled_items=crawled)
        return {
            "anime_id": anime_id,
            "total": len(persisted),
            "items": persisted,
            "meta": {"refreshed": True, "source": "live_crawl"},
        }

    def _load_from_cache(self, anime_id: str) -> list[dict] | None:
        now = timezone.now()
        anime = Anime.objects.filter(anime_id=anime_id, expires_at__gt=now).first()
        if not anime:
            return None

        episodes = list(
            Episode.objects.filter(anime=anime, expires_at__gt=now)
            .order_by("order")
            .values("data_id", "order", "title", "episode_url")
        )
        if not episodes:
            return None

        return [
            {
                "episode_id": row["data_id"],
                "order": row["order"],
                "title": row["title"],
                "episode_url": row["episode_url"],
            }
            for row in episodes
        ]

    def _crawl_episode_list(self, anime_id: str) -> list[dict]:
        candidates = self._build_anime_id_candidates(anime_id)
        crawl_errors: list[dict] = []

        for candidate in candidates:
            logger.info("crawl_episodes_start anime_id=%s candidate=%s", anime_id, candidate)
            try:
                episodes = self._crawl_episode_list_for_candidate(candidate)
            except requests.Timeout as exc:
                raise UpstreamTimeoutException(
                    "Cannot fetch anime episodes in time",
                    details={"anime_id": anime_id, "candidate": candidate},
                ) from exc
            except requests.RequestException as exc:
                raise UpstreamServiceException(
                    "Cannot connect upstream source",
                    details={"anime_id": anime_id, "candidate": candidate},
                ) from exc
            except UpstreamServiceException:
                raise

            if episodes:
                logger.info(
                    "crawl_episodes_success anime_id=%s candidate=%s total=%s",
                    anime_id,
                    candidate,
                    len(episodes),
                )
                return episodes

            crawl_errors.append({"candidate": candidate, "reason": "no_episodes"})

        raise AnimeNotFoundException(
            f"No episodes found for anime '{anime_id}'",
            details={"anime_id": anime_id, "tried_candidates": candidates, "attempts": crawl_errors},
        )

    def _crawl_episode_list_for_candidate(self, anime_id: str) -> list[dict]:
        watch_url = f"{self.base_url}/watch/{anime_id}"
        response = self._http_get(watch_url, headers=self._build_headers(referer_url=self.base_url))

        if response.status_code == 404:
            logger.info("crawl_episodes_404 anime_id=%s watch_url=%s", anime_id, watch_url)
            return []

        if response.status_code >= 400:
            raise UpstreamServiceException(
                f"Upstream status code: {response.status_code}",
                details={"anime_id": anime_id, "status_code": response.status_code},
            )

        logger.info(
            "crawl_episodes_watch_ok anime_id=%s status=%s content_length=%s",
            anime_id,
            response.status_code,
            len(response.text or ""),
        )

        episodes = parse_episodes_from_watch_html(base_url=self.base_url, raw_html=response.text)
        if episodes:
            return episodes

        return self._fetch_episodes_via_ajax(watch_url=watch_url, watch_html=response.text)

    def _fetch_episodes_via_ajax(self, watch_url: str, watch_html: str) -> list[dict]:
        anime_numeric_id = extract_anime_numeric_id(watch_html)
        if not anime_numeric_id:
            return []

        ajax_url = urljoin(watch_url, f"/ajax/episode/list/{anime_numeric_id}")
        response = self._http_get(
            ajax_url,
            headers=self._build_headers(referer_url=watch_url, is_ajax=True),
        )

        if response.status_code >= 400:
            logger.warning(
                "crawl_episodes_ajax_bad_status ajax_url=%s status=%s",
                ajax_url,
                response.status_code,
            )
            return []

        try:
            payload = response.json()
        except ValueError:
            logger.warning("crawl_episodes_ajax_invalid_json ajax_url=%s", ajax_url)
            return []

        if not payload.get("status"):
            return []

        html_payload = payload.get("html", "")
        if not html_payload:
            return []

        episodes = parse_episodes_from_watch_html(base_url=self.base_url, raw_html=html_payload)
        logger.info("crawl_episodes_ajax_result total=%s", len(episodes))
        return episodes

    def _build_anime_id_candidates(self, anime_id: str) -> list[str]:
        normalized = re.sub(r"-\d+$", "", anime_id.strip())
        if normalized and normalized != anime_id:
            return [anime_id, normalized]
        return [anime_id]

    def _build_headers(self, referer_url: str, is_ajax: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer_url,
        }
        if is_ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        return headers

    def _http_get(self, url: str, headers: dict | None = None, params: dict | None = None) -> requests.Response:
        attempts = self.retry_count + 1
        last_exc: Exception | None = None
        retryable_statuses = {429, 500, 502, 503, 504}

        for attempt in range(1, attempts + 1):
            try:
                response = self.http_session.get(url, headers=headers, params=params, timeout=self.request_timeout)
                if response.status_code in retryable_statuses and attempt < attempts:
                    time.sleep(0.3 * (2 ** (attempt - 1)))
                    continue
                return response
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

    @transaction.atomic
    def _upsert(self, anime_id: str, crawled_items: list[dict]) -> list[dict]:
        now = timezone.now()
        expires_at = now + timedelta(seconds=self.cache_ttl_seconds)

        anime, _ = Anime.objects.update_or_create(
            anime_id=anime_id,
            defaults={
                "title": anime_id,
                "last_fetched_at": now,
                "expires_at": expires_at,
                "cached_episodes_count": len(crawled_items),
            },
        )

        crawled_data_ids = {item["data_id"] for item in crawled_items}

        for item in crawled_items:
            Episode.objects.update_or_create(
                data_id=item["data_id"],
                defaults={
                    "anime": anime,
                    "title": item["title"],
                    "order": item["order"],
                    "episode_url": item["episode_url"],
                    "data_number": item["data_number"],
                    "ep_query": item["ep_query"],
                    "last_fetched_at": now,
                    "expires_at": expires_at,
                },
            )

        Episode.objects.filter(anime=anime).exclude(data_id__in=crawled_data_ids).delete()

        episodes = list(
            Episode.objects.filter(anime=anime).order_by("order").values("data_id", "order", "title", "episode_url")
        )
        return [
            {
                "episode_id": row["data_id"],
                "order": row["order"],
                "title": row["title"],
                "episode_url": row["episode_url"],
            }
            for row in episodes
        ]
