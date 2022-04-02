import math
import time
import os
from threading import Thread
from multiprocessing import Process, Pool, Queue
from queue import Full
from flask import Flask, request, make_response


app = Flask(__name__)

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
    ''' For readiness or liveness probe. '''
    return "OK"

@app.route('/start', methods=['POST'])
def start():
    '''
    Accept configuration from client to generate cpu load.
    Http body is json format like below:
    {
        "count": 10000      # calc count once time
        "interval": 1       # interval sec between two calc
    }    
    '''
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