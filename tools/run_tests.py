#!/usr/bin/env python3
"""Rulează testele unei probleme exact ca verificatorul.

Utilizare:
    run_tests.py <problem_dir> <solution.c> [--generate] [--sanitize] [--leaks] [--quiet]

Pentru fiecare test NN (deduse din tests/NN.in, NN.out, NN.args, NN.files/):
  - creează un director temporar nou și copiază în el conținutul NN.files/;
  - rulează programul acolo, cu argumentele din NN.args (câte unul pe linie)
    și cu stdin din NN.in (sau intrare vidă);
  - compară DOAR stdout cu NN.out (ignoră spațiile de la final de linie și
    liniile goale de la final).

--generate  scrie NN.out din ieșirea soluției (în loc să compare)
--sanitize  compilează cu -fsanitize=address,undefined (Linux) sau
            -fsanitize=undefined + Guard Malloc (macOS)
--leaks     compilează cu un contor de alocări și fișiere (malloc/calloc/
            realloc/free, fopen/fclose) și raportează blocurile de memorie
            neeliberate și fișierele neînchise la terminarea programului
            (funcționează și pe macOS, unde LeakSanitizer lipsește)
--quiet     afișează doar rezumatul

Codul de ieșire: 0 dacă totul e în regulă (compilare fără avertismente,
toate testele trec), 1 altfel.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

CFLAGS = ["-Wall", "-Wextra", "-std=c11", "-O0", "-g"]
TIMEOUT = 10

# --leaks: antet inclus forțat înaintea sursei (-include) + implementarea contoarelor
LC_H = r"""
#ifndef PCLP_LEAKCHECK_H
#define PCLP_LEAKCHECK_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void *lc_malloc(size_t n);
void *lc_calloc(size_t n, size_t s);
void *lc_realloc(void *p, size_t n);
void lc_free(void *p);
FILE *lc_fopen(const char *name, const char *mode);
int lc_fclose(FILE *f);
#define malloc(n) lc_malloc(n)
#define calloc(n, s) lc_calloc(n, s)
#define realloc(p, n) lc_realloc(p, n)
#define free(p) lc_free(p)
#define fopen(a, b) lc_fopen(a, b)
#define fclose(f) lc_fclose(f)
#endif
"""
LC_C = r"""
#include <stdio.h>
#include <stdlib.h>
static long blocks, files;
void *lc_malloc(size_t n) { void *p = malloc(n); if (p) blocks++; return p; }
void *lc_calloc(size_t n, size_t s) { void *p = calloc(n, s); if (p) blocks++; return p; }
void *lc_realloc(void *p, size_t n) {
    void *q = realloc(p, n);
    if (p == NULL && q != NULL) blocks++;
    else if (p != NULL && n == 0 && q == NULL) blocks--;
    return q;
}
void lc_free(void *p) { if (p) blocks--; free(p); }
FILE *lc_fopen(const char *a, const char *b) { FILE *f = fopen(a, b); if (f) files++; return f; }
int lc_fclose(FILE *f) { if (f) files--; return fclose(f); }
static void lc_report(void) { fprintf(stderr, "\nPCLP_LEAKCHECK blocks=%ld files=%ld\n", blocks, files); }
__attribute__((constructor)) static void lc_init(void) { atexit(lc_report); }
"""


def normalize(data: bytes) -> list:
    text = data.decode("utf-8", errors="replace")
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def test_ids(tests_dir: str) -> list:
    ids = set()
    for name in os.listdir(tests_dir):
        m = re.match(r"^(\d+)\.(in|out|args|files)$", name)
        if m:
            ids.add(m.group(1))
    return sorted(ids)


def read_args(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def main() -> int:
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(pos) != 2:
        print(__doc__)
        return 2
    problem_dir, source = (os.path.abspath(p) for p in pos)
    generate = "--generate" in opts
    sanitize = "--sanitize" in opts
    quiet = "--quiet" in opts
    leaks = "--leaks" in opts
    tests_dir = os.path.join(problem_dir, "tests")

    work = tempfile.mkdtemp(prefix="pclp_rt_")
    try:
        exe = os.path.join(work, "sol")
        cmd = ["gcc"] + CFLAGS + [source, "-o", exe, "-lm"]
        darwin = sys.platform == "darwin"
        if sanitize:
            # pe macOS (clang Apple) AddressSanitizer se poate bloca la pornire;
            # folosim UBSan + Guard Malloc (libgmalloc), care prinde depășirile
            # de buffer pe heap și folosirea memoriei eliberate
            san = "undefined" if darwin else "address,undefined"
            cmd[1:1] = [f"-fsanitize={san}", "-fno-omit-frame-pointer"]
        if leaks:
            with open(os.path.join(work, "lc.h"), "w") as f:
                f.write(LC_H)
            with open(os.path.join(work, "lc.c"), "w") as f:
                f.write(LC_C)
            lc_o = os.path.join(work, "lc.o")
            subprocess.run(["gcc", "-c", os.path.join(work, "lc.c"), "-o", lc_o], check=True)
            cmd = (["gcc"] + CFLAGS + ["-include", os.path.join(work, "lc.h"), source,
                   lc_o, "-o", exe, "-lm"])
        comp = subprocess.run(cmd, capture_output=True, text=True)
        ok = True
        if comp.returncode != 0:
            print(f"[COMPILARE EȘUATĂ] {source}\n{comp.stderr}")
            return 1
        if comp.stderr.strip():
            print(f"[AVERTISMENTE] {source}\n{comp.stderr}")
            ok = False

        env = dict(os.environ)
        # pe macOS LeakSanitizer nu este disponibil (folosiți --leaks)
        if sys.platform.startswith("linux"):
            env["ASAN_OPTIONS"] = "detect_leaks=1"
        if sanitize and darwin and os.path.exists("/usr/lib/libgmalloc.dylib"):
            env["DYLD_INSERT_LIBRARIES"] = "/usr/lib/libgmalloc.dylib"
            env["MALLOC_STRICT_SIZE"] = "1"
        passed = 0
        ids = test_ids(tests_dir)
        for tid in ids:
            run_dir = os.path.join(work, f"run_{tid}")
            os.mkdir(run_dir)
            fdir = os.path.join(tests_dir, f"{tid}.files")
            if os.path.isdir(fdir):
                shutil.copytree(fdir, run_dir, dirs_exist_ok=True)
            args = read_args(os.path.join(tests_dir, f"{tid}.args"))
            in_path = os.path.join(tests_dir, f"{tid}.in")
            stdin_data = b""
            if os.path.exists(in_path):
                with open(in_path, "rb") as f:
                    stdin_data = f.read()
            try:
                res = subprocess.run([exe] + args, input=stdin_data, cwd=run_dir,
                                     capture_output=True, timeout=TIMEOUT, env=env)
            except subprocess.TimeoutExpired:
                print(f"  {tid}: TIMEOUT")
                ok = False
                continue
            if sanitize and (b"Sanitizer" in res.stderr or b"runtime error" in res.stderr
                             or res.returncode < 0):
                print(f"  {tid}: SANITIZER\n{res.stderr.decode(errors='replace')}")
                ok = False
            if leaks:
                m = re.search(rb"PCLP_LEAKCHECK blocks=(-?\d+) files=(-?\d+)", res.stderr)
                if not m:
                    print(f"  {tid}: nu am putut verifica (programul s-a oprit anormal?)")
                    ok = False
                elif m.group(1) != b"0" or m.group(2) != b"0":
                    print(f"  {tid}: NEELIBERAT blocuri={m.group(1).decode()} "
                          f"fisiere={m.group(2).decode()}")
                    ok = False
                else:
                    passed += 1
                continue
            out_path = os.path.join(tests_dir, f"{tid}.out")
            if generate:
                with open(out_path, "wb") as f:
                    f.write(res.stdout)
                passed += 1
                if not quiet:
                    print(f"  {tid}: generat ({len(res.stdout)} octeți, cod {res.returncode})")
                continue
            if not os.path.exists(out_path):
                print(f"  {tid}: lipsește {tid}.out")
                ok = False
                continue
            with open(out_path, "rb") as f:
                expected = normalize(f.read())
            got = normalize(res.stdout)
            if got == expected:
                passed += 1
                if not quiet:
                    print(f"  {tid}: OK")
            else:
                ok = False
                print(f"  {tid}: DIFERIT")
                for i in range(max(len(got), len(expected))):
                    e = expected[i] if i < len(expected) else "<lipsă>"
                    g = got[i] if i < len(got) else "<lipsă>"
                    if e != g:
                        print(f"     linia {i + 1}: așteptat {e!r}, obținut {g!r}")
                        break
        print(f"{os.path.basename(problem_dir)}: {passed}/{len(ids)} teste"
              f"{' generate' if generate else ' trecute'}")
        return 0 if ok and passed == len(ids) else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
