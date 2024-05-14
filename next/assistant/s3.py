import boto3
import next.utils as utils
from pprint import pprint

# TODO: grab from env
AWS_ID =  ''
AWS_KEY = ''

# Initialize a session using your AWS credentials
session = boto3.Session(
    aws_access_key_id=AWS_ID,
    aws_secret_access_key=AWS_KEY
)

# Use the session to create S3 resource
s3 = session.resource('s3')

def create_bucket(AWS_BUCKET_NAME):
    """
    Creates a bucket for an S3 account
    """
    bucket = s3.create_bucket(Bucket=AWS_BUCKET_NAME)
    return bucket

def get_bucket(AWS_BUCKET_NAME):
    """
    Retrieves a bucket object
    """
    bucket = s3.Bucket(AWS_BUCKET_NAME)
    # If you need to verify the bucket exists on S3, use the following:
    exists = True
    try:
        s3.meta.client.head_bucket(Bucket=AWS_BUCKET_NAME)
    except boto3.exceptions.botocore.exceptions.ClientError as e:
        # If a client error is thrown, check that it was a 404 error.
        # If it was a 404 error, then the bucket does not exist.
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            exists = False
    return bucket if exists else None

def upload(filename, file_object, AWS_BUCKET_NAME):
    """
    Uploads a file object to an S3 bucket
    """
    object = s3.Object(AWS_BUCKET_NAME, filename)
    object.put(Body=file_object)
    object.Acl().put(ACL='public-read')

    # Generate the URL
    url = "http://{}.s3.amazonaws.com/{}".format(AWS_BUCKET_NAME, filename)
    return url

# Note: AWS_ID and AWS_KEY are your AWS credentials.
# Remove them from function arguments if you're using a session or handling
# credentials in a different way (e.g., via environment variables or IAM roles).
