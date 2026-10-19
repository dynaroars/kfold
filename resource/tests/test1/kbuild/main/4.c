#include <f.h>

int f4() {
  #ifdef CONFIG_B
  f2();
  #else
  f3();
  #endif
  printf("4\n");
  return 0;
}
