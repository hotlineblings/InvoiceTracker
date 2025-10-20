import requests

url = "https://api.infakt.pl/api/v3/clients/33509907.json"
headers = {
    "accept": "application/json",
    "X-inFakt-ApiKey": "36129a257b95a45d72e0ebf1fb267ec66165ab84"
    # ↑ To jest przykładowy klucz, w praktyce wstaw tu swój prawdziwy
}

response = requests.get(url, headers=headers)
print(response.text)