import math
import time
from flask import Flask, request

app = Flask(__name__)

@app.route('/')
def index():
    ''' For readiness or liveness probe. '''
    return "OK"

@app.route('/cpu')
def consume_cpu():
    count = request.args.get("count", default=1000000, type=int)
    x = 0.0001
    start = time.monotonic()
    for i in range(1, count):
        x += math.sqrt(x)
    end = time.monotonic()
    return str(end - start)
