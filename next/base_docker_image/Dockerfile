FROM python:3.11.9
# MAINTAINER Lalit Jain, lalitkumarj@gmail.com

# Install MongoDB and its tools
# RUN \
#   # wget -qO - https://www.mongodb.org/static/pgp/server-6.0.asc | apt-key add - && \
#   # echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/debian buster/mongodb-org/6.0 main" | tee /etc/apt/sources.list.d/mongodb-org-6.0.list && \
#   #
#   wget -qO - https://www.mongodb.org/static/pgp/server-4.4.asc | apt-key add - && \
#   echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/debian buster/mongodb-org/4.4 main" | tee /etc/apt/sources.list.d/mongodb-org-4.4.list && \
# 	  # apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 2930ADAE8CAF5059EE73BB4B58712A2291FA4AD5 && \
#     # echo "deb http://repo.mongodb.org/apt/debian stretch/mongodb-org/3.6 main" | tee /etc/apt/sources.list.d/mongodb-org-3.6.list && \
#     # echo "deb http://ftp.debian.org/debian stretch-backports main" > /etc/apt/sources.list && \
# 	apt-get update -y && \
# 	apt-get install -y mongodb-org

RUN wget -qO - https://www.mongodb.org/static/pgp/server-4.4.asc | apt-key add -
RUN echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/debian buster/mongodb-org/4.4 main" | tee /etc/apt/sources.list.d/mongodb-org-4.4.list
RUN echo "deb http://security.debian.org/debian-security buster/updates main" >> /etc/apt/sources.list
RUN apt-get update -y && apt-get upgrade -y
RUN apt-get install -y libssl1.1
RUN apt-get install -y mongodb-org

# Install python dependencies for next_backend
ADD requirements.txt /requirements.txt
# RUN pip uninstall -y setuptools
# RUN pip install -U "setuptools<58.0.0" wheel
RUN pip install -U -r requirements.txt
