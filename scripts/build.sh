#!/usr/bin/env bash
# Packages both Lambda functions with their dependencies vendored in, rather
# than relying on whatever boto3/SDK version happens to ship with the managed
# runtime. Both functions call very recently added APIs (durable execution
# checkpointing, SendDurableExecutionCallbackSuccess), so pinning matters.
set -euo pipefail

cd "$(dirname "$0")/.."

for name in orchestrator api; do
  rm -rf "build/$name"
  mkdir -p "build/$name"
  pip install -r "src/$name/requirements.txt" -t "build/$name" --quiet
  cp "src/$name/lambda_function.py" "build/$name/"
  echo "Built build/$name"
done

echo "Done - now run: cd terraform && terraform apply -var-file=dev.tfvars"
