import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("RUNPOD_API_KEY")
endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")

query = """
query Endpoint($id: String!) {
  endpoint(id: $id) {
    id
    name
    templateId
    workers {
      id
      status
    }
  }
}
"""

url = f"https://api.runpod.io/graphql?api_key={api_key}"
resp = requests.post(url, json={"query": query, "variables": {"id": endpoint_id}})
print(resp.status_code)
print(resp.text)
