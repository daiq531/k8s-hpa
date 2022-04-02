from threading import Thread, Timer
import time
import json
from queue import SimpleQueue
import requests
from flask import Flask, request, Response, make_response


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
'''
# below is new solution Klaus suggested
@app.route('/start', methods=['POST'])
def start():

    Accept configuration from user script to generate cpu load on one pod.
    Http body is json format like below:
    {
        "pod_ip": 172.1.1.1 # server pod ip
        "count": 10000      # calc count once time
        "interval": 1       # interval sec between two calc
    }

    data = request.get_json()
    url = "http://" + data["pod_ip"] + ":8080/cpu"
    payload = {
        "count": data["count"],
        "interval": data["interval"]
    }
    resp = requests.post(url, json=payload)
    if 200 != resp.status_code:
        print("set pod cpu load fail. {}".format(str(data)))
        resp = make_response("set pod cpu load fail. {}".format(str(data)), resp.status_code)
        return resp
    else:
        print("set pod cpu load success. {}".format(str(data)))
        resp = make_response("set pod cpu load success. {}".format(str(data)), 200)
        return resp

@app.route('/cpuload', methods=['POST'])
def stop():

    Accept configuration from user script to generate cpu load on one pod.
    Http body is json format like below:
    {
        "pod_ip": 172.1.1.1 # server pod ip
    }

'''