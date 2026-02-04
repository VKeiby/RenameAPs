import random
import time


def execTime(func):
    def procTime(t):
        startTime = time.time()
        func(t)
        print("Time to process - ", time.time() - startTime)

    return procTime


# @execTime
# def process(zakaz):
#     match zakaz:
#         case 1:
#             return 'There is your Cognac'
#         case 2:
#             return 'There is your Vodka'
#


Ebar = "Our bar is Empty"
alco = {"Cognac": 300, "Vodka": 100}
# print(type(alco))
# for i in alco.items(): # alco.keys() or alco.value()
#     print(i)
print(
    "Now in bar:\n",
    "Available Vodka:",
    alco["Vodka"],
    "ml\n",
    "Available Cognac:",
    alco["Cognac"],
    "ml\n",
)
print("1-Cognac -50ml\n", "2-Vodka -50ml\n", "3-Pour me something at once!\n")
zakaz = int(input("What do U want?\n"))

if zakaz == 3:
    zakaz = random.randint(1, 2)
if zakaz == 1:
    if alco["Cognac"] > 0:
        print("There is your Cognac")
    else:
        print(Ebar)
else:
    if alco["Vodka"] > 0:
        print("There is your Vodka")
    else:
        print(Ebar)
