import json
import os
from datetime import datetime

from core.analyzer import DbtProjectAnalyzer
from .aws.api_gateway import parse_event_body
from .aws.dynamodb import DynamoDB
from .aws.sqs import SQS

DYNAMODB_TABLE_NAME = 'dbt-github-analyzer-status-table'
SQS_QUEUE_NAME = 'dbt-github-analyzer-task-queue'


# Lambda Handler Functions
def receiver(event, context):
    body = parse_event_body(event)
    if body.get('github_url') is None:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "github_url is required",
            }),
        }

    # Send message to SQS
    ret = SQS.factory(SQS_QUEUE_NAME).send_message(message=body)
    task_id = ret['MessageId']

    db = DynamoDB.factory(DYNAMODB_TABLE_NAME)
    db.put_item({
        'task_id': task_id,
        'task_status': 'pending',
        'created_at': datetime.utcnow().isoformat()
    })

    return {
        "statusCode": 202,
        "body": json.dumps({
            "message": "ok",
            'task_id': task_id,
        }),
    }


def analyze(payload):
    github_url = payload.get('github_url')
    if github_url is None:
        raise Exception('github_url is required')

    print('[Handling Request]')
    print('github_url: ', github_url)
    print('github_token: ', payload.get('github_token'))
    print('piperider_api_service', payload.get('piperider_api_service'))
    print('piperider_api_token', "******" if payload.get('piperider_api_token') else None)
    print('piperider_project', payload.get('piperider_project'))

    if payload.get('github_token'):
        # Set GitHub Token to environment variable
        os.environ['GITHUB_TOKEN'] = payload.get('github_token')

    if payload.get('piperider_api_service'):
        # Set Piperider API Service to environment variable
        os.environ['PIPERIDER_API_SERVICE'] = payload.get('piperider_api_service')

    piperider_token = payload.get('piperider_api_token')
    piperider_project = payload.get('piperider_project')

    upload: bool = True if piperider_token and piperider_project else False

    analyzer = DbtProjectAnalyzer(github_url, api_token=piperider_token, project_name=piperider_project, upload=upload)
    # TODO: handle exception
    reason = ''
    try:
        analyzer.analyze()
        status = 'completed'
    except BaseException as e:
        print(f'Error: {str(e)}')
        reason = str(e)
        status = 'failed'

    if analyzer.results['compare']:
        report = analyzer.results['compare'].report
    elif analyzer.results['base']:
        report = analyzer.results['base'].report
    else:
        report = None
        status = 'failed'

    # TODO: return the report URL
    return status, report, reason


def processor(event, context):
    # TODO: get options from SQS message
    db = DynamoDB.factory(DYNAMODB_TABLE_NAME)

    for record in event.get('Records', []):
        try:
            task_id = record.get('messageId')
            body = json.loads(record.get('body'))
            db.update_item(
                key={'task_id': task_id},
                update_expression='SET task_status = :status',
                expression_attribute_values={':status': 'processing'},
            )
            status, report, reason = analyze(body)
            # TODO: update task status to DynamoDB with report URL
            # TODO: save failed reason if status is failed
            db.update_item(
                key={'task_id': task_id},
                update_expression='SET task_status = :status, report_url = :report, reason = :reason',
                expression_attribute_values={':status': status, ':report': report, ':reason': reason},
            )
            pass
        except Exception as e:
            print(f"Error processing record {record.get('messageId')}: {str(e)}")
            continue
        finally:
            pass


def status_checker(event, context):
    path_params = event.get('pathParameters')
    task_id = path_params.get('task_id')
    if task_id is None:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "task_id is required",
            }),
        }

    db = DynamoDB.factory(DYNAMODB_TABLE_NAME)
    task = db.get_item({'task_id': task_id})
    if task is None:
        return {
            "statusCode": 410,
            "body": json.dumps({
                "message": "task not found",
            }),
        }

    status = task.get('task_status')
    if status == 'completed':
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": status,
                "message": "ok",
                "report_url": task.get('report_url'),
            }),
        }
    elif status == 'failed':
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": status,
                "reason": task.get('reason'),
            }),
        }

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": task.get('task_status'),
            "message": "ok",
        }),
    }


if __name__ == '__main__':
    import os.path

    event_file = os.path.join(os.path.dirname(__file__), 'events', 'receiver_api_gateway_event.json')

    with open(event_file) as f:
        from rich.console import Console

        console = Console()
        mock_event = json.load(f)
        response = receiver(mock_event, None)
        console.print(response)
