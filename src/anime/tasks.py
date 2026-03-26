from celery import shared_task

from anime.services.episode_source_service import EpisodeSourceService


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def crawl_episode_sources_task(self, episode_id: str) -> dict:
    service = EpisodeSourceService()
    return service.capture_sources_for_task(episode_id=episode_id)
