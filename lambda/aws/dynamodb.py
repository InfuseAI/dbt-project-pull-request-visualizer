import os
from abc import ABCMeta, abstractmethod

import boto3

region = os.environ.get('AWS_REGION', 'us-east-1')
DEBUG = os.environ.get('DEBUG', 'true')
LOCALHOST = os.environ.get('LOCALHOST', 'localhost')
LOCAL_DYNAMODB_ENDPOINT_URL = f'http://{LOCALHOST}:8000'


class DynamoDB(metaclass=ABCMeta):
    @staticmethod
    def factory(table_name: str):
        if DEBUG == 'false':
            return AwsDynamoDB(table_name)
        else:
            return LocalDynamoDB(table_name)

    @abstractmethod
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.table = None
        raise NotImplementedError

    def put_item(self, item: dict):
        return self.table.put_item(Item=item)

    def get_item(self, key: dict):
        response = self.table.get_item(Key=key)
        return response.get('Item')

    def update_item(self, key: dict, update_expression: str, expression_attribute_values: dict):
        return self.table.update_item(
            Key=key,
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values)


class AwsDynamoDB(DynamoDB):
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.table = self.dynamodb.Table(self.table_name)


class LocalDynamoDB(DynamoDB):
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.dynamodb = boto3.resource('dynamodb', endpoint_url=LOCAL_DYNAMODB_ENDPOINT_URL)
        if table_name not in self.dynamodb.meta.client.list_tables()['TableNames']:
            # Create table
            self.dynamodb.create_table(
                TableName=table_name,
                KeySchema=[
                    {
                        'AttributeName': 'task_id',
                        'KeyType': 'HASH'
                    },
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'task_id',
                        'AttributeType': 'S'
                    },
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
        self.table = self.dynamodb.Table(self.table_name)
