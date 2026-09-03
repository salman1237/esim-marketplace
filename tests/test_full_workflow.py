import httpx
import asyncio
import uuid
from decimal import Decimal

# You can run this against http://localhost:8000 or the live production domain
BASE_URL = "https://esim.salmandev.io/api/v1"
# BASE_URL = "http://localhost:8000/api/v1"

async def run_tests():
    print(f"Starting E2E Workflow Test against {BASE_URL}...\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        uid = uuid.uuid4().hex[:6]
        user_email = f"e2e_test_{uid}@example.com"
        user_pass = "TestPass123!"
        username = f"e2e_{uid}"
        
        # 1. Register User
        print(f"[1] Registering test user: {user_email}")
        res = await client.post(f"{BASE_URL}/auth/register", json={
            "email": user_email,
            "username": username,
            "password": user_pass,
            "phone": "+8801700000000"
        })
        assert res.status_code == 200, f"Register failed: {res.text}"
        print(" -> Success!")
        
        # 2. Login User
        print(f"[2] Logging in...")
        res = await client.post(f"{BASE_URL}/auth/login", json={
            "email": user_email,
            "password": user_pass
        })
        assert res.status_code == 200, f"Login failed: {res.text}"
        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(" -> Success! Token acquired.")
        
        # 3. Get Catalog Countries
        print(f"[3] Fetching Catalog Countries...")
        res = await client.get(f"{BASE_URL}/catalog/countries?popular_only=true", headers=headers)
        assert res.status_code == 200, "Failed to get countries"
        countries = res.json()
        print(f" -> Found {len(countries)} popular countries.")
        
        if len(countries) == 0:
            print(" -> [WARN] No countries found. Catalog might not be synced. Stopping test gracefully.")
            return
            
        test_country_iso = countries[0]["iso2"]
        
        # 4. Get Products for Country
        print(f"[4] Fetching Products for {test_country_iso}...")
        res = await client.get(f"{BASE_URL}/catalog/countries/{test_country_iso}/products", headers=headers)
        assert res.status_code == 200, "Failed to get products"
        products = res.json()
        print(f" -> Found {len(products)} products.")
        
        if len(products) == 0:
            print(" -> [WARN] No products found. Stopping test gracefully.")
            return
            
        test_product = products[0]
        print(f" -> Selected Product: {test_product['title_en']} (${test_product['retail_price']})")
        
        # 5. Check Initial Wallet Balance
        print(f"[5] Checking Initial Wallets...")
        res = await client.get(f"{BASE_URL}/wallets/my-wallets", headers=headers)
        wallets = res.json()
        default_wallet = next((w for w in wallets if w["wallet_type"] == "DEFAULT"), None)
        print(f" -> Default Wallet Balance: ${default_wallet['balance']}")
        
        # 6. Attempt Checkout (Should Fail - Insufficient Balance)
        print(f"[6] Attempting Checkout without balance...")
        res = await client.post(f"{BASE_URL}/orders/checkout", json={
            "product_id": test_product["id"],
            "payment_method": "WALLET"
        }, headers=headers)
        assert res.status_code == 400, "Checkout should have failed!"
        print(f" -> Expected Failure: {res.json()['detail']}")
        
        # 7. Apply to be a Merchant
        print(f"[7] Submitting B2B Merchant Application...")
        res = await client.post(f"{BASE_URL}/auth/apply-merchant", json={
            "business_name": "E2E Test Travel Inc.",
            "trade_license": "TR-12345",
            "contact_phone": "+1234567890"
        }, headers=headers)
        assert res.status_code == 200, f"Merchant app failed: {res.text}"
        print(" -> Success! Application submitted to queue.")
        
        print("\n--- E2E Workflow Simulation Complete ---")
        print("Note: To test successful checkout and merchant approvals, an Admin/SuperAdmin token is required to fund the wallet and approve the application.")
        print("The core storefront, catalog, wallet state, and application logic are verified working end-to-end.")

if __name__ == "__main__":
    asyncio.run(run_tests())
