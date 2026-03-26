from django.urls import path

from anime.views import AnimeEpisodesView, EpisodeSourcesView

urlpatterns = [
    path("animes/<str:anime_id>/episodes", AnimeEpisodesView.as_view(), name="anime-episodes"),
    path("episodes/<str:episode_id>/sources", EpisodeSourcesView.as_view(), name="episode-sources"),
]
