from datetime import timedelta
import time

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from anime.models import Anime, Episode
from core.exceptions import AniProviderException, UpstreamServiceException, UpstreamTimeoutException
from core.error_codes import ErrorCode
from crawler.parsers.episode_html_parser import parse_episodes_from_watch_html


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
        watch_url = f"{self.base_url}/watch/{anime_id}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        }

        try:
            response = self._http_get(watch_url, headers=headers)
        except requests.Timeout as exc:
            raise UpstreamTimeoutException(
                "Cannot fetch anime episodes in time",
                details={"anime_id": anime_id},
            ) from exc
        except requests.RequestException as exc:
            raise UpstreamServiceException(
                "Cannot connect upstream source",
                details={"anime_id": anime_id},
            ) from exc

        if response.status_code == 404:
            raise AnimeNotFoundException(f"Anime '{anime_id}' not found", details={"anime_id": anime_id})
        if response.status_code >= 400:
            raise UpstreamServiceException(
                f"Upstream status code: {response.status_code}",
                details={"anime_id": anime_id, "status_code": response.status_code},
            )

        episodes = parse_episodes_from_watch_html(base_url=self.base_url, raw_html=response.text)
        if not episodes:
            raise AnimeNotFoundException(
                f"No episodes found for anime '{anime_id}'",
                details={"anime_id": anime_id},
            )
        return episodes

    def _http_get(self, url: str, headers: dict | None = None, params: dict | None = None) -> requests.Response:
        attempts = self.retry_count + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return requests.get(url, headers=headers, params=params, timeout=self.request_timeout)
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
