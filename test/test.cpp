#define MAKE_FUNC(x) int func_##x(int b);

MAKE_FUNC(1)
MAKE_FUNC(2)

int foo();

extern void hoge();

int foo(int a) {
    return a + 1;
}