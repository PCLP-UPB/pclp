# Mediul de lucru PCLP — ghid pentru studenți

La PCLP lucrezi într-un **container Docker** care conține tot ce îți trebuie:

- **VS Code în browser** (code-server), cu extensii pentru C (clangd), depanare (gdb) și asistentul AI Continue;
- compilatoarele și uneltele cursului: `gcc`, `clang`, `make`, `gdb`, `valgrind`, `cppcheck`,
  `clang-format` și paginile de manual (`man 3 printf`);
- **portalul cursului** (materiale, probleme, teste);
- o înregistrare discretă a **procesului** tău de lucru, pe care o predai săptămânal.

> La laborator nota vine din testele de la clasă. Predarea săptămânală arată **cum** ai lucrat
> (procesul), nu cât de corect e rezultatul final. Nu ai nimic de ascuns: încercările greșite, erorile
> de compilare și întrebările puse unui AI sunt **normale** și fac parte din învățare.

---

## Pe scurt

1. Instalează [Docker Desktop](https://www.docker.com/products/docker-desktop/) și pornește-l.
2. Creează un director pentru curs și descarcă în el fișierul `compose.yaml`
   ([link direct](https://raw.githubusercontent.com/PCLP-UPB/pclp/main/env/compose.student.yaml) — salvează-l cu numele **`compose.yaml`**), sau din terminal, în acel director:
   - macOS / Linux: `curl -fsSL https://raw.githubusercontent.com/PCLP-UPB/pclp/main/env/compose.student.yaml -o compose.yaml`
   - Windows (PowerShell): `curl.exe -fsSL https://raw.githubusercontent.com/PCLP-UPB/pclp/main/env/compose.student.yaml -o compose.yaml`
3. În același director: `docker compose up -d`
4. Deschide portalul: <http://localhost:8000> (completează numele, emailul Moodle și grupa) și VS Code: <http://localhost:8080>.
5. Lucrezi la problemele săptămânii; la final, în terminalul din VS Code: `pclp submit <săptămâna>`,
   apoi încarci arhiva din `work/predari/` pe Moodle și lipești **codul de verificare** afișat.

Detaliile sunt mai jos.

---

## 1. Instalare (o singură dată)

1. Instalează **Docker Desktop**: <https://www.docker.com/products/docker-desktop/>
   - **Windows**: în timpul instalării păstrează bifată opțiunea **„Use WSL 2”**. Dacă ți se cere,
     rulează în PowerShell (ca administrator) `wsl --install` și repornește calculatorul.
   - **macOS**: alege varianta potrivită procesorului (Apple Silicon — M1/M2/M3/M4 — sau Intel).
   - **Linux**: instalează Docker Engine + pluginul `docker compose` (sau Docker Desktop).
2. Creează un director pentru curs, de exemplu `Documente/pclp`.
3. Descarcă în el fișierul **`compose.yaml`** ([link direct](https://raw.githubusercontent.com/PCLP-UPB/pclp/main/env/compose.student.yaml); salvează-l exact cu numele
   `compose.yaml`) — sau varianta pusă de profesor pe Moodle.
   Tot ce lucrezi va fi salvat în subdirectorul **`work/`**, creat automat lângă `compose.yaml`.
   **Nu șterge directorul `work/`** — acolo sunt sursele tale și istoricul.
4. Deschide un terminal (Windows: PowerShell; macOS: Terminal) **în directorul cursului** și rulează:

   ```sh
   docker compose up -d
   ```

   Prima dată durează câteva minute (se descarcă imaginea: ~1 GB, ~2,5 GB după dezarhivare).

## 2. Utilizare zilnică

| Ce                  | Unde                                   |
|---------------------|----------------------------------------|
| Portalul cursului   | <http://localhost:8000>                |
| VS Code în browser  | <http://localhost:8080>                |
| Oprire              | `docker compose stop` (sau lasă-l pornit) |
| Pornire             | `docker compose up -d`                 |
| Actualizare imagine | `docker compose pull && docker compose up -d` |

Terminalul din VS Code (meniul ☰ → *Terminal* → *New Terminal*) este un terminal Linux, în `~/work`.
Poți intra în container și dintr-un terminal de pe calculatorul tău:

```sh
docker exec -it -u student pclp bash
```

### Prima pornire: datele tale

La prima deschidere, portalul (<http://localhost:8000>) îți cere numele, emailul și grupa. Alternativ,
în terminalul din VS Code rulează o singură dată:

```sh
pclp init
```

și completează **numele complet (exact ca pe Moodle)**, **emailul Moodle** și **grupa** (ex. `311CA`).
Poți rula comanda din nou oricând ca să corectezi datele.

### Comenzi utile

```sh
pclp status          # cine ești, ce s-a înregistrat săptămâna asta
pclp week            # săptămâna curentă a semestrului
pclp test            # (în directorul unei probleme) compilează și rulează testele
pclp test --valgrind # la fel, dar verifică și memoria cu valgrind
pclp snap -m "mesaj" # salvează imediat un snapshot (oricum se face automat)
man 3 printf         # documentația unei funcții din biblioteca C
```

Problemele se rezolvă în `~/work/sapt-NN/<problema>/` (portalul creează directoarele).
Compilare recomandată: `gcc -Wall -Wextra -std=c11 -g main.c -o main`.
În VS Code: **Ctrl+Shift+B** compilează fișierul curent, **F5** pornește depanatorul (gdb).
Stilul de cod al cursului este în `~/work/.clang-format` (formatare: *Format Document*).

## 3. Ce se înregistrează — și ce NU

Totul rămâne **pe calculatorul tău**, în `work/`. Nimic nu este trimis nicăieri automat.
Profesorul vede aceste date **doar** când încarci arhiva săptămânală pe Moodle.

**Se înregistrează:**

1. **Modificările codului** — un snapshot git automat la ~20 de secunde după ce te oprești din scris
   (și cel puțin o dată la 10 minute). Doar fișierele sursă/text (`.c`, `.h`, `Makefile`, `.txt`,
   `.md`, `.in`/`.out` etc.), **niciodată** executabile, și niciun fișier mai mare de 1 MB.
2. **Comenzile din terminal** — textul comenzii, ora, directorul și codul de ieșire
   (în `work/.pclp/terminal.log`). **Nu** se înregistrează ce afișează comenzile.
3. **Ieșirea compilatoarelor și a uneltelor de verificare** — `gcc`, `cc`, `clang`, `make`, `valgrind`
   (mesajele de eroare/avertisment fac parte din procesul de învățare), în `work/.pclp/tools.log`;
   plus rezultatele `pclp test` în `work/.pclp/tests.log`.
4. **Prompturile către asistenți AI**, acolo unde se poate:
   - conversațiile din **Continue** (VS Code) și din CLI-urile **Gemini CLI**, **Claude Code**, **Codex CLI**
     folosite în container (copiate în `work/.pclp/ai/`);
   - întrebările puse prin portal;
   - prompturile folosite **în afara** containerului, pe care le raportezi singur în portal
     (formularul **„Adaugă prompt extern”**).

**NU se înregistrează:** tastele apăsate, mișcările mouse-ului, ce copiezi/lipești, ce e pe ecran,
ieșirea generală a programelor tale, istoricul browserului, nimic din afara containerului.
**Cheile API și autentificările** tale pentru uneltele AI (în `work/.pclp/state/`) **nu** intră
niciodată în predare. Dacă lipești din greșeală o cheie într-un prompt, ea este mascată (`[REDACTAT]`).

Poți verifica oricând ce s-a înregistrat: fișierele din `work/.pclp/` sunt text simplu, iar istoricul
se vede cu `git log --stat` în `~/work`.

## 4. Asistenți AI

Poți folosi AI — e chiar încurajat, **ca pe un tutore**. În `~/work` există `AGENTS.md`, `CLAUDE.md`,
`GEMINI.md` și `.continue/rules/tutor.md`: ele îi cer asistentului să explice, să pună întrebări și să
dea indicii, nu soluția gata făcută. (Le poți șterge — se vede în istoric; nu e interzis, dar
te privează de ce e mai util.)

- **Continue (în VS Code)**: iconița Continue din bara laterală → configurează un model cu cheia ta
  (ex. un nivel gratuit Gemini/Mistral/Groq) sau un model local. Configurarea și cheia rămân în
  `work/.pclp/state/` (persistente, dar nepredate).
- **CLI-uri AI în terminal** (necesită cont propriu):
  ```sh
  pclp ai-install gemini   # Gemini CLI  (apoi: gemini)
  pclp ai-install claude   # Claude Code (apoi: claude)
  pclp ai-install codex    # Codex CLI   (apoi: codex)
  ```
- **AI în afara containerului** (ChatGPT în browser, telefon etc.): adaugă promptul în portal cu
  **„Adaugă prompt extern”**. Onestitatea contează mai mult decât numărul de prompturi.

## 5. Predarea săptămânală

La finalul săptămânii (înainte de termenul de pe Moodle), în terminalul din VS Code:

```sh
pclp submit 3        # 3 = numărul săptămânii
```

Comanda face un ultim snapshot, creează arhiva și afișează un **cod de verificare**, de forma
`PCLP-1A2B-3C4D-5E6F-7A8B`. Apoi, pe Moodle, la tema săptămânii:

1. încarcă fișierul `work/predari/sapt-03-<nume>-<data>.tar.gz` (îl găsești în directorul `work/predari/`
   de lângă `compose.yaml`);
2. **lipește codul de verificare** în câmpul de text al predării.

Nu modifica, nu redenumi conținutul și nu re-arhiva fișierul — codul n-ar mai corespunde.
Dacă vrei să predai din nou (înainte de termen), rulează iar `pclp submit 3` și încarcă noua arhivă
cu noul cod. **Nu rescrie istoricul git** (`git rebase`, `git commit --amend`, `git reset` pe
commit-uri deja predate, ștergerea `.git`) — verificatorul detectează asta.

## 6. Probleme frecvente

- **„port is already allocated” / „address already in use”**: alt program folosește portul 8000
  sau 8080. Oprește-l sau pornește cu alte porturi:
  `PCLP_PORT_PORTAL=8001 PCLP_PORT_VSCODE=8081 docker compose up -d`
  (Windows PowerShell: `$env:PCLP_PORT_PORTAL=8001; docker compose up -d`) și folosește
  <http://localhost:8001> / <http://localhost:8081>.
- **„Cannot connect to the Docker daemon”**: pornește aplicația Docker Desktop și așteaptă să fie „running”.
- **Windows**: dacă Docker cere WSL 2, rulează `wsl --update` în PowerShell. Ține directorul cursului
  pe discul local (nu pe OneDrive/rețea). Dacă merge greu, poți ține directorul cursului în WSL
  (ex. `\\wsl$\Ubuntu\home\<user>\pclp`).
- **Mac cu Apple Silicon (M1–M4)**: imaginea are variantă nativă arm64; nu e nevoie de Rosetta.
- **Linux — fișierele din `work/` au alt proprietar / „Permission denied”**: containerul preia automat
  proprietarul directorului `work/`. Dacă tot apare problema:
  `PUID=$(id -u) PGID=$(id -g) docker compose up -d`.
- **VS Code nu se încarcă**: `docker compose logs --tail 50` și `docker compose restart`.
- **`gdb` sau `valgrind` dau erori de permisiuni**: folosește `compose.yaml` primit (are
  `SYS_PTRACE` și `seccomp:unconfined`).
- **Am șters din greșeală un fișier**: e în istoric — `git log -- cale/fisier.c`, apoi
  `git checkout <commit> -- cale/fisier.c`.
- **Reinstalare completă**: `docker compose down && docker compose up -d` — datele din `work/`
  (inclusiv autentificările AI și setările VS Code) se păstrează.
