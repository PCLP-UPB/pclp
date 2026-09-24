# PCLP — mediu de învățare pentru Programarea Calculatoarelor (C)

Un singur container Docker pentru studenți: VS Code în browser (code-server), toolchain C complet
(gcc, clang, gdb, valgrind, make, cppcheck, clang-format, clangd, pagini man), portalul cursului și o
înregistrare minimă a **procesului** de lucru (snapshot-uri git, comenzi din terminal, ieșirea
compilatoarelor, prompturi AI), predată săptămânal pe Moodle cu un cod de verificare.

## Structura repo-ului

| director | conținut |
|---|---|
| `env/` | `Dockerfile`, `compose.yaml` (dezvoltare), `compose.student.yaml` (pentru studenți), `rootfs/` (entrypoint, supervizor, watcher, wrappere gcc/make/valgrind, configurare bash și code-server, șabloane) |
| `tools/` | `pclp` (CLI-ul studentului: init, status, snap, test, submit, week, ai-install), `pclp-verify` (verificatorul profesorului), `pclp_logs.py` (parsere comune) |
| `portal/` | portalul web Django (rulează în container pe portul 8000) |
| `content/` | pipeline-ul de conținut (`content/pipeline/build.py`) → `content/build/` (materiale, probleme, teste, `course.json`) |
| `sources/` | materialele sursă descărcate (folosite de pipeline) |
| `solutions/` | soluții de referință — doar pentru profesori, **excluse** din imagine |
| `docs/` | `student.md` (ghid studenți), `teacher.md` (build, verificare, limite, GDPR) |

## Pornire rapidă (dezvoltatori)

```sh
docker compose -f env/compose.yaml build
mkdir -p work/dev
PCLP_WORK_DIR=../work/dev docker compose -f env/compose.yaml up -d
# portal: http://localhost:8000   VS Code: http://localhost:8080
# porturi ocupate? PCLP_PORT_PORTAL=18000 PCLP_PORT_VSCODE=18080 ...
docker exec -it -u student pclp bash      # terminal în container
docker compose -f env/compose.yaml logs -f
```

Directorul `work/` (ignorat de git) conține directoarele de lucru de test. Verificarea unei predări:

```sh
python3 tools/pclp-verify work/dev/predari/ --out work/raport
```

Detalii: [docs/teacher.md](docs/teacher.md) · Ghid pentru studenți: [docs/student.md](docs/student.md)
