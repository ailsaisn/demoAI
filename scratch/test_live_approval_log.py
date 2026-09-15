import requests
import json
import time

BASE_URL = "http://localhost:8000/api"

def main():
    s = requests.Session()
    # 1. Login as admin
    login_res = s.post(f"{BASE_URL}/auth/login", data={"username": "admin@mail.com", "password": "Erhadermies@123"})
    print("Login Status:", login_res.status_code)

    # 2. Get quota/pending list to find a document to approve
    docs_res = s.get(f"{BASE_URL}/knowledge/quota")
    print("Quota Status:", docs_res.status_code)

    # 3. Upload a sample document to create a fresh staging ID
    pdf_path = "C:\\Users\\wildan\\.gemini\\antigravity-ide\\brain\\c5719ff5-6ddb-4f4a-9e69-652c9863b42e\\.user_uploaded\\media_1789435090485.pdf"
    with open(pdf_path, "rb") as f:
        files = {"file": ("test_logging_approval.pdf", f, "application/pdf")}
        up_res = s.post(f"{BASE_URL}/knowledge/upload", files=files)
    print("Upload Status:", up_res.status_code, up_res.json())
    
    k_id = up_res.json()["documents"][0]["knowledge_id"]
    print(f"Staged Knowledge ID: {k_id}")

    # Wait 2 sec for parser staging
    time.sleep(2)

    # 4. Trigger Approval
    print(f"\nTriggering POST {BASE_URL}/knowledge/{k_id}/approve ...")
    app_res = s.post(f"{BASE_URL}/knowledge/{k_id}/approve")
    print("Approval Response Status:", app_res.status_code)
    print("Approval Response Output:", app_res.json())

if __name__ == "__main__":
    main()
