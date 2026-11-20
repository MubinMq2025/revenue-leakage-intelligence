"""
AWS Glue job: run the Phase 4 ML pipeline in the cloud (Phase 4.7).

Glue only runs one script from S3, so this small launcher:
    1. downloads the code bundle (built by scripts/build_ml_bundle.py, uploaded by Terraform)
    2. unzips it into a temporary folder
    3. runs scripts/run_ml_pipeline.py, the same pipeline you run locally

MLflow tracking is switched off here (the job's disk is thrown away after each run); the results
are published to the ml_* Athena tables instead. All output appears in the job's CloudWatch logs.
"""

import os
import runpy
import sys
import zipfile

import boto3
from awsglue.utils import getResolvedOptions

args = getResolvedOptions(sys.argv, ["DATA_BUCKET", "BUNDLE_KEY"])
WORK_DIR = "/tmp/rli"
BUNDLE = "/tmp/ml_bundle.zip"

boto3.client("s3").download_file(args["DATA_BUCKET"], args["BUNDLE_KEY"], BUNDLE)
with zipfile.ZipFile(BUNDLE) as zf:
    zf.extractall(WORK_DIR)
print(f"Code bundle s3://{args['DATA_BUCKET']}/{args['BUNDLE_KEY']} unpacked to {WORK_DIR}", flush=True)

os.environ["RLI_TRACKING"] = "off"
os.environ["MPLBACKEND"] = "Agg"
os.chdir(WORK_DIR)
sys.path.insert(0, WORK_DIR)
sys.argv = [sys.argv[0]]          # the pipeline scripts take no arguments
runpy.run_path(os.path.join(WORK_DIR, "scripts", "run_ml_pipeline.py"), run_name="__main__")