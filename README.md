# k8s-hpa

This project is used for testing HPA in K8S. Actually it is one helm chart directory named by autoscale. 

Internally the release created by this chart will deploy one php server deployment with HPA configuration and one http client deployment without HPA configuration. The user script in CSure will call the API provided by http client to make client generate one fixed http request rate to the server, which will cause different load to trigger server deployment auto scale out or auto scale in.

On server side, some PHP scripts are deployed in server pod when release is created. These PHP script will consume CPU or memory once it receive http requests. In order to simulate multiple client request in parralell and mitigate http request sync waiting, thread pool executor is used in client python script.

In fastcgi directory there is one fastcgi app implementation in C language. It's one attempt to make memory consumption more precise due to C language can control memory more clearly. But unfortnately it will segment fault crash when recieving multiple continuous request with unknown reason. 

There are some piece of code in other dir which are provided by Mark or some trial script by me.

The user scripts in root dir can be run in CSure NFVI_LGC_HELM3_GENERIC_01 test case. The final user script file is userscript.py in root dir. Other python file in root dir are trial scripts.