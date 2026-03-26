from django.db import models


class Anime(models.Model):
    anime_id = models.CharField(max_length=255, unique=True, db_index=True)
    numeric_id = models.CharField(max_length=64, null=True, blank=True)
    title = models.CharField(max_length=512, blank=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    cached_episodes_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "anime"


class Episode(models.Model):
    anime = models.ForeignKey(Anime, on_delete=models.CASCADE, related_name="episodes")
    data_id = models.CharField(max_length=128, unique=True, db_index=True)
    title = models.CharField(max_length=512, blank=True)
    order = models.IntegerField(default=0)
    episode_url = models.URLField(max_length=1000)
    data_number = models.CharField(max_length=64, blank=True)
    ep_query = models.CharField(max_length=64, blank=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "episode"
        ordering = ["order"]
        indexes = [models.Index(fields=["anime", "order"])]


class EpisodeSource(models.Model):
    SOURCE_RAPIDCLOUD = "rapid-cloud"
    SOURCE_OTHER = "other"

    SOURCE_TYPE_CHOICES = [
        (SOURCE_RAPIDCLOUD, "rapid-cloud"),
        (SOURCE_OTHER, "other"),
    ]

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="sources")
    source_url = models.URLField(max_length=1000, unique=True, db_index=True)
    source_type = models.CharField(max_length=32, choices=SOURCE_TYPE_CHOICES, default=SOURCE_OTHER)
    response_status = models.IntegerField(default=0)
    response_data = models.JSONField(default=dict)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "episode_source"
        indexes = [models.Index(fields=["episode", "source_type"])]
