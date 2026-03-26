import re

from rest_framework.response import Response
from rest_framework.views import APIView

from anime.services.episode_catalog_service import EpisodeCatalogService
from anime.services.episode_source_service import EpisodeSourceService
from core.exceptions import InvalidInputException

ANIME_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,128}$")
EPISODE_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,128}$")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


class AnimeEpisodesView(APIView):
    service_class = EpisodeCatalogService

    def get(self, request, anime_id: str):
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
    service_class = EpisodeSourceService

    def get(self, request, episode_id: str):
        episode_id = (episode_id or "").strip()
        if not EPISODE_ID_RE.match(episode_id):
            raise InvalidInputException(
                detail="Invalid episode_id",
                details={"episode_id": episode_id},
            )

        refresh = _parse_bool(request.query_params.get("refresh"), default=False)
        service = self.service_class()
        payload = service.get_sources(episode_id=episode_id, refresh=refresh)
        return Response(payload, status=200)
