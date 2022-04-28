
import os

from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor

def fn(str):
    print("pid: {}, {}".format(os.getpid(), str))

def run_concurrent():
    # executor = ThreadPoolExecutor()
    executor = ProcessPoolExecutor()
    for i in range(5):
        executor.submit(fn, "task"+str(i))

if __name__ == "__main__":
    run_concurrent()