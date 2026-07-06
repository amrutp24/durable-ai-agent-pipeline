"""
Plain (non-durable) Lambda behind API Gateway HTTP API.

Routes:
  POST /posts             start a new agent pipeline run -> {"topic": "..."}
  GET  /posts/{id}         check status / read the current draft
  POST /posts/{id}/approve approve or reject the pending draft -> {"approved": true}
"""

import json
import os
import uuid

import boto3

lambda_client = boto3.client("lambda")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

ORCHESTRATOR_QUALIFIED_ARN = os.environ["ORCHESTRATOR_QUALIFIED_ARN"]


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def start_pipeline(body):
    topic = (body or {}).get("topic")
    if not topic:
        return _response(400, {"error": "topic is required"})

    execution_id = str(uuid.uuid4())

    table.put_item(
        Item={"execution_id": execution_id, "topic": topic, "status": "STARTED"}
    )

    lambda_client.invoke(
        FunctionName=ORCHESTRATOR_QUALIFIED_ARN,
        InvocationType="Event",
        Payload=json.dumps({"topic": topic, "execution_id": execution_id}).encode("utf-8"),
    )

    return _response(202, {"execution_id": execution_id, "status": "STARTED"})


def get_status(execution_id):
    item = table.get_item(Key={"execution_id": execution_id}).get("Item")
    if not item:
        return _response(404, {"error": "not found"})
    return _response(200, item)


def approve(execution_id, body):
    item = table.get_item(Key={"execution_id": execution_id}).get("Item")
    if not item:
        return _response(404, {"error": "not found"})
    if item.get("status") != "AWAITING_APPROVAL":
        return _response(409, {"error": f"nothing awaiting approval (status={item.get('status')})"})

    approved = bool((body or {}).get("approved"))

    lambda_client.send_durable_execution_callback_success(
        CallbackId=item["callback_id"],
        Result=json.dumps({"approved": approved}),
    )

    table.update_item(
        Key={"execution_id": execution_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "APPROVAL_SUBMITTED"},
    )

    return _response(200, {"execution_id": execution_id, "approved": approved})


def lambda_handler(event, context):
    route_key = event["routeKey"]  # e.g. "POST /posts/{id}/approve"
    path_params = event.get("pathParameters") or {}
    body = json.loads(event["body"]) if event.get("body") else {}

    if route_key == "POST /posts":
        return start_pipeline(body)
    if route_key == "GET /posts/{id}":
        return get_status(path_params["id"])
    if route_key == "POST /posts/{id}/approve":
        return approve(path_params["id"], body)

    return _response(404, {"error": "no matching route"})
