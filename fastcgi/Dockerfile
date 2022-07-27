FROM debian

RUN apt update; apt install -y gcc libfcgi-dev libfcgi-bin spawn-fcgi

COPY . /usr/src/myapp
WORKDIR /usr/src/myapp
RUN gcc main.c -g -lfcgi -lpthread -o app.fcgi
# CMD ["cgi-fcgi", "-connect", "0.0.0.0:2016", "app.fcgi"]
CMD ["spawn-fcgi", "-n", "-a", "127.0.0.1", "-p", "9100", "app.fcgi"]
