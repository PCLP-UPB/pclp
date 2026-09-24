#define A 1
#ifdef A
  a este definit
  #ifndef B
    B nu este definit, A = A
    #define B 2
  #else
    B era deja definit
  #endif
  B = B
#else
  #define C 3
#endif
C ramane C
#undef A
#ifdef A
nu apare
#endif
A final, "A in sir", A_B, 12A
