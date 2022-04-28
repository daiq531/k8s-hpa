# from sre_constants import SUCCESS
from threading import Thread, Timer
import threading
import time
import sys
import requests

from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor

rate = 100
req_url = "http://172.30.100.212/cpuload.php"

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

    payload = {
        "count": count
    }
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
        resp.close()

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
            expected = (time.time() - self.start_timestamp) * rate
            rate_error = ((expected - SENT) / SENT) * 100
            print(f"STATUS"
                  f" - threads: {threading.active_count()}"
                  f" - pass/fail:  {SUCCESS}/{FAIL}"
                  f" - rate_error: {rate_error:.2f}%")
        
        http_requst_cnt = int((time.time() - self.start_timestamp) * self.rate) - self.req_sent
        
        # Add an IF statement to prevent sending requests when none are required (for rates < loops/second)
        if http_requst_cnt > 0:
            try:
                # add the request count to the timer function, instead of starting a thread for each requests.
                #  this way, only 1 thread is created per timer interval.
                self.executor.submit(send_http_request, self.target_url, self.count, http_requst_cnt)
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

    def change_config(self, rate, count):
        self.count = count

        if rate != self.rate:
            self.timer.cancel()

            self.rate = rate
            self.req_sent = 0
            self.start_timestamp = time.time()

            # flush executor to make new config take effect quicker
            if sys.version_info.minor >= 9:
                self.executor.shutdown(wait=True, cancel_futures=True)
            else:
                self.executor.shutdown(wait=True)
            # self.executor = ThreadPoolExecutor(self.MAX_WORKER_NUM)
            self.executor = ProcessPoolExecutor()

            self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
            self.timer.start()

    def stop(self):
        if self.timer:
            self.timer.cancel()
        if self.executor:
            if sys.version_info.minor >= 9:
                self.executor.shutdown(wait=True, cancel_futures=True)
            else:
                self.executor.shutdown(wait=True)

generator = HTTPRequestLoadGenerator(req_url)
generator.start(rate=rate, count=500)

time.sleep(1000)