from django.urls import path

from . import views

urlpatterns = [
    path("exploreaza/", views.explore, name="explore"),
    path("capitol/<str:uid>/", views.chapter, name="chapter"),
    path("carte/<str:uid>/", views.reader, name="reader"),
    path("termen/nou/", views.term_new, name="term_new"),
    path("termen/<str:cid>/", views.term, name="term"),
    path("termen/<str:cid>/editeaza/", views.term_edit, name="term_edit"),
    path("termen/<str:cid>/nivel/", views.term_level, name="term_level"),
    path("termen/<str:cid>/sterge/", views.term_delete, name="term_delete"),
    path("man/", views.man_index, name="man_index"),
    path("man/<str:mid>/", views.man_view, name="man"),
    path("cauta/", views.search, name="search"),
    path("graf/", views.graph, name="graph"),
    path("media/<str:name>", views.media, name="media"),
    path("api/sugestii/", views.api_suggest, name="api_suggest"),
    path("api/termen/<str:cid>/", views.api_term, name="api_term"),
    path("api/panou/<str:cid>/", views.api_panel, name="api_panel"),
    path("api/explica/", views.api_explain, name="api_explain"),
    path("api/graf/", views.api_graph, name="api_graph"),
    path("audit/", views.audit, name="audit"),
]
