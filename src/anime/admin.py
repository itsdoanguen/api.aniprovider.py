from django.contrib import admin

from anime.models import Anime, Episode, EpisodeSource


@admin.register(Anime)
class AnimeAdmin(admin.ModelAdmin):
    list_display = ("id", "anime_id", "numeric_id", "cached_episodes_count", "expires_at")
    search_fields = ("anime_id", "numeric_id", "title")


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("id", "anime", "data_id", "order", "expires_at")
    search_fields = ("data_id", "title")
    list_filter = ("anime",)


@admin.register(EpisodeSource)
class EpisodeSourceAdmin(admin.ModelAdmin):
    list_display = ("id", "episode", "source_type", "response_status", "expires_at")
    search_fields = ("source_url",)
    list_filter = ("source_type",)
