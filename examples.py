import os

from dotenv import load_dotenv
load_dotenv()

BASE_URL = os.getenv("API_CONTRACT_SERVICE_URL")


def download_pdf(file_path):
    import requests, shutil

    url = f"{BASE_URL}/contract/download/68d11fc58cad15b8b8f0f7b9"
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(f"{file_path}/contract.pdf", "wb") as f:
            shutil.copyfileobj(r.raw, f)

if __name__ == "__main__":
    path = "/home/mh1f25/scratch/upcast_pro/contract_service/negotiation-plugin/demo/"
    download_pdf(path)