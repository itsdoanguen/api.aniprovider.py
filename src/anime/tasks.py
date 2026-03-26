from celery import shared_task


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def crawl_episode_sources_task(self, episode_id: int) -> dict:
    return {
        "episode_id": episode_id,
        "status": "queued",
        "message": "Crawler implementation will be added in Sprint 2",
    }
