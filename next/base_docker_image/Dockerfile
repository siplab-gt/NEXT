FROM python:3.11.9
MAINTAINER Konstantine Tsafatinos, konstantine.tsafatinos@neuromatch.io


# Install dependencies for Miniconda
# RUN apt-get update && apt-get install -y wget bzip2 && rm -rf /var/lib/apt/lists/*
# ENV CONDA_DIR=/opt/conda
# ENV PATH=$CONDA_DIR/bin:$PATH
# RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
#     bash /tmp/miniconda.sh -b -p $CONDA_DIR && \
#     rm /tmp/miniconda.sh && \
#     conda clean -tipsy
# COPY environment.yml /tmp/environment.yml
# RUN conda env create -f /tmp/environment.yml && \
#     conda clean -a -y
# RUN echo "source activate infotuple_test_env" > ~/.bashrc
# ENV PATH /opt/conda/envs/infotuple_test_env/bin:$PATH



# Install MongoDB and its tools
RUN wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | apt-key add -
RUN echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" | tee /etc/apt/sources.list.d/mongodb-org-7.0.list
RUN apt-get update -y && apt-get upgrade -y
RUN apt-get install -y libssl3
RUN apt-get install -y mongodb-org
RUN apt-get install -y libgl1-mesa-glx  # Install OpenGL libraries for video processing

# Install python dependencies for next_backend
RUN python -m pip install --upgrade pip
ADD requirements.txt /requirements.txt
RUN pip install -U -r requirements.txt
