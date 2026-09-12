numbers = [25, 10, 45, 30, 15, 50, 20, 35, 40, 5]

print("List of Numbers:", numbers)

search_value = int(input("Enter number to search: "))

position = -1
comparisons = 0

for i in range(len(numbers)):
    comparisons += 1
    if numbers[i] == search_value:
        position = i + 1
        break

if position != -1:
    print(f"{search_value} found at position {position}")
else:
    print("Number not found")

print("Number of comparisons:", comparisons)
