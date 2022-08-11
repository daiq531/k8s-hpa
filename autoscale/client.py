from threading import Thread, Timer
import threading
from datetime import datetime
import time
import sys
import json
import requests
from flask import Flask, request, Response, make_response
from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    """ For readiness or liveness probe """
    return 'OK'

# Global variables threads will increment for each request (keeps totals for all threads)
SUCCESS = 0
FAIL = 0
SENT = 0

# Interval in seconds to print pass/fail and rate accuracy statistics.
REPORT_RATE = 2

def send_http_request(url, count, req_cnt=1):
    # Global sent, pass, and fail vairables
    global SUCCESS
    global FAIL
    global SENT

    # Send the number of requests required for the timer loop to maintain specified rate.
    for _ in range(0, req_cnt):
        # increment the sent counter
        SENT += 1
        resp = requests.get(url)
        # Increment pass/fail counters depending on the results from the request
        if resp.status_code == 200:
            SUCCESS += 1
        else:
            FAIL += 1
        # resp.close()

class HTTPRequestLoadGenerator(object):

    MAX_WORKER_NUM = 500
    TIMER_INTERVAL = 0.02

    # Additional class properties to allow triggering of status every 1 second.
    interval_per_second = int(1/TIMER_INTERVAL)
    timer_loop_cnt = 0

    def __init__(self, target_url):
        self.target_url = target_url
        
        self.timer = None
        self.executor = None
        self.rate = 0
        self.count = 0
        self.req_sent = 0
        
    def timer_function(self):
        # Global variables to track ACTUAL requests and pass/fail
        global SUCCESS
        global FAIL
        global SENT

        # Print status if the number of timer loops is divisible by the loop rate * REPORT_RATE.
        self.timer_loop_cnt += 1
        if self.timer_loop_cnt % (self.interval_per_second * REPORT_RATE) == 0:
            expected = (time.time() - self.start_timestamp) * self.rate
            rate_error = ((expected - SENT) / expected) * 100
            print(f"{time.asctime(time.gmtime())}"
                  f" - threads: {threading.active_count()}"
                  f" - pass/fail:  {SUCCESS}/{FAIL}"
                  f" - rate_error: {rate_error:.2f}%")

        http_requst_cnt = int((time.time() - self.start_timestamp) * self.rate) - self.req_sent
        # http_requst_cnt = int(self.TIMER_INTERVAL * self.rate)
        # Add an IF statement to prevent sending requests when none are required (for rates < loops/second)
        if http_requst_cnt > 0:
            try:
                # add the request count to the timer function, instead of starting a thread for each requests.
                #  this way, only 1 thread is created per timer interval.
                f = self.executor.submit(send_http_request, self.target_url, self.count, http_requst_cnt)
                # if f.exception():
                #    print(f.exception())
            except RuntimeError:
                # ignore possible run time error when changing rate
                pass
            self.req_sent += http_requst_cnt

        self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
        self.timer.start()

    def start(self, rate, count):
        self.rate = rate
        self.count = count

        self.executor = ThreadPoolExecutor(self.MAX_WORKER_NUM)
        # self.executor = ProcessPoolExecutor()

        self.start_timestamp = time.time()
        self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
        self.timer.start()

    def reset_global_vars(self):
        global SUCCESS
        global FAIL
        global SENT        
        SUCCESS = 0
        FAIL = 0
        SENT = 0

    def change_config(self, rate, count):
        self.count = count

        if rate != self.rate:
            self.timer.cancel()

            self.rate = rate
            self.req_sent = 0
            self.start_timestamp = time.time()

            # flush executor to make new config take effect quicker
            if sys.version_info.minor >= 9:
                self.executor.shutdown(wait=False, cancel_futures=True)
            else:
                self.executor.shutdown(wait=False)
            self.reset_global_vars()
            self.executor = ThreadPoolExecutor(self.MAX_WORKER_NUM)
            # self.executor = ProcessPoolExecutor()

            self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
            self.timer.start()

    def stop(self):
        if self.timer:
            self.timer.cancel()
        if self.executor:
            if sys.version_info.minor >= 9:
                self.executor.shutdown(wait=False, cancel_futures=True)
            else:
                self.executor.shutdown(wait=False)
        self.reset_global_vars()

generator = None

# below is new solution Klaus suggested
@app.route('/start', methods=['POST'])
def start():
    """
    Accept configuration from user script to generate cpu load on one pod.
    Http body is json format like below:
    {
        "target_url": "http://svc_ip/cpu"  # server service url
        "count": 10000              # calc count once time
        "rate": 10                  # http rate
    }
    """
    global generator
    data = request.get_json()
    if generator:
        generator.change_config(data["rate"], data["count"])
    else:
        generator = HTTPRequestLoadGenerator(data["target_url"])
        generator.start(rate=data["rate"], count=data["count"])

    return "OK"

@app.route('/stop', methods=['POST'])
def stop():
    global generator
    if generator:
        generator.stop()
        generator = None

    return "OK"

@app.route('/config', methods=['GET'])
def get_config():
    global generator
    if generator:
        data = {
            "target_url": generator.target_url,
            "count": generator.count, 
            "rate": generator.rate
        }
        resp = make_response(data)
        return resp
    else:
        return make_response(("please start http traffic client first.", 400))