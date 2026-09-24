from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    # aplicație locală pentru un singur utilizator: servim fișierele statice direct
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.BASE_DIR / "static"}),
    path("", include("invatare.urls")),
    path("", include("glosar.urls")),
]
