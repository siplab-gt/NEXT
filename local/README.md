# Running NEXT locally
This document contains instructions on how to run a NEXT experiment on your local machine.


## Dependencies

To start the NEXT backend, you need a machine with the following things installed:

```
docker
docker-compose
python3.11
```

`docker` can be installed via the [Docker install guide]. `docker-compose` can
be installed via `pip install docker-compose`.

Optionally, you need extra packages located in `local/requirements.txt` to run the `launch.py` and `stress_test.py` scripts in this directory:

`python -m venv venv`
`source venv/bin/activate`
`pip install -r requirements.txt`


### Using MacOS
If using MacOS/OS X, download [Docker for Mac], not [Docker Toolbox] It
provides an easier interface to get started.

[Docker for Mac]:https://docs.docker.com/engine/installation/mac/#/docker-for-mac

[Docker install guide]:https://docs.docker.com/v1.8/installation/

[Docker Toolbox]:https://www.docker.com/products/docker-toolbox


## Starting the backend

First clone this repository and navigate to the `NEXT/local/` directory.

To start up the NEXT backend, run `./docker_up.sh [host]` where `host`
is the IP or hostname of the machine running the backend.  You may
optionally provide a path to the repo if you are running the
`docker_up` script from a different directory.  For example:

```
./docker_up.sh [host] [/path/to/NEXT]
```

The default will assume host is `localhost` and `NEXT` is located at `../../`:

Note: The default setting of `localhost` can be used when deploying on AWS with this setup because NGINX in now included in the docker network.
Make sure to change the `server_name` variable in the `local/nginx.conf` file to the IP address associated with your AWS instance. You will also need to open up port 80 on your AWS instace.

```
./docker_up.sh
```

The first time you run this, docker will download and build the images, which will take a few minutes.

If you make changes to your docker setup, you may need to rebuild the dockers with `docker-compose build`.

Once the backend is launched, you should be able to go to `http://localhost:8000/home` or `http://AWS_INSTANCE_IP/home` to see the NEXT homepage.


## Starting an experiment

Once the backend is running you can launch an experiment.  To set up an experiment, you need to create a yaml file specifying all
the required parameters and data. See `NEXT/local/strange_fruit_triplet/init.yaml`
for an example.  This `init.yaml` file is nearly identical to the files in `NEXT/examples`,
except that the targets information is specified explicitly (rather than generated when uploaded to the EC2 server).

Additionally, if your targets are images/videos/audio, they need to be hosted somewhere.
The example **strange_fruit_triplet** example assumes the files are hosted on `localhost:8999`,
which can be achieved by running
`python -m SimpleHTTPServer 8999` in the directory that contains the images (e.g.
`NEXT/local/strange_fruit_triplet/images/`). This can be run on the AWS instance to serve the media files for the NEXT backend.

You can launch an experiment by clicking on the *Experiment launch* link on the NEXT homepage and uploading the
appropriate `init.yaml` file (no need to specify a targets file).
Alternatively, you can launch the experiment by running:
```bash
python launch.py strange_fruit_triplet/init.yaml
```


## Creating your own experiments
To run any of the remaining examples in `NEXT/examples/`:

1. Copy the appropriate directory from `NEXT/examples/`
2. Modify the `init.yaml` file to include the appropriate information about the targets.
3. Host the image(s)/video(s)/audio by running `python -m SimpleHTTPServer 8999` in the appropriate directory.
4. Start the experiment through the *Experiment launch* interface or by running `python launch.py path/to/init.yaml`

To create your own experiments, simply create a new `init.yaml` with the appropriate configuration
and follow the same steps. Note that if your targets are just text, you may skip the hosting step
and simply include the data in the `init.yaml` file.

