class A {
private:
  int a;
  void foo(int a);
public:
  void foo(double a);
  void multi(double a, int b, A* c);
  void bar();
};

int main(int argc, char const *argv[]) {
  A a;
  a.foo((double)1.0f);

  int aa;

  a.

  return 0;
}
