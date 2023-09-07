from rich.console import Console

from ..app import SQS_QUEUE_NAME
from ..aws.sqs import SQS

console = Console()


def sqs_runner():
    sqs = SQS.factory(SQS_QUEUE_NAME).queue

    messages = sqs.receive_messages(
        AttributeNames=['All'],
        MaxNumberOfMessages=10,
        WaitTimeSeconds=10,
    )
    lambda_event_payload = {
        'Records': []
    }

    for msg in messages:
        record_payload = {
            'body': msg.body,
            'messageId': msg.message_id,
        }
        lambda_event_payload['Records'].append(record_payload)
        console.log(f'Processing message: {record_payload}')
        msg.delete()

    if len(lambda_event_payload['Records']) > 0:
        # Invoke lambda function
        from ..app import processor
        processor(lambda_event_payload, None)


if __name__ == '__main__':
    console.log('Starting local SQS runner')
    console.log(f'Waiting for messages from {SQS_QUEUE_NAME}...')
    while True:
        try:
            sqs_runner()
        except Exception as e:
            console.log(f'Error: {str(e)}')
            continue
