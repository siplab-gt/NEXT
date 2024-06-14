"""
Usage:
    launch.py <init_filename>
    launch.py <init_filename> <targets_path>

Arguments:
    initExp_path (required) : path to a YAML file for arguments to launch experiment
    targets_path (optional) : yaml file that contains the targets information

Options:
    -h, --help

Example:

    > cd ~/Developer/NEXT/local/
    > python launch.py strange_fruit_triplet/init.yaml strange_fruit_triplet/targets.yaml

"""

from docopt import docopt
import os
import sys
from collections import OrderedDict
import base64
import yaml
import requests

sys.path.append('../next/lib')


def get_backend():
    """
    Get the backend host and port.

    Defaults to dict(host='localhost', port=8000).
    """
    return {
        'host': os.environ.get('NEXT_BACKEND_GLOBAL_HOST', 'localhost'),
        'port': os.environ.get('NEXT_BACKEND_GLOBAL_PORT', '8000')
    }


def launch(init_filename, targets_filename=None):
    with open(init_filename, 'r') as f:
        init = yaml.load(f, Loader=yaml.SafeLoader)

    if targets_filename:
        with open(targets_filename, 'r') as f:
            targets = yaml.load(f, Loader=yaml.SafeLoader)

            if 'targets' not in init['args']:
                init['args']['targets'] = {'targetset': []}
            init['args']['targets']['targetset'] = targets

    # -- encode the experiment definition for transmission to the backend
    data_header = "data:application/x-yaml;base64,"

    byte64_args = base64.b64encode(yaml.dump(init).encode('utf-8'))
    str_encoded_args = byte64_args.decode('utf-8')
    encoded_attrs = OrderedDict(args=data_header+str_encoded_args)

    # generate metadata describing each attr's length; this is prepended to the request data.
    metadata = ';'.join(['{}:{}'.format(k, len(v))
                        for k, v in list(encoded_attrs.items())])

    # concat all the encoded attrs together
    body = ''.join([v for _, v in list(encoded_attrs.items())])

    # what we're actually going to send
    payload = metadata + '\n' + body

    # -- send the packed experiment definition file
    host = get_backend()
    host_url = "http://{host}:{port}".format(**host)

    r = requests.post(host_url + '/assistant/init/experiment', data=payload)
    response = r.json()

    if not response['success']:
        print('An error occurred launching the experiment:')
        print((response['message']))
        sys.exit()

    dashboard_url = host_url + \
        '/dashboard/experiment_dashboard/{}/{}'.format(
            response['exp_uid'], init['app_id'])
    print(('Dashboard URL: {}'.format(dashboard_url)))
    print(('NEXT Home URL: {}'.format(host_url + '/home')))

    return response


if __name__ == "__main__":
    args = docopt(__doc__)
    launch(args['<init_filename>'], targets_filename=args['<targets_path>'])
