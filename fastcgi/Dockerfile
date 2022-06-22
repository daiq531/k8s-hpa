FROM debian

RUN apt update; apt install -y gcc libfcgi-dev libfcgi-bin

COPY . /usr/src/myapp
WORKDIR /usr/src/myapp
RUN gcc main.c -lfcgi -o app.fcgi
CMD ["cgi-fcgi", "-connect", "0.0.0.0:2016", "app.fcgi"]
