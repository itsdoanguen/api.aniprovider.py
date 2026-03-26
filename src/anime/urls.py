from django.urls import path

from anime.views import AnimeEpisodesView

urlpatterns = [
    path("animes/<str:anime_id>/episodes", AnimeEpisodesView.as_view(), name="anime-episodes"),
]
