# Mediul PCLP — ghid pentru profesori

## Pe scurt

- **Studenții** primesc linkul la [ghidul pentru studenți](student.md). Imaginea publică este
  `ghcr.io/pclp-upb/pclp-env:latest` (amd64 + arm64), reconstruită automat la fiecare push pe `main`.
- **Săptămânal**, după termenul de predare, descărcați de pe Moodle toate predările temei
  („Download all submissions”, un `.zip`) și rulați, dintr-o clonă a acestui repo (Python ≥ 3.10):

  ```bash
  python3 tools/pclp-verify predari-saptamana-5.zip --out raport-s5     # integritate + cronologii HTML
  python3 tools/pclp-grade  predari-saptamana-5.zip --csv note-s5.csv   # punctaj după timpul activ (4 h = 100%)
  ```

  Deschideți `raport-s5/index.html`; pentru fiecare student există o cronologie (cod, comenzi,
  compilări, teste, prompturi AI). Detalii: secțiunile 4 și 9.
- **Materialele** (laboratoare, concepte, probleme, indicii) se modifică în acest repo prin pull request;
  soluțiile de referință stau în repo-ul privat `PCLP-UPB/pclp-solutions`. Detalii: secțiunea 8.
- **Actualizarea la studenți e automată:** după merge pe `main`, workflow-ul `content` publică un pachet
  nou de materiale (≈11 MB), iar portalul din containerul fiecărui student îl descarcă singur în câteva ore
  (sau imediat, cu „Verifică acum” din pagina Despre ori `pclp update`). Detalii: secțiunea 10.


## 1. Construirea și publicarea imaginii

Imaginea se construiește din rădăcina repo-ului (contextul include `portal/`, `content/`, `tools/`,
`sources/`; soluțiile de referință stau în repo-ul privat `PCLP-UPB/pclp-solutions` și nu ajung niciodată în imagine).

Local (arhitectura mașinii curente):

```sh
docker compose -f env/compose.yaml build
PCLP_WORK_DIR=../work/test docker compose -f env/compose.yaml up -d
```

Multi-arch (amd64 + arm64) și publicare, de ex. pe GHCR:

```sh
echo $GITHUB_TOKEN | docker login ghcr.io -u <utilizator> --password-stdin
docker buildx create --use --name pclp-builder     # o singură dată
docker buildx build --platform linux/amd64,linux/arm64 \
  -f env/Dockerfile \
  --build-arg PCLP_VERSION=2026.10.1 --build-arg PCLP_STRICT_CONTENT=1 \
  -t ghcr.io/<org>/pclp-env:2026.10.1 -t ghcr.io/<org>/pclp-env:latest \
  --push .
```

(Docker Hub: `-t <user>/pclp-env:...`.) Faceți pachetul GHCR **public**, ca studenții să îl poată
descărca fără autentificare. Construirea arm64 pe o mașină amd64 folosește emulare QEMU și durează
(compilarea nu e necesară, dar `apt` și `pip` rulează emulat); pe un Mac Apple Silicon e invers.

Argumente de build:

| argument | implicit | rol |
|---|---|---|
| `PCLP_VERSION` | `dev` | apare în manifestul fiecărei predări (`pclp_version`) |
| `CODE_SERVER_VERSION` | `4.138.0` | versiunea code-server |
| `NODE_MAJOR` | `22` | Node.js (pentru CLI-urile AI instalate de studenți) |
| `PCLP_STRICT_CONTENT` | `0` | `1` = build-ul eșuează dacă pipeline-ul de conținut eșuează (folosiți `1` la release) |

Studenților le dați **`env/compose.student.yaml`** (redenumit `compose.yaml`), după ce înlocuiți
`ghcr.io/pclp-upb/pclp-env:latest` (imaginea publicată de workflow-ul GitHub Actions din acest repo).

## 2. Data de început a semestrului

`pclp week` și portalul calculează săptămâna din `semester_start` (dată ISO) din
`content/build/course.json`, generat de pipeline-ul de conținut. Setați data (și maparea săptămână → laborator) în
`content/curated/course.yaml` și reconstruiți imaginea. Săptămâna = `(azi − semester_start) / 7 + 1`, limitată la 1..14
(vacanțele nu sunt scăzute automat — numerotați temele Moodle după săptămânile de curs).

## 3. Ce conține o predare

`pclp submit N` creează `work/predari/sapt-NN-<nume>-<AAAALLZZ-HHMM>.tar.gz` și afișează
codul `PCLP-XXXX-XXXX-XXXX-XXXX` (primele 16 caractere hex ale SHA-256 al arhivei) + SHA-256 complet.

| fișier | conținut |
|---|---|
| `history.bundle` | `git bundle --all`: tot istoricul din `~/work` (snapshot-uri automate la ~20 s după editare, cel puțin la 10 min) + tag-urile `sapt-NN` |
| `files/` | conținutul directorului `sapt-NN/` la momentul predării (doar fișiere urmărite de git) |
| `logs/terminal.log` | TSV: `ora ⇥ director ⇥ cod ieșire ⇥ comandă` pentru fiecare comandă din bash |
| `logs/tools.log` | blocuri `=== ora \| director \| comandă \| exit N ===` + ieșirea gcc/cc/clang/make/valgrind (max 200 linii) |
| `logs/tests.log` | rulări `pclp test`: `ora ⇥ problemă ⇥ trecute/total ⇥ compile_ok/fail ⇥ normal/valgrind` |
| `ai/` | `continue/`, `gemini/`, `claude/`, `codex/` (copii ale transcrierilor), `portal.jsonl`, `external/*.md` |
| `manifest.json` | student, săptămână, HEAD, tag, predarea anterioară, momentul creării, versiunea imaginii, statistici, SHA-256 pentru fiecare fișier |

La re-predare tag-ul `sapt-NN` este mutat și contorul `resubmission` crește.

## 4. Verificarea predărilor (`tools/pclp-verify`)

Pe laptopul vostru (Python ≥ 3.10 și git; nu e nevoie de Docker):

1. Pe Moodle, la temă: *Vizualizare toate predările → Descărcare toate predările* → un `.zip`.
   Tema trebuie să aibă activate **„Predare fișier”** și **„Text online”** (studentul lipește codul).
2. Rulați:

   ```sh
   python3 tools/pclp-verify ~/Downloads/PCLP-Saptamana-3.zip --out raport-s3
   # sau un director dezarhivat, sau mai multe săptămâni deodată (recomandat — vezi lanțul de mai jos):
   python3 tools/pclp-verify moodle-s1/ moodle-s2/ moodle-s3/ --out raport
   # coduri colectate altfel: CSV cu coloanele archive,code
   python3 tools/pclp-verify arhive/ --codes coduri.csv --out raport
   ```

3. Deschideți `raport/index.html` (tabel sumar; și `summary.csv` pentru Excel), apoi
   `timeline-<student>-sapt-NN.html` pentru fiecare student: o cronologie unică, pe sesiuni de lucru
   (pauză > 15 min = sesiune nouă; `--gap` o modifică), cu snapshot-uri (diff-uri colorate .c/.h),
   comenzi (cu cod de ieșire), ieșiri ale compilatorului/valgrind (erorile evidențiate), rulări de teste și
   prompturi AI (textul promptului vizibil, răspunsurile pliate). `--all-history` arată tot istoricul,
   nu doar fereastra de la predarea anterioară.

Codul se ia automat din `onlinetext.html` (folderul `Nume_ID_assignsubmission_onlinetext_` sau același
folder cu fișierul). „Timp activ” = suma intervalelor mai mici de 15 minute dintre evenimente consecutive.

### Ce înseamnă semnalările

| nivel | mesaj | interpretare |
|---|---|---|
| EROARE | codul de verificare nu corespunde | arhiva încărcată nu este cea pentru care s-a generat codul (modificată, alt fișier, sau cod copiat greșit — întrebați studentul) |
| EROARE | fișiere modificate / lipsă față de manifest | conținutul arhivei a fost editat după generare |
| EROARE | git bundle verify a eșuat / HEAD lipsă | istoric corupt sau fabricat |
| EROARE | predarea anterioară / săpt. N nu este strămoș | istoria a fost rescrisă (rebase, reset, repo reinițializat) după o predare anterioară — comparați cu arhivele vechi |
| EROARE | `files/…` sau `logs/…` diferă de git | arhiva nu corespunde propriului istoric |
| atenție | cod lipsă | studentul nu a lipit codul în textul predării |
| atenție | commit-uri cu dată anterioară părintelui / dată autor ≠ dată commit | ceas modificat, `git commit --amend`, rebase sau cherry-pick |
| atenție | commit-uri datate după predare | ceasul containerului/gazdei era greșit |
| atenție | alte adrese de email în commit-uri | istoric combinat din alt repo / alt student |
| atenție | numele din arhivă diferă de Moodle | arhiva altui student sau `pclp init` completat greșit |
| info | re-predare, verificat lanțul cu săpt. N, merge-uri | informativ |

## 5. Limitele modelului de integritate (varianta A, fără server) — pe scurt și onest

- Codul de verificare dovedește **doar** că arhiva încărcată nu a fost modificată **după** ce studentul a
  rulat `pclp submit` și a lipit codul pe Moodle (Moodle păstrează ora predării).
- **Nu** dovedește că istoricul este autentic: un student care înțelege git și formatul poate fabrica
  un istoric plauzibil (inclusiv date), poate edita jurnalele înainte de `pclp submit`, poate lucra în
  afara containerului și lipi codul, sau poate șterge sesiunile AI. Datele sunt pe calculatorul lui.
- Verificarea lanțului între săptămâni (tag-urile vechi trebuie să fie strămoși) face rescrierea
  retroactivă vizibilă, dar numai dacă aveți arhivele anterioare (rulați verificatorul pe mai multe
  săptămâni deodată).
- Transcrierile AI depind de formatele uneltelor (se pot schimba între versiuni); prompturile externe
  sunt auto-raportate.
- Concluzie: folosiți cronologia ca **bază de discuție** despre proces (cum a depanat, ce a întrebat,
  cât a iterat), nu ca probă de fraudă. Rezultatele învățării se măsoară la testele din clasă.

## 6. GDPR și informarea studenților

- **Ce date**: nume, email Moodle, grupă; codul scris și istoricul lui; comenzile tastate în terminal
  (text, oră, director, cod de ieșire); ieșirea compilatoarelor/valgrind; rezultatele testelor;
  prompturile și răspunsurile AI din unelte folosite în container sau prin portal; prompturile externe
  auto-raportate. **Nu**: taste, ecran, clipboard, ieșirea generală a programelor, date din afara containerului,
  chei API/autentificări (rămân în `work/.pclp/state/`, exclus din git; cheile lipite în prompturi sunt mascate).
- **Unde**: exclusiv pe calculatorul studentului, până când acesta încarcă voluntar arhiva pe Moodle.
  Nicio telemetrie (code-server are telemetria dezactivată; nu există server PCLP).
- **Scop**: evaluarea procesului de lucru la laborator (componenta de proces a notei) și feedback.
- **Informare**: prezentați `docs/student.md` (secțiunea „Ce se înregistrează”) la primul laborator și
  publicați-o pe Moodle; studentul poate inspecta oricând tot ce se predă (fișiere text + `git log`).
- **Păstrare**: arhivele de pe Moodle și rapoartele generate se păstrează cel mult până la încheierea
  situației școlare a anului (inclusiv contestații/restanțe), apoi se șterg; nu le copiați în alte
  sisteme și nu le partajați în afara echipei de predare. Rapoartele HTML conțin date personale —
  păstrați-le pe un dispozitiv criptat.
- **Temei și contact**: stabiliți-le împreună cu responsabilul DPO al universității și menționați-le
  în fișa disciplinei.

## 7. Alte note tehnice

- `~/work` este un repo git; snapshot-urile sunt făcute de `pclp-watch` (inotify + debounce 20 s,
  plus verificare periodică la 10 min și verificarea sesiunilor AI la 60 s).
- Wrapper-ele din `/opt/pclp/wrap` (primele în `PATH`) înregistrează doar comenzile rulate sub `~/work`
  și nu dublează înregistrarea când `make` apelează `cc`.
- Sesiunile AI se copiază din: `~/.continue/sessions/*.json`, `~/.gemini/tmp/*/chats/*.json[l]` (+ `logs.json`),
  `~/.claude/projects/*/*.jsonl`, `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (tabelul `AI_SOURCES`
  din `tools/pclp_logs.py`, ușor de extins). Fișierele de configurare / autentificare nu se copiază niciodată.
- Fișierul de stil: `env/rootfs/opt/pclp/templates/work/.clang-format` (derivat din pagina de coding
  style a cursului: kernel-like, indentare 4 cu tab, 80 de coloane, acolade obligatorii).

## 8. Conținutul portalului (laboratoare, concepte, man pages)

Portalul (`portal/`, Django) urmează specificația aplicației de manual, adaptată: în loc de un PDF,
sursele sunt paginile OCW (suport teoretic, ghiduri, coding style), enunțurile de pe acs-pclp.github.io
și paginile de manual Linux (`man-pages`, generate cu `mandoc` din pachetele instalate în imagine).

| Unde | Ce |
|---|---|
| `sources/raw/` | HTML-ul descărcat (OCW export xhtml, acs-pclp) + imaginile. Se reîmprospătează cu `python3 content/pipeline/fetch_sources.py`. |
| `content/curated/units.yaml` | Laboratoarele și ghidurile, cu sursele lor. |
| `content/curated/course.yaml` | Calendarul: `semester_start`, săptămână → laborator, ghiduri recomandate. |
| `content/curated/parts/*/concepts.tsv`, `relations.txt`, `prompts.yaml` | Conceptele (≈390), relațiile (≈840) și prompturile recomandate. Format: `content/curated/FORMAT.md`. |
| `content/curated/problems/<lab>/<id>/` | Cele 10 probleme/laborator: `problem.yaml` (enunț, 3 indicii, greșeli frecvente) + `tests/`. Format: `PROBLEMS_FORMAT.md`. |
| `../pclp-solutions/<lab>/<id>/` | **Soluțiile de referință + note pentru profesor**, în repo-ul privat `PCLP-UPB/pclp-solutions`, clonat alături. |
| `content/pipeline/` | `extract_reader` → `extract_man` → `build_database` (→ `content/build/content.sqlite`). |

Comenzi uzuale (vezi `make help`):

```bash
make content          # reconstruiește baza (fără man pages)
make content-full     # inclusiv paginile de manual, într-un container Ubuntu
make dev              # portalul local, în modul autor, pe http://127.0.0.1:8765
make check-solutions  # toate soluțiile de referință trec toate testele?
make export-edits     # editările făcute în portal → fișierele curate
make image            # imaginea studenților (rulează și build-ul de conținut)
```

**Modul autor** (`PCLP_AUTHOR=1`, activ în `make dev`): pe pagina unui termen apar butoanele de nivel
(1/2/3) și „Editează” (denumire, tip, definiție, sinonime, locul definiției, relații ascunse/adăugate),
plus „Termen nou” și „Audit” în subsol. Editările stau într-un strat peste baza de conținut; comanda
`exporta_editari` le scrie în `content/curated/concepts.tsv` și `relations.txt` (fișiere unificate care
înlocuiesc părțile `parts/*`), apoi `make content`. Pagina `/audit/` listează observațiile validării
(evidențe care nu conțin termenul, relații cu capete necunoscute etc.).

**Probleme noi:** copiază structura unei probleme existente, scrie soluția în `../pclp-solutions/<lab>/<id>/`,
generează ieșirile rulând soluția (`tools/run_tests.py <problemă> <solution.c> --generate`) și verifică cu
`make check-solutions`.
Indiciile se scriu pornind de la soluție, de la general la specific, fără cod.

**AI în portal:** tutorele din pagina problemei, butonul „✨ Explică” (selecție în text) și întrebările
generate folosesc cheia studentului (Claude prin SDK-ul oficial `anthropic`, sau orice furnizor
compatibil OpenAI: Gemini, OpenAI, Mistral, Ollama local). Cheia stă în `work/.pclp/state/` și nu intră
în arhivă; prompturile și răspunsurile intră (`.pclp/ai/portal.jsonl`). Chat-ul Copilot integrat în
code-server e dezactivat (`chat.disableAIFeatures`), pentru că sesiunile lui nu pot fi colectate.

## 9. Punctaj după timpul activ (`tools/pclp-grade`)

```bash
python3.11 tools/pclp-grade <arhive | director | moodle.zip> [--hours 4] [--max-points 100] [--csv note.csv]
```

Timpul activ se calculează ca în `pclp-verify` (evenimente din fereastra săptămânii; o pauză de peste
15 minute începe o sesiune nouă). Punctaj liniar: 0 h = 0%, 4 h = 100% (plafonat). O arhivă care nu trece
verificarea primește 0 (`--ignore-integrity` pentru a o puncta totuși). Implicit se punctează doar cea mai
recentă predare a fiecărui student pentru fiecare săptămână (`--all-submissions` pentru toate).


## 10. Actualizarea materialelor la studenți

Materialele (textele laboratoarelor, conceptele, problemele, indiciile, testele, prompturile) sunt publicate
**separat de imagine**, ca pachet de conținut:

1. Faceți modificarea în repo (`content/curated/…`, sau `sources/raw/…` după `fetch_sources.py`) și o
   aduceți pe `main` (direct sau prin pull request, după ce trece `check`).
2. Workflow-ul **`content`** construiește baza (cu paginile de manual), o verifică și publică un
   GitHub Release `content-AAAA.LL.ZZ-N` cu `content.tar.gz` + `content.json`. Se poate rula și manual
   (Actions → content → Run workflow), cu un **mesaj pentru studenți** („Am corectat testele problemei 5 din lab04”)
   care apare în portal la actualizare.
3. Portalul fiecărui student verifică `…/releases/latest/download/content.json` la pornire și apoi la
   fiecare 6 ore (`PCLP_UPDATE_HOURS`), descarcă pachetul, îi verifică amprenta SHA-256 și integritatea bazei
   și trece pe versiunea nouă fără repornire. Studentul vede un anunț „Materialele cursului au fost
   actualizate”. `pclp test` folosește imediat testele noi.

Detalii tehnice:

- Pachetele descărcate stau în `work/.pclp/state/content/` (ignorat de git, nu intră în arhive); se
  păstrează ultimele două versiuni. Dacă descărcarea sau verificarea eșuează, rămâne versiunea curentă.
- Fără internet, portalul folosește ultima versiune descărcată (sau pe cea din imagine).
- Fiecare pachet are o **schemă** (`CONTENT_SCHEMA` în `build_database.py` = `SCHEMA` în
  `tools/pclp_content.py`). Dacă schimbați structura bazei, măriți ambele valori: studenții cu imagine veche
  nu vor instala pachetul și vor fi rugați să ruleze `docker compose pull && docker compose up -d`.
- **Imaginea** se reconstruiește doar când se schimbă uneltele, portalul sau pipeline-ul (`env/`, `portal/`,
  `tools/`, `content/pipeline/`). Abia atunci studenții au nevoie de `docker compose pull`.
- Oprire pentru un container anume: `PCLP_CONTENT_URL=` (gol) în mediul containerului.
