# Runtime Hata - ZeroDivisionError

def divide(a, b):
    return a / b

def find_average(numbers):
    return divide(sum(numbers), len(numbers))

if __name__ == "__main__":
    print("Avg [1,2,3]:", find_average([1, 2, 3]))
    print("Avg []:", find_average([]))  # ZeroDivisionError
