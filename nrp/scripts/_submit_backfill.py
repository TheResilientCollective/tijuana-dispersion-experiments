"""Submit the Sobol backfill via the Dagster GraphQL API (remote daemon)."""

import json
import sys

import requests

URL = "http://localhost:3000/graphql"
N_CHUNKS = 100


def submit_backfill() -> str | None:
    partitions = [f"chunk_{i:03d}" for i in range(N_CHUNKS)]

    mutation = """
    mutation($partitions: [String!]!) {
      launchPartitionBackfill(
        backfillParams: {
          partitionNames: $partitions,
          assetSelection: [{ path: ["sobol_chunk_results"] }],
        }
      ) {
        ... on LaunchBackfillSuccess {
          backfillId
        }
        ... on PythonError {
          message
        }
      }
    }
    """

    resp = requests.post(URL, json={"query": mutation, "variables": {"partitions": partitions}})
    result = resp.json()
    print(json.dumps(result, indent=2))

    data = result.get("data", {}).get("launchPartitionBackfill", {})
    if "backfillId" in data:
        return data["backfillId"]
    print(f"Error: {data.get('message', 'unknown')}", file=sys.stderr)
    return None


if __name__ == "__main__":
    backfill_id = submit_backfill()
    if backfill_id:
        print(f"\nBackfill submitted: {backfill_id}")
    else:
        sys.exit(1)
