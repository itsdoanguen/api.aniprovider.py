from django.urls import path

from anime.views import AnimeEpisodesView, EpisodeSourceTaskStatusView, EpisodeSourcesView

urlpatterns = [
    path("animes/<str:anime_id>/episodes", AnimeEpisodesView.as_view(), name="anime-episodes"),
    path("episodes/<str:episode_id>/sources", EpisodeSourcesView.as_view(), name="episode-sources"),
    path("tasks/<str:task_id>", EpisodeSourceTaskStatusView.as_view(), name="task-status"),
]
