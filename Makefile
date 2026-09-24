# Sarcini uzuale pentru mediul PCLP.
PY ?= .venv/bin/python

.PHONY: help venv content content-full dev image up down check-solutions export-edits

help:
	@echo "make venv             - mediu Python local pentru dezvoltare"
	@echo "make content          - reconstruiește baza de conținut (fără paginile de manual)"
	@echo "make content-full     - reconstruiește tot, inclusiv paginile de manual (într-un container Ubuntu)"
	@echo "make dev              - pornește portalul local pe http://127.0.0.1:8765 (mod autor)"
	@echo "make image            - construiește imaginea Docker a studenților"
	@echo "make up / make down   - pornește / oprește containerul local"
	@echo "make check-solutions  - verifică soluțiile de referință pe toate testele"
	@echo "make export-edits     - scrie editările din portal în fișierele curate"

venv:
	python3.11 -m venv .venv && $(PY) -m pip install -q -r portal/requirements.txt

content:
	$(PY) content/pipeline/build.py --skip-man

content-full:
	docker run --rm -v "$(CURDIR)":/src -w /src ubuntu:24.04 bash -c '\
	  rm -f /etc/dpkg/dpkg.cfg.d/excludes; export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends manpages manpages-dev \
	    manpages-posix manpages-posix-dev mandoc python3 python3-bs4 python3-lxml gcc gdb valgrind make >/dev/null 2>&1; \
	  python3 content/pipeline/extract_man.py --out /tmp/b && rm -rf content/build/man && cp -r /tmp/b/man content/build/'
	$(PY) content/pipeline/build.py --skip-man

dev:
	cd portal && PCLP_AUTHOR=1 PCLP_DEBUG=1 ../$(PY) manage.py migrate --noinput && PCLP_AUTHOR=1 PCLP_DEBUG=1 ../$(PY) manage.py runserver 127.0.0.1:8765

image:
	docker compose -f env/compose.yaml build

up:
	docker compose -f env/compose.yaml up -d

down:
	docker compose -f env/compose.yaml down

check-solutions:
	$(PY) solutions/check_all.py

export-edits:
	cd portal && PCLP_AUTHOR=1 ../$(PY) manage.py exporta_editari
