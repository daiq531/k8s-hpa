import sys
import math
import time
import os
from threading import Thread, Timer
from multiprocessing import Process, Pool, Queue
from queue import Full
from flask import Flask, request, make_response


app = Flask(__name__)

'''
# below is new solution Klaus suggested
class CaculationWorker2(Thread):
    def __init__(self, count, interval):
        super().__init__()
        self.count = count
        self.interval = interval
        self.run_flag = True
    
    def run(self):
        while(self.run_flag):
            x = 0.0001
            for i in range(self.count):
                x += math.sqrt(x)
            time.sleep(self.interval)

    def stop(self):
        self.run_flag = False

worker = None
@app.route('/')
def index():
    return "OK"

@app.route('/start', methods=['POST'])
def start():
    global worker
    data = request.get_json()
    if worker:
        worker.interval = data["interval"]
        worker.count = int(data["count"])
    else:
        worker = CaculationWorker2(data["count"], data["interval"])
        worker.start()

    return "OK"

@app.route('/stop', methods=['POST'])
def stop():
    global worker
    if worker:
        worker.stop()
        worker = None

    return "OK"

@app.route('/cpuload')
def cpuload():
    global worker
    if worker:
        payload = {
            "count": worker.count,      # calc count once time
            "interval": worker.interval       # interval sec between two calc
        }
        resp = make_response(payload)
        return resp

    return "OK"
'''

import os
from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor

def fibonacci(count):
    if count <= 1:
        return count

    begin = time.time()
    f, f_prev = (1, 1)
    for i in range(2, count):
        tmp = f
        f += f_prev
        f_prev = tmp
    end = time.time()

    return count, f, end-begin

def calc_sqrt(count):
    # x = 0.0001
    # for i in range(count):
    #     x += math.sqrt(x)
    for i in range(count):
        a = sqrt(i)

# Mode1: cpu load triggered by local timer
class WorkloadMgr(object):

    MAX_WORKER_NUM = 1000
    TIMER_INTERVAL = 0.02
    
    def __init__(self):
        self.count = 0
        self.executor = None
        self.timer = None

    def timer_function(self):
        if self.count != 0:
            try:
                rslt = self.executor.submit(fibonacci, self.count)
            except RuntimeError as e:
                # ignore exception which is possible when change count
                pass
            # print(rslt.result())

        # restart timer
        self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
        self.timer.start()

    def start_load(self, count):
        """ start load or change load """
        self.count = count

        if self.timer:
            self.timer.cancel()

        if self.executor:
            # wait executor exit gracfully and cancel the pending futures
            if sys.version_info.minor >= 9:
                self.executor.shutdown(wait=True, cancel_futures=True) # only for python3.9
            else:
                self.executor.shutdown(wait=True)
            # recreate new pool
            self.executor = ProcessPoolExecutor()
        else:
            # self.executor = ThreadPoolExecutor(self.MAX_WORKER_NUM)
            self.executor = ProcessPoolExecutor()

        self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
        self.timer.start()

    def stop_load(self):
        self.count = 0
        self.timer.cancel()
        if sys.version_info.minor >= 9:
            self.executor.shutdown(wait=True, cancel_futures=True)
        else:
            self.executor.shutdown(wait=True)
        self.executor = None
        
mgr = WorkloadMgr()

@app.route('/')
def index():
    """ For readiness or liveness probe. """
    return "OK"

@app.route('/start', methods=['POST'])
def start_load():
    global mgr
    data = request.get_json()
    count = int(data["count"])
    mgr.start_load(count)

    return "OK"

@app.route('/stop', methods=['POST'])
def stop_load():
    global mgr
    mgr.stop_load()

    return "OK"

@app.route('/config', methods=['GET'])
def config():
    global mgr
    payload = {
        "count": mgr.count,      # calc count once time
    }
    resp = make_response(payload)
    return resp

# Mode2: cpu load trigger from http request
executor = None
# timestamp = 0

@app.route('/cpu', methods=['POST'])
def cpu():
    global executor
    # global timestamp    
    data = request.get_json()
    count = int(data["count"])
    if executor:
        """
        now = time.time()
        interval = now - timestamp
        timestamp = now
        print("interval: {}".format(interval))
        """
        executor.submit(fibonacci, count)
    else:
        # timestamp = time.time()
        executor = ProcessPoolExecutor()
        executor.submit(fibonacci, count)

    return "OK"

@app.route('/cpuload', methods=['GET'])
def cpu_get():
    global executor
    if executor:
        """
        now = time.time()
        interval = now - timestamp
        timestamp = now
        print("interval: {}".format(interval))
        """
        executor.submit(calc_sqrt, 30000)
    else:
        # timestamp = time.time()
        executor = ProcessPoolExecutor()
        executor.submit(calc_sqrt, 30000)

if __name__ == "__main__":
    mgr.start_load(10000)
    time.sleep(30)
    mgr.stop()