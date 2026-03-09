import requests
import time
import os

API_KEY = os.environ.get("RUNPOD_API_KEY")
POD_ID = os.environ.get("RUNPOD_POD_ID")

BASE = "https://api.runpod.io/graphql"


def start_pod():
    """Start the RunPod GPU pod."""
    query = """
    mutation {
      podStart(input: {podId: "%s"}) { id }
    }
    """ % POD_ID

    requests.post(BASE, json={"query": query},
                  headers={"Authorization": API_KEY})


def stop_pod():
    """Stop the RunPod GPU pod."""
    query = """
    mutation {
      podStop(input: {podId: "%s"}) { id }
    }
    """ % POD_ID

    requests.post(BASE, json={"query": query},
                  headers={"Authorization": API_KEY})


def wait_until_ready(timeout=120):
    """Wait for the pod to be ready and running."""
    for _ in range(timeout):
        query = """
        query {
          pod(input: {podId: "%s"}) {
            runtime { uptimeInSeconds }
          }
        }
        """ % POD_ID

        r = requests.post(BASE, json={"query": query},
                          headers={"Authorization": API_KEY})

        if r.json()["data"]["pod"]["runtime"]:
            return True

        time.sleep(2)

    return False
