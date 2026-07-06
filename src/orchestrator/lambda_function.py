"""
Durable orchestrator for a multi-agent content pipeline.

Agents (each a checkpointed step):
  1. Researcher  - turns a topic into an outline
  2. Writer      - drafts a post from the outline (and, on revisions, editor feedback)
  3. Editor      - scores the draft and decides whether it needs another pass

After the editor is satisfied (or MAX_REVISIONS is hit), the function suspends
with wait_for_callback() until a human approves or rejects the draft via the
/approve API route. Suspension costs nothing while it waits - that's the part
Step Functions / a plain Lambda + SQS setup can't do for free.
"""

import json
import os

import boto3
from aws_durable_execution_sdk_python import DurableContext, durable_execution
from aws_durable_execution_sdk_python.config import Duration, WaitForCallbackConfig

bedrock = boto3.client("bedrock-runtime")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
s3 = boto3.client("s3")

MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
MAX_REVISIONS = int(os.environ.get("MAX_REVISIONS", "2"))
APPROVAL_SCORE_THRESHOLD = int(os.environ.get("APPROVAL_SCORE_THRESHOLD", "8"))
CALLBACK_TIMEOUT_SECONDS = int(os.environ.get("CALLBACK_TIMEOUT_SECONDS", str(24 * 60 * 60)))


def call_agent(system_prompt: str, user_prompt: str) -> str:
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={"maxTokens": 1500, "temperature": 0.4},
    )
    return response["output"]["message"]["content"][0]["text"]


def parse_agent_json(text: str) -> dict:
    """Models often wrap JSON in ```json fences despite instructions - strip them."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned.strip())


def set_status(execution_id, **fields):
    expression = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    table.update_item(
        Key={"execution_id": execution_id},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


@durable_execution
def lambda_handler(event, context: DurableContext):
    topic = event["topic"]
    execution_id = event["execution_id"]

    # --- Agent 1: Researcher -------------------------------------------------
    outline = context.step(
        lambda _: call_agent(
            "You are a research agent. Produce a tight 5-7 bullet outline for a "
            "blog post on the given topic. Bullets only, no preamble.",
            topic,
        ),
        name="research",
    )

    # --- Agent 2: Writer -------------------------------------------------------
    draft = context.step(
        lambda _: call_agent(
            "You are a writer agent. Write a ~500 word blog post draft in markdown "
            "from the given topic and outline.",
            f"Topic: {topic}\nOutline:\n{outline}",
        ),
        name="write-0",
    )

    # --- Agent 3: Editor, with a self-correcting revision loop ----------------
    # This is the "agentic" part: the editor decides whether the writer needs
    # to try again, and the loop can run 0-N times depending on that decision.
    for revision in range(MAX_REVISIONS):
        critique_raw = context.step(
            lambda _: call_agent(
                "You are an editor agent. Score the draft from 1-10 for clarity "
                "and correctness. Reply with ONLY compact JSON: "
                '{"score": <int>, "feedback": "<string>"}',
                draft,
            ),
            name=f"critique-{revision}",
        )
        critique = parse_agent_json(critique_raw)

        if critique["score"] >= APPROVAL_SCORE_THRESHOLD:
            break

        draft = context.step(
            lambda _: call_agent(
                "You are a writer agent. Revise the draft in markdown using the "
                "editor's feedback.",
                f"Topic: {topic}\nPrevious draft:\n{draft}\nEditor feedback:\n{critique['feedback']}",
            ),
            name=f"write-{revision + 1}",
        )

    # --- Human-in-the-loop: suspend for free until someone approves -----------
    # The submitter the SDK calls when it opens the callback takes
    # (callback_id, callback_context); we only need the ID.
    def request_approval(callback_id, _callback_context):
        set_status(
            execution_id,
            callback_id=callback_id,
            draft=draft,
            status="AWAITING_APPROVAL",
        )

    # Callback results arrive as the raw string an external caller sent via
    # SendDurableExecutionCallbackSuccess, so we JSON-decode it ourselves.
    approval_raw = context.wait_for_callback(
        request_approval,
        name="human-approval",
        config=WaitForCallbackConfig(timeout=Duration.from_seconds(CALLBACK_TIMEOUT_SECONDS)),
    )
    approval = json.loads(approval_raw) if approval_raw else None

    if not approval or not approval.get("approved"):
        set_status(execution_id, status="REJECTED")
        return {"execution_id": execution_id, "status": "REJECTED"}

    # --- Publish step -----------------------------------------------------------
    def publish(_):
        key = f"{execution_id}.md"
        s3.put_object(
            Bucket=os.environ["BUCKET_NAME"],
            Key=key,
            Body=draft.encode("utf-8"),
            ContentType="text/markdown",
        )
        url = f"s3://{os.environ['BUCKET_NAME']}/{key}"
        set_status(execution_id, final_url=url, status="PUBLISHED")
        return url

    final_url = context.step(publish, name="publish")

    return {"execution_id": execution_id, "status": "PUBLISHED", "url": final_url}
