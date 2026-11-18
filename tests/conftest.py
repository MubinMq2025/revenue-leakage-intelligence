"""
Shared test setup. pytest runs this file before collecting any test.

Unit tests must never touch real AWS. The Lambda handler creates a boto3 client
when it is imported, and boto3 looks up credentials at that moment, so an
expired AWS login would break the tests. Fake credentials stop that.
"""

import os

os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ.pop("AWS_SESSION_TOKEN", None)
os.environ.pop("AWS_PROFILE", None)
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")