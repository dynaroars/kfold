#include <f.h>

int f7() {
  #ifndef CONFIG_F
  f8();
  #endif
  printf("7\n");
  return 0;
}
