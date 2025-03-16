import sys
import requests

total_cost = int(float(sys.argv[1]) * 100) 

url = "https://api.paymongo.com/v1/links"

payload = {
    "data": {
        "attributes": {
            "amount": total_cost,
            "description": "total amount"
        }
    }
}
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": "Basic c2tfdGVzdF93RjNQa0c5RlFKNDlNbThtM2ZkWWNFeDQ6"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)
