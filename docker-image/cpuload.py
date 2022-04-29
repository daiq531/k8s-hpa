import math
import time

def cpuload():
    etime = {}
    start_time = time.time()
    for x in range(1, 1000000):
        s = math.sqrt(x)
    end_time = time.time()
    time_taken = end_time - start_time
    etime["start_time"] = start_time
    etime["end_time"] = end_time
    etime["time_taken"] = time_taken
    return etime

"""if __name__ == "__main__":
    f = squareroot()
    print(f)"""