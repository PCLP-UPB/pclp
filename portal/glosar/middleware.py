from . import content as C


class ContentVersionMiddleware:
    """Trece pe versiunea nouă de conținut imediat ce updater-ul a activat-o (în orice worker)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        C.ensure_current()
        return self.get_response(request)
