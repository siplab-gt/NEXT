FROM python:3.11.9
MAINTAINER Konstantine Tsafatinos, konstantine.tsafatinos@neuromatch.io

# Install MongoDB and its tools
RUN wget -qO - https://www.mongodb.org/static/pgp/server-4.4.asc | apt-key add -
RUN echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/debian buster/mongodb-org/4.4 main" | tee /etc/apt/sources.list.d/mongodb-org-4.4.list
RUN echo "deb http://security.debian.org/debian-security buster/updates main" >> /etc/apt/sources.list
RUN apt-get update -y && apt-get upgrade -y
RUN apt-get install -y libssl1.1
RUN apt-get install -y mongodb-org

# Install python dependencies for next_backend
ADD requirements.txt /requirements.txt
RUN pip install -U -r requirements.txt
