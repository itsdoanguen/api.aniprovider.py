import re

from django.conf import settings
from celery.result import AsyncResult
from rest_framework.response import Response
from rest_framework.views import APIView

from anime.services.episode_catalog_service import EpisodeCatalogService
from anime.services.episode_source_service import EpisodeSourceService
from anime.tasks import crawl_episode_sources_task
from core.exceptions import InvalidInputException, ServiceUnavailableException

ANIME_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,128}$")
EPISODE_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,128}$")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


class AnimeEpisodesView(APIView):
    """
    Retrieve all episodes for a given anime.
    
    Returns a cached list of episodes with episode metadata including URLs and data IDs.
    Cache can be refreshed by passing ?refresh=true query parameter.
    """
    service_class = EpisodeCatalogService

    def get(self, request, anime_id: str):
        """
        Get episodes for anime.
        
        Args:
            anime_id (str): The anime identifier (alphanumeric with hyphens, 1-128 chars)
        
        Query Parameters:
            refresh (bool): Whether to refresh cache (default: false)
        
        Returns:
            - 200: List of episodes with metadata
            - 400: Invalid anime_id format
            - 500: Upstream fetch failed or internal error
        """
        anime_id = (anime_id or "").strip()
        if not ANIME_ID_RE.match(anime_id):
            raise InvalidInputException(
                detail="Invalid anime_id",
                details={"anime_id": anime_id},
            )

        refresh = _parse_bool(request.query_params.get("refresh"), default=False)
        service = self.service_class()
        payload = service.list_episodes(anime_id=anime_id, refresh=refresh)
        return Response(payload, status=200)


class EpisodeSourcesView(APIView):
    """
    Retrieve streaming sources for a given episode.
    
    Supports both synchronous (immediate response) and asynchronous (task-based) modes.
    Async mode returns a task ID for polling status. Cache can be refreshed with ?refresh=true.
    """
    service_class = EpisodeSourceService

    def get(self, request, episode_id: str):
        """
        Get streaming sources for episode.
        
        Args:
            episode_id (str): The episode identifier (alphanumeric with hyphens, 1-128 chars)
        
        Query Parameters:
            async (bool): Whether to use async/Celery mode (default: false)
            refresh (bool): Whether to refresh cache (default: false)
        
        Returns on sync mode:
            - 200: List of streaming sources with stream/vtt links
            - 400: Invalid episode_id or invalid query parameters
            - 500: Upstream fetch failed or internal error
        
        Returns on async mode:
            - 200: Cached sources (if available and not refreshing)
            - 202: Task enqueued, returns task_id for polling
            - 400: Invalid episode_id
            - 503: Cannot enqueue task (Celery/Redis unavailable)
        """
        episode_id = (episode_id or "").strip()
        if not EPISODE_ID_RE.match(episode_id):
            raise InvalidInputException(
                detail="Invalid episode_id",
                details={"episode_id": episode_id},
            )

        refresh = _parse_bool(request.query_params.get("refresh"), default=False)
        async_mode = _parse_bool(request.query_params.get("async"), default=False)
        service = self.service_class()

        if async_mode:
            if not settings.ANIPROVIDER_ENABLE_ASYNC_CRAWL:
                raise ServiceUnavailableException(
                    detail="Async source crawling is disabled",
                    details={"episode_id": episode_id},
                )

            if not refresh:
                cached = service.get_cached_sources(episode_id=episode_id)
                if cached is not None:
                    return Response(cached, status=200)

            try:
                task = crawl_episode_sources_task.delay(episode_id)
            except Exception as exc:
                raise ServiceUnavailableException(
                    detail="Cannot enqueue capture task",
                    details={"episode_id": episode_id},
                ) from exc

            return Response(
                {
                    "episode_id": episode_id,
                    "task_id": task.id,
                    "status": "pending",
                    "meta": {"refreshed": refresh, "source": "celery_queue"},
                },
                status=202,
            )

        payload = service.get_sources(episode_id=episode_id, refresh=refresh)
        return Response(payload, status=200)


class EpisodeSourceTaskStatusView(APIView):
    """
    Poll the status of an async task for retrieving episode sources.
    
    Returns the task status and result/error information when complete.
    """
    def get(self, request, task_id: str):
        """
        Get status of a source capture task.
        
        Args:
            task_id (str): The Celery task ID returned from async request
        
        Returns:
            - 200: Task status with result (if SUCCESS) or error (if FAILURE)
            - 503: Task backend (Redis) unavailable
        """
        if not settings.ANIPROVIDER_ENABLE_ASYNC_CRAWL:
            raise ServiceUnavailableException(
                detail="Task status is unavailable because async crawling is disabled",
                details={"task_id": task_id},
            )

        try:
            task = AsyncResult(task_id)
            state = task.state
        except Exception as exc:
            raise ServiceUnavailableException(
                detail="Task backend unavailable",
                details={"task_id": task_id},
            ) from exc

        payload = {"task_id": task_id, "status": state.lower()}

        if state == "SUCCESS":
            payload["result"] = task.result
        elif state == "FAILURE":
            payload["error"] = str(task.result)

        return Response(payload, status=200)
