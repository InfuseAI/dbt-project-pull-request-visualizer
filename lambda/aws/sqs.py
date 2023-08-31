import json
import os
from abc import ABCMeta, abstractmethod

import boto3
from botocore.exceptions import ClientError

region = os.environ.get('AWS_REGION', 'us-east-1')
DEBUG = os.environ.get('DEBUG', 'true')
LOCALHOST = os.environ.get('LOCALHOST', 'localhost')
LOCAL_SQS_ENDPOINT_URL = f'http://{LOCALHOST}:9324'


class SQS(metaclass=ABCMeta):
    @staticmethod
    def factory(queue_name: str):
        if DEBUG == 'false':
            return AwsSQS(queue_name)
        return LocalSQS(queue_name)

    @abstractmethod
    def __init__(self, queue_name: str):
        self.queue = None
        raise NotImplementedError

    def send_message(self, message: dict):
        return self.queue.send_message(MessageBody=json.dumps(message))


class AwsSQS(SQS):
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.sqs = boto3.resource('sqs', region_name=region)

        self.queue = self.sqs.get_queue_by_name(QueueName=queue_name)


class LocalSQS(SQS):
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.sqs = boto3.resource('sqs', endpoint_url=LOCAL_SQS_ENDPOINT_URL)
        try:
            self.queue = self.sqs.get_queue_by_name(QueueName=queue_name)
        except ClientError as e:
            if e.response['Error']['Code'] == 'AWS.SimpleQueueService.NonExistentQueue':
                self.queue = self.sqs.create_queue(QueueName=queue_name)
            else:
                raise e
