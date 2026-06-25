# Welcome to AetherIDE!
# This is a sample Python file. Press F5 or click the Run button to execute.

def greet(name):
    print(f"Hello, {name}!")
    print("Welcome to your lightweight multi-language developer environment.")

def math_demo():
    print("\nCalculating Fibonacci numbers:")
    a, b = 0, 1
    for _ in range(10):
        print(a, end=" ")
        a, b = b, a + b
    print()

if __name__ == "__main__":
    greet("Developer")
    math_demo()
