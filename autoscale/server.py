import math
import time
import os
from multiprocessing import Process, Pool, Queue
from queue import Full
from flask import Flask, request, make_response

app = Flask(__name__)
queue = Queue(os.cpu_count())

class CaculationWorker(Process):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
    
    def run(self):
        while(True):
            count = self.queue.get()
            x = 0.0001
            start = time.monotonic()
            for i in range(count):
                x += math.sqrt(x)
            end = time.monotonic()
            print("pid: {}, count: {}, time: {}".format(self.pid, count, end - start))

workers = []
for i in range(os.cpu_count()):
    worker = CaculationWorker(queue)
    workers.append(worker)
    worker.start()
print("created {} worker process".format(os.cpu_count()))

@app.route('/')
def index():
    ''' For readiness or liveness probe. '''
    return "OK"

@app.route('/cpu')
def consume_cpu():
    global queue
    count = request.args.get("count", type=int)
    try:
        queue.put_nowait(count)
    except Full:
        return make_response(("Too Many Requests", 429))

    return "OK"