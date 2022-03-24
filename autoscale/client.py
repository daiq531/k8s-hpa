from threading import Thread, Timer
import time
import json
from queue import SimpleQueue
import requests
from flask import Flask, request, Response, make_response


class HttpRequestClient(Thread):

    TIMER_INTERVAL = 1
    DEFAULT_COUNT = 100000

    def __init__(self, url: str, rate: int):
        super().__init__()
        self.url = url
        self.rate = rate
        self.timer = None
        self.queue = SimpleQueue()
        self.run_flag = True

    def timer_function(self):
        current = time.monotonic()

        # caculate http request count based on rate and actual timer interval
        duration = current - self.rate_begin_time
        count = int((duration + self.TIMER_INTERVAL)
                    * self.rate / 60 - self.sent_reqs)
        if count > 0:
            self.queue.put_nowait(count)

        # restart timer
        self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
        self.timer.start()

    def run(self):
        self.sent_reqs = 0
        self.rate_begin_time = time.monotonic()
        self.timer = Timer(self.TIMER_INTERVAL, self.timer_function)
        self.timer.start()

        while self.run_flag:
            # get request count from queue
            request_count = self.queue.get()
            print("current queue size after get one: {}".format(self.queue.qsize()))
            cpu_load_duration = 0
            begin = time.monotonic()
            for i in range(request_count):
                # url format: http://server_svc_ip/cpu?count=10000
                resp = requests.get(
                    self.url, params={"count": self.DEFAULT_COUNT})
                cpu_load_duration += float(resp.text)
                resp.close()
            self.sent_reqs += request_count
            end = time.monotonic()
            total_duration = end - begin
            print("request count: {}, cpu load_duration: {}, total_duration: {}".format(
                request_count, cpu_load_duration, total_duration))
            if total_duration > self.TIMER_INTERVAL:
                print(
                    "WARNING: current configuration exceed http sending max capability, please decrease rate or DEFAULT_COUNT.")

    def change_http_rate(self, rate):
        self.queue.empty()
        self.sent_reqs = 0
        self.rate_begin_time = time.monotonic()
        self.rate = rate

    def stop(self):
        self.run_flag = False
        self.timer.cancel()


class HttpRequestClient(Thread):
    DEFAULT_COUNT = 10000

    def __init__(self, url: str, rate: int, calc_count: int):
        super().__init__()
        self.url = url
        self.rate = rate
        self.calc_count = calc_count
        self.run_flag = True
        self.client_busy_count = 0
        self.server_busy_count = 0
        self.client_max_request_latency = 0

    def run(self):
        while self.run_flag:
            begin = time.monotonic()
            resp = requests.get(self.url, params={"count": self.calc_count})
            if resp.status_code == 429:
                self.server_busy_count += 1
                print("WARNING: Server queue full because of too many request.")
            resp.close()
            end = time.monotonic()
            latency = end - begin
            if latency > self.client_max_request_latency:
                self.client_max_request_latency = latency
            sleep_time = max((1 / self.rate) - latency, 0)
            if sleep_time == 0:
                self.client_busy_count += 1
            else:
                print("sleep {}s".format(sleep_time))
            time.sleep(sleep_time)

    def change_http_rate(self, rate):
        self.rate = rate
        self.client_busy_count = 0

    def stop(self):
        self.run_flag = False
        self.client_busy_count = 0
        self.server_busy_count = 0

clientThread = None
app = Flask(__name__)


@app.route('/', methods=['GET'])
def index():
    ''' For readiness or liveness probe '''
    return 'OK'


@app.route('/start', methods=['GET', 'POST'])
def start():
    """
    Start generate load to http server deployment or query current status.
    For POST method, request body is json like below:
    {
        "target_url": "http://" + http_server_svc_ip,
        "rate": rate
    }
    For GET method, response body is json like below:
    {
        "target_url": "http://" + http_server_svc_ip,
        "rate": rate
    }
    :return: response object
    :rtype: str
    """
    global clientThread
    if request.method == "POST":
        data = request.get_json()
        if not clientThread:
            print("start http traffic: url: {}, rate: {}".format(
                data["target_url"], data["rate"]))
            clientThread = HttpRequestClient(url=data["target_url"],
                                             rate=int(data["rate"]),
                                             calc_count=int(data["calc_count"]))
            clientThread.start()
            return make_response(("create http traffic client success.", 200))
        else:
            if data["target_url"] == clientThread.url:
                print("change http traffic rate: {}".format(data["rate"]))
                clientThread.change_http_rate(int(data["rate"]))
                return make_response(("change http traffic client rate success.", 200))
            else:
                print("target url are different from original one.")
                return make_response(("target url are different from original one.", 400))
    else:
        if clientThread:
            data = {
                "target_url": clientThread.url,
                "rate": clientThread.rate
            }
            return make_response(data)
        else:
            return make_response(("please start http traffic client first.", 400))


@app.route('/stop', methods=['POST'])
def stop():
    global clientThread
    data = request.get_json()
    if clientThread:
        if data["target_url"] == clientThread.url:
            print("stop http traffic.")
            clientThread.stop()
            clientThread = None
            return make_response(("stop http traffic client success.", 200))
        else:
            print("target url are different from original one.")
            return make_response(("target url are different from original one.", 400))

    return make_response(("please start http traffic client first.", 400))

@app.route('/statistic', methods=["GET"])
def statistic():
    global clientThread
    if clientThread:
        data = {
            "client_busy_count": clientThread.client_busy_count,
            "client_max_request_latency": clientThread.client_max_request_latency,
            "server_busy_count": clientThread.server_busy_count
        }
        resp = make_response(data)
        return resp
    else:
        return make_response(("please start http traffic client first.", 400))