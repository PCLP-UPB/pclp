from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("saptamana/", views.week_redirect, name="week_current"),
    path("saptamana/<int:n>/", views.week, name="week"),
    path("probleme/", views.problems, name="problems"),
    path("problema/<str:pid>/", views.problem, name="problem"),
    path("problema/<str:pid>/incepe/", views.problem_start, name="problem_start"),
    path("problema/<str:pid>/teste/", views.problem_tests, name="problem_tests"),
    path("problema/<str:pid>/indiciu/", views.problem_hint, name="problem_hint"),
    path("problema/<str:pid>/stare/", views.problem_status, name="problem_status"),
    path("problema/<str:pid>/tutore/", views.problem_tutor, name="problem_tutor"),
    path("prompturi/", views.prompts, name="prompts"),
    path("prompturi/extern/", views.prompt_external, name="prompt_external"),
    path("intrebari/", views.quiz_config, name="quiz"),
    path("intrebari/<int:qid>/", views.quiz_play, name="quiz_play"),
    path("progres/", views.progress, name="progress"),
    path("setari/", views.ai_settings, name="settings"),
    path("despre/", views.about, name="about"),
    path("actualizare/", views.content_update, name="content_update"),
    path("actualizare/ok/", views.content_notice_ok, name="content_notice_ok"),
]
