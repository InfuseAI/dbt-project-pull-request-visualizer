import base64
import json


def parse_event_body(event) -> dict:
    body = event.get('body')
    if body is None:
        return {}

    if event.get('isBase64Encoded', False):
        body = base64.b64decode(body).decode('utf-8')

    return json.loads(body)
