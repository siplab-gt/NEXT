#!/usr/bin/python
"""
Every 6 hours backs up database to S3. To recover the database, (i.e. reverse the process)
simply download the file from S3, un-tar it, and use the command:

(./)mongorestore --host {hostname} --port {port} path/to/dump/mongodump

where {hostname} and {port} are as they are below
"""

import os
import next.constants as constants
import subprocess
import next.utils as utils
import traceback
import time
import sys
sys.path.append("/next_backend")


while (1):

    timestamp = utils.datetimeNow()
    print("[ %s ] Calling database daemon..." % str(timestamp))
    subprocess.call('python ./next/database/database_backup.py', shell=True)

    time.sleep(3600*6)  # once every 6 hours
