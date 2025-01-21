
import time
import random
import sys

instance_name = sys.argv[1]
total_steps = random.randint(5, 15)
for i in range(total_steps + 1):
    print(f"Instance: {instance_name}, Progress: {i}/{total_steps}")
    time.sleep(random.uniform(0.1, 0.5))
