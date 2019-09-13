#include <f.h>

int main(int argc, char **argv) {
  printf("hello, world!\n");
  #ifdef CONFIG_A
  f1();
  #endif
  #ifdef CONFIG_C
  f4();
  #endif
  #ifdef CONFIG_E
  f5();
  #endif
  #ifdef CONFIG_G
  f7();
  #elif defined(CONFIG_F)
  f6();
  #endif
  return 0;
}
