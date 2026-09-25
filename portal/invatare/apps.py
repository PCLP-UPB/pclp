import logging
import os
import sys
import threading
import time

from django.apps import AppConfig
from django.conf import settings

log = logging.getLogger("pclp.update")


def _loop():
    from glosar import content as C

    time.sleep(20)  # lăsăm portalul să pornească
    while True:
        try:
            res = C.pclp_content.update(settings.PCLP_CONTENT_URL)
            if res.get("status") not in ("la-zi", "dezactivat"):
                log.warning("actualizare conținut: %s", res.get("status"))
        except Exception as e:  # rețea indisponibilă etc. — reîncercăm la următorul ciclu
            log.warning("actualizare conținut eșuată: %s", e)
        time.sleep(max(0.25, settings.PCLP_UPDATE_HOURS) * 3600)


class InvatareConfig(AppConfig):
    name = "invatare"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        if not settings.PCLP_CONTENT_URL:
            return
        if any(a in sys.argv for a in ("migrate", "makemigrations", "check", "shell", "test", "exporta_editari")):
            return
        if os.environ.get("RUN_MAIN") == "false":
            return
        threading.Thread(target=_loop, name="pclp-content-update", daemon=True).start()
