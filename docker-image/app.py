from flask import Flask
from cpuload import cpuload
from httpclient import httpclient
app = Flask(__name__)

""" This URL will be called by http client app. As the client app hits this URL, 
    cpuload function will be called and generate CPU load.
    Check cpuload.py for more information. """
@app.route('/cpu')
def firstapp():
    f = cpuload()
    return f

""" This URL will be called by python script. With GET call to this URL, httpclient function will be called.
    httpclient function is intent to call this app's cpuload function (http://FQDN/cpu).
    Check httpclient.py for more information. """
@app.route('/')
def get():
    h = httpclient()
    return h