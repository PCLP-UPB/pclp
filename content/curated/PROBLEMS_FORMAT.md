# Formatul problemelor săptămânale

Fiecare laborator are seturi de câte 10 probleme proprii (p01–p10, apoi p11–p20 …), fiecare set cu dificultate crescătoare (prima cea mai ușoară, ultima o provocare).

## Ce vede studentul: `content/curated/problems/<lab>/<id>/`

```
content/curated/problems/lab05/lab05-p03-inversare-vector/
  problem.yaml
  tests/01.in  tests/01.out        # intrare pe stdin / ieșire așteptată pe stdout
  tests/02.in  tests/02.out
  tests/03.args                    # opțional: argumentele programului, câte unul pe linie
  tests/03.files/date.txt          # opțional: fișiere copiate în directorul de rulare
```

`problem.yaml`:

```yaml
id: lab05-p03-inversare-vector      # <lab>-pNN-<slug ascii>
lab: lab05
number: 3
title: "Inversarea unui vector cu pointeri"
difficulty: 2                        # 1 (încălzire) … 5 (provocare); crește cu numărul problemei
estimated_minutes: 25
concepts: [pointer, aritmetică cu pointeri, vector]   # label-uri de concepte (vezi FORMAT.md)
statement: |                          # Markdown, în română
  Cerința, apoi secțiunile **Date de intrare**, **Date de ieșire**, **Restricții**, **Exemplu**
  (exemplul coincide cu tests/01).
starter: |                            # opțional: schelet C fără soluție (main + semnături + TODO)
  #include <stdio.h>
  ...
hints:                                # 3 indicii, de la general la specific; FĂRĂ cod de soluție
  - "Indiciu conceptual: la ce trebuie să te gândești."
  - "Indiciu de abordare: pașii mari, structurile de date."
  - "Indiciu detaliat: pseudocod sau capcana principală (cazuri limită), tot fără cod C complet."
pitfalls:                             # opțional: greșeli frecvente (se afișează după indicii)
  - "..."
```

- Testele: minimum 5 per problemă (01 = exemplul din enunț), inclusiv cazuri limită. Ieșirea așteptată se generează rulând soluția de referință, nu se scrie de mână.
- Comparația ignoră spațiile de la finalul liniilor și liniile goale de la final.
- Problemele cu fișiere sau argumente folosesc `NN.files/` și `NN.args`; ieșirea verificată e tot stdout.

## Ce NU ajunge la student: `pclp-solutions/<lab>/<id>/`

```
pclp-solutions/lab05/lab05-p03-inversare-vector/
  solution.c          # soluția de referință, compilează cu: gcc -Wall -Wextra -std=c11 -O0 -g solution.c -o sol -lm
  notes.md            # pentru profesor: ideea, complexitatea, variante, ce urmărim la evaluare
```

Soluțiile stau în repo-ul privat [PCLP-UPB/pclp-solutions](https://github.com/PCLP-UPB/pclp-solutions), clonat alături de `pclp/` (`../pclp-solutions`). Nu se pun niciodată în repo-ul public `pclp` și nu ajung în imaginea Docker.
