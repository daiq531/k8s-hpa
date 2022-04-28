# Flask container image

The purpose of this image to provide server/client capability to test HPA using a single image.

- `app.py` runs as flask app's entrypoint.
- `Dockerfile` to build container image
- `cpuload.py` will be used by server side app to generate cpu load
- `httpclient.py` will be exposed using K8S service to external network, which will accept GET call and initiate traffic to server app