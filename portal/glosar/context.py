from django.conf import settings


def pclp(request):
    from . import content as C

    try:
        cw = C.current_week()
        labs = C.labs()
    except Exception:  # baza de conținut lipsește
        cw, labs = 1, []
    notice = None
    try:
        import json
        nf = C.pclp_content.store() / "notice.json"
        if nf.exists():
            notice = json.loads(nf.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        notice = None
    return {
        "CONTENT_NOTICE": notice,
        "AUTHOR": settings.PCLP_AUTHOR,
        "CODE_URL": settings.PCLP_CODE_URL,
        "STATIC_V": settings.STATIC_VERSION,
        "PCLP_VERSION": settings.PCLP_VERSION,
        "CURRENT_WEEK": cw,
        "NAV_LABS": labs,
    }
