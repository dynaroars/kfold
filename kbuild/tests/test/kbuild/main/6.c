#include <f.h>

int f6() {
  printf("6\n");
  #ifdef CONFIG_G
  f7();
  #endif
  return 0;
}
