import time
import random
import sys

instance_name = sys.argv[1]
duration = float(sys.argv[2])
total_steps = 100
sleep_time = duration / total_steps

for i in range(total_steps + 1):
    speed = f"{random.uniform(0.8, 1.5):.1f} MB/s"  # Simulate speed
    print(f"Instance: {instance_name}, Progress: {i}/{total_steps}, Speed: {speed}", flush=True)
    time.sleep(sleep_time)
