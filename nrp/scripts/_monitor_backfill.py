"""Monitor backfill progress via the Dagster GraphQL API."""

import sys

import requests

URL = "http://localhost:3000/graphql"
if len(sys.argv) < 2:
    print("Usage: python _monitor_backfill.py <backfill_id>", file=sys.stderr)
    sys.exit(2)
BACKFILL_ID = sys.argv[1]

query = """
query($id: String!) {
  partitionBackfillOrError(backfillId: $id) {
    ... on PartitionBackfill {
      id
      status
      numPartitions
      partitionStatuses {
        results {
          partitionName
          runStatus
        }
      }
    }
    ... on PythonError { message }
  }
}
"""

resp = requests.post(URL, json={"query": query, "variables": {"id": BACKFILL_ID}})
data = resp.json()["data"]["partitionBackfillOrError"]

if "message" in data:
    print(f"Error: {data['message']}", file=sys.stderr)
    sys.exit(1)

print(f"Backfill: {data['id']}  Status: {data['status']}")
print(f"Partitions: {data['numPartitions']}")

ps = data.get("partitionStatuses")
if ps and ps.get("results"):
    statuses: dict[str, int] = {}
    for r in ps["results"]:
        s = r["runStatus"] or "QUEUED"
        statuses[s] = statuses.get(s, 0) + 1
    for s, c in sorted(statuses.items()):
        print(f"  {s}: {c}")
else:
    print("  (partition statuses not yet available)")
