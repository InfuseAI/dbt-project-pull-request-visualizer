import json
import os
from datetime import datetime

import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

from core.analyzer import DbtProjectAnalyzer, AnalyzerEventHandler
from core.utils import parse_github_url
from .aws.api_gateway import parse_event_body
from .aws.dynamodb import DynamoDB
from .aws.sqs import SQS

DYNAMODB_TABLE_NAME = 'dbt-github-analyzer-status-table'
SQS_QUEUE_NAME = 'dbt-github-analyzer-task-queue'
SENTRY_DNS = os.environ.get('SENTRY_DNS', None)

if SENTRY_DNS:
    sentry_sdk.init(
        dsn=SENTRY_DNS,
        integrations=[AwsLambdaIntegration(timeout_warning=True)],
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=1.0,
    )


# Lambda Handler Functions
def receiver(event, context):
    try:
        body = parse_event_body(event)
        if body.get('github_url') is None:
            raise Exception('github_url is required')
        analysis_type, pr_id, repo_name = parse_github_url(body.get('github_url'))
    except Exception as e:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": str(e),
            }),
        }

    # Send message to SQS
    ret = SQS.factory(SQS_QUEUE_NAME).send_message(message=body)
    task_id = ret['MessageId']

    db = DynamoDB.factory(DYNAMODB_TABLE_NAME)
    db.put_item({
        'task_id': task_id,
        'task_status': 'pending',
        'analysis_type': analysis_type.value,
        'repo_name': repo_name,
        'created_at': datetime.utcnow().isoformat()
    })

    return {
        "statusCode": 202,
        "body": json.dumps({
            "message": "ok",
            'task_id': task_id,
        }),
    }


class TaskEventHandler(AnalyzerEventHandler):
    def __init__(self, db, task_id: str):
        super().__init__()
        self.db = db
        self.task_id = task_id
        self.status = 'running'

    def handle_run_start(self):
        self.progress = 0
        self.db.update_item(
            key={'task_id': self.task_id},
            update_expression='SET task_status = :status, progress = :progress',
            expression_attribute_values={':progress': f'{self.progress}% - Start', ':status': self.status},
        )

    def handle_run_end(self):
        self.progress = 100
        self.db.update_item(
            key={'task_id': self.task_id},
            update_expression='SET task_status = :status, progress = :progress',
            expression_attribute_values={':progress': f'{self.progress}% - Completed', ':status': self.status},
        )

    def handle_run_error(self, error):
        pass

    def handle_run_progress(self, msg, progress: int = None):
        if progress is not None:
            self.progress = progress
        self.db.update_item(
            key={'task_id': self.task_id},
            update_expression='SET task_status = :status, progress = :progress',
            expression_attribute_values={':progress': f'{self.progress}% - {msg}', ':status': self.status},
        )


def analyze(payload, event_handler: AnalyzerEventHandler = None):
    github_url = payload.get('github_url')
    if github_url is None:
        raise Exception('github_url is required')

    is_share_to_quick_look = payload.get('piperider_share_to_quick_look', False)

    print('[Handling Request]')
    print('github_url: ', github_url)
    print('github_token: ', payload.get('github_token'))
    print('piperider_api_service', payload.get('piperider_api_service'))
    if is_share_to_quick_look:
        print('piperider_share_to_quick_look', is_share_to_quick_look)
        upload = False
        share = True
        piperider_token = None
        piperider_project = None
    else:
        print('piperider_api_token', "******" if payload.get('piperider_api_token') else None)
        print('piperider_project', payload.get('piperider_project'))
        piperider_token = payload.get('piperider_api_token')
        piperider_project = payload.get('piperider_project')
        upload: bool = True if piperider_token and piperider_project else False
        share = False

    if payload.get('github_token'):
        # Set GitHub Token to environment variable
        os.environ['GITHUB_TOKEN'] = payload.get('github_token')

    if payload.get('piperider_api_service'):
        # Set Piperider API Service to environment variable
        os.environ['PIPERIDER_API_SERVICE'] = payload.get('piperider_api_service')

    analyzer = DbtProjectAnalyzer(github_url,
                                  api_token=piperider_token,
                                  project_name=piperider_project,
                                  upload=upload,
                                  share=share)
    if event_handler:
        analyzer.set_event_handler(event_handler)

    # TODO: handle exception
    reason = ''
    try:
        analyzer.exec()
        status = 'completed'
    except BaseException as e:
        print(f'Error: {str(e)}')
        reason = str(e)
        status = 'failed'

    if analyzer.result:
        report_url = analyzer.result.report
    else:
        report_url = None
        status = 'failed'
        reason = 'Failed to generate report'

    # TODO: return the report URL
    return status, report_url, reason


def processor(event, context):
    # TODO: get options from SQS message
    db = DynamoDB.factory(DYNAMODB_TABLE_NAME)

    for record in event.get('Records', []):
        task_id = record.get('messageId')
        task_event_handler = TaskEventHandler(db, task_id)
        try:
            body = json.loads(record.get('body'))
            status, report, reason = analyze(body, task_event_handler)
            # TODO: update task status to DynamoDB with report URL
            # TODO: save failed reason if status is failed
            db.update_item(
                key={'task_id': task_id},
                update_expression='SET task_status = :status, '
                                  'report_url = :report, '
                                  'reason = :reason',
                expression_attribute_values={
                    ':status': status,
                    ':report': report,
                    ':reason': reason},
            )
            pass
        except Exception as e:
            print(f"Error processing record {record.get('messageId')}: {str(e)}")
            db.update_item(
                key={'task_id': task_id},
                update_expression='SET task_status = :status, reason = :reason',
                expression_attribute_values={':status': 'failed', ':reason': str(e)},
            )
            continue
        finally:
            pass


def update_running_progress(db, task_id, progress, status='running'):
    db.update_item(
        key={'task_id': task_id},
        update_expression='SET task_status = :status, progress = :progress',
        expression_attribute_values={':status': status, ':progress': progress},
    )


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
                "progress": task.get('progress'),
                "repo_name": task.get('repo_name'),
                "type": task.get('analysis_type'),
                "report_url": task.get('report_url'),
            }),
        }
    elif status == 'failed':
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": status,
                "progress": task.get('progress'),
                "repo_name": task.get('repo_name'),
                "type": task.get('analysis_type'),
                "reason": task.get('reason'),
            }),
        }

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": task.get('task_status'),
            "progress": task.get('progress'),
            "repo_name": task.get('repo_name'),
            "type": task.get('analysis_type'),
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
