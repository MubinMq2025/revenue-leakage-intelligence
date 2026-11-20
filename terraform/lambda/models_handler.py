"""
AWS Lambda entry point for the warehouse steps of the daily pipeline (Phase 5).

One function, three actions, chosen by the event Step Functions sends:
    {"action": "build"}                       rebuild every model in sql/models/ (views, then mart tables)
    {"action": "check"}                       run the checks in config/model_checks.yaml
    {"action": "leakage"}                     latest month's money at risk vs config/alerts.yaml, plus drift
    {"action": "leakage", "max_at_risk_rate": 0.001}   same, with a test line (forces an alert)

A failed build or check RAISES, so Step Functions sees the step as failed, stops the chain and
sends the failure email. The leakage action never fails on a high number: it returns "alert": true
and Step Functions decides to email.
"""

from __future__ import annotations

import json
import logging
import time

import boto3

from src.athena_tools import REGION, athena_client
from src.warehouse.build import build_all
from src.warehouse.checks import broken, run_all
from src.warehouse.leakage import check_leakage

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class StepFailed(RuntimeError):
    """Raised so Step Functions marks the step as failed (the name shows up in the console)."""


def do_build(event: dict) -> dict:
    session = boto3.Session(region_name=REGION)
    results = build_all(athena_client(), session.client("glue"), session.client("s3"))
    failed = [r for r in results if r["status"] != "OK"]
    for r in failed:
        logger.error("Model failed: %s", json.dumps(r))
    if failed:
        raise StepFailed(f"{len(failed)} of {len(results)} models failed: " + ", ".join(r["model"] for r in failed))
    return {"models": len(results), "failed": 0}


def do_check(event: dict) -> dict:
    results = run_all(athena_client())
    bad = broken(results)
    for r in bad:
        logger.error("Check not as expected: %s", json.dumps(r))
    if bad:
        raise StepFailed(f"{len(bad)} of {len(results)} checks need attention: " + ", ".join(r["name"] for r in bad))
    return {"checks": len(results), "as_expected": len(results)}


def do_leakage(event: dict) -> dict:
    return check_leakage(athena_client(), max_rate=event.get("max_at_risk_rate"))


ACTIONS = {"build": do_build, "check": do_check, "leakage": do_leakage}


def lambda_handler(event, context):
    event = event or {}
    action = event.get("action")
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}; expected one of {sorted(ACTIONS)}")

    started = time.time()
    result = ACTIONS[action](event)
    result["action"] = action
    result["seconds"] = round(time.time() - started, 1)
    logger.info("Done: %s", json.dumps(result, default=str))
    return result
