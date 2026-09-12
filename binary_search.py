numbers = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

print("List of Numbers:", numbers)

search_value = int(input("Enter number to search: "))

low = 0
high = len(numbers) - 1
position = -1
comparisons = 0

while low <= high:
    mid = (low + high) // 2
    comparisons += 1
    if numbers[mid] == search_value:
        position = mid + 1
        break
    elif numbers[mid] < search_value:
        low = mid + 1
    else:
        high = mid - 1

if position != -1:
    print(f"{search_value} found at position {position}")
else:
    print("Number not found")

print("Number of comparisons:", comparisons)
