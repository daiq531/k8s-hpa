import requests
import time

count = 0
while(1):
    resp = requests.get("http://10.109.222.9/memload.php?print=qdai")
    #print(resp.text)
    count += 1
    print(count)
    if count >= 10000:
        break
    time.sleep(0.002)

