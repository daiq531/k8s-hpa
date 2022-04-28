from threading import Thread, Timer
import threading
import time
import sys
import requests
from datetime import datetime

from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor

rate = 500

SENT = 0
LAST50 = datetime.now()

def send_http_request(url, count):
    global SENT
    global LAST50
    payload = {
        "count": count
    }
    SENT += 1
    if SENT % rate == 0:
        print(f"sent {rate} - {(datetime.now() - LAST50).total_seconds()} - threads: {threading.active_count()}")
        LAST50 = datetime.now()
    resp = requests.get(url)
    resp.close()

class HTTPRequestLoadGenerator(object):

    MAX_WORKER_NUM = 5000
    TIMER_INTERVAL = 0.02

    def __init__(self, target_url):
        self.target_url = target_url

        self.timer = None
        self.executor = None
        self.rate = 0
        self.count = 0
        self.req_sent = 0

    def timer_function(self):
        http_requst_cnt = int((time.time() - self.start_timestamp) * self.rate) - self.req_sent
        # http_requst_cnt = int(self.TIMER_INTERVAL * self.rate)
        for i in range(http_requst_cnt):
            try:
                self.executor.submit(send_http_request, self.target_url, self.count)
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

generator = HTTPRequestLoadGenerator("http://172.30.10.46/cpuload.php")
generator.start(rate=rate, count=500)
time.sleep(1000)