#include <stdio.h>
#define N 10
#define MESAJ "gata"
int v[N];
#ifdef DEBUG
printf("N = %d\n", N);
#else
puts(MESAJ);
#endif
int N2 = N * 2;
