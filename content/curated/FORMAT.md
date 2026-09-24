# Formatul datelor curate

Toate fișierele sunt UTF-8, cu diacritice corecte (ș, ț cu virgulă). Sunt editabile de mână și din aplicație (modul autor, comanda `exporta_editari`).

## `concepts.tsv`

Separat prin TAB, cu antet. O linie per concept.

| Coloană | Conținut |
|---|---|
| `label` | Denumirea canonică. Pentru identificatori C, forma exactă din cod (`malloc`, `NULL`, `size_t`, `#define`, `%d`). Pentru noțiuni, în română, la singular nearticulat, cu literă mică (excepție: nume proprii, acronime): `pointer`, `alocare dinamică`, `aritmetică cu pointeri`. |
| `level` | 1 = bază (trebuie știut), 2 = aprofundare (explică mecanismele), 3 = detaliu (specializat). |
| `kind` | Unul dintre: `noțiune`, `tip de date`, `operator`, `instrucțiune`, `cuvânt cheie`, `funcție de bibliotecă`, `fișier antet`, `directivă preprocesor`, `unealtă`, `opțiune de compilare`, `eroare`, `bună practică`, `tehnică`, `specificator de format`. |
| `unit` | Laboratorul/ghidul principal (`lab05`, `debugging`) — unde e tratat prima dată pe larg. |
| `evidence` | Secțiunile care susțin definiția, separate prin virgulă: `lab05#notiunea_de_pointer,lab05#aritmetica_cu_pointeri` (id-urile din `[..]` din fișierele dump). Termenul (sau un alias) trebuie să apară în acele secțiuni. |
| `definition` | Reformulare scurtă (1–2 fraze, max ~220 caractere), fidelă textului din secțiunea citată, pentru un student de anul I. Fără a inventa informație care nu reiese din laborator sau din documentația standard. |
| `aliases` | Forme alternative separate prin `;` (sinonime, forme englezești uzuale în text, variante: `pointer` → `pointeri;pointerul;pointerului;indicator`; nu e nevoie de toate formele flexionare, potrivitorul le acceptă). Poate fi gol. |
| `man` | Pentru funcții de bibliotecă, fișiere antet, unelte: pagina de manual, `malloc(3)`, `stdio.h(0p)`, `gcc(1)`, `valgrind(1)`. Gol altfel. |

Id-ul conceptului se derivă din `label`: `c-` + slug ASCII (`aritmetică cu pointeri` → `c-aritmetica-cu-pointeri`, `#define` → `c-define`, `%d` → `c-d`; la coliziune se adaugă sufixul tipului).

## `relations.txt`

O relație pe linie: `subiect|predicat|obiect|evidență|origine`

- `subiect`, `obiect`: `label`-uri existente în `concepts.tsv` (exact).
- `evidență`: `lab05#aritmetica_cu_pointeri` (secțiunea unde reiese relația) sau gol pentru relații editoriale.
- `origine`: `source_explicit` (relația e spusă în text) sau `editorial` (cunoaștere standard C, adăugată pentru învățare).

### Predicate

| Predicat | Direct / invers | Ierarhic |
|---|---|---|
| `is_a` | este un tip de / include tipul | da |
| `part_of` | face parte din / conține | da |
| `declared_in` | este declarat în / declară | da |
| `requires` | presupune cunoașterea / este necesar pentru | nu |
| `uses` | folosește / este folosit de | nu |
| `operates_on` | operează asupra / este operat de | nu |
| `returns` | returnează / este returnat de | nu |
| `pairs_with` | se folosește împreună cu / se folosește împreună cu | nu |
| `alternative_to` | este o alternativă la / are ca alternativă | nu |
| `causes` | poate cauza / poate fi cauzat de | nu |
| `detects` | detectează / este detectat de | nu |
| `prevents` | previne / este prevenit de | nu |
| `precedes` | se învață înainte de / se învață după | nu |
| `has_property` | are proprietatea / este proprietate a | nu |

`requires` e cel mai important pentru ordonarea învățării (graful de prerechizite).

## `prompts.yaml`

Prompturi recomandate pentru învățare, per unitate:

```yaml
lab05:
  - title: "Verifică-ți modelul mental"
    when: "după ce ai citit despre aritmetica cu pointeri"
    concepts: [aritmetică cu pointeri]
    prompt: |
      Explică-mi ce afișează următorul cod, pas cu pas, fără să-mi dai direct rezultatul final. ...
```

Promptul ajută studentul să învețe (explicații, contraexemple, verificarea raționamentului, interpretarea erorilor, teste), nu să primească soluția problemei de laborator.
