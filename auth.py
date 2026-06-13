import json
import hashlib
import requests
import time
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

AES_KEY = b"1YGonuQqkjhUYpKy4GQvzKNuhKSge5sH"
AES_IV = b"sfj289ernx92o2di"
HASH_SALT = "v6i37vCf93Zngf3o5p1s8b1ai05SypLB"
BASE_URL = "https://pbrpvkrs25.psrtilhtnd.com"

class Authenticator:
    def __init__(self):
        self.headers = {
            'user-agent': 'okhttp/4.12.0',
            'device-type': '2',
            'version': '1.0.0',
            'content-type': 'application/json'
        }

    def encrypt_payload(self, payload_dict):
        sorted_keys = sorted(payload_dict.keys())
        sorted_payload = {k: payload_dict[k] for k in sorted_keys}
        json_str = json.dumps(sorted_payload, separators=(',', ':'))
        to_hash = json_str + HASH_SALT
        signature = hashlib.sha512(to_hash.encode('utf-8')).hexdigest()
        final_payload = dict(sorted_payload)
        final_payload['signature'] = signature
        final_json = json.dumps(final_payload, separators=(',', ':'))
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        padded_data = pad(final_json.encode('utf-8'), AES.block_size)
        return cipher.encrypt(padded_data).hex()

    def decrypt_response(self, hex_string):
        try:
            encrypted_bytes = bytes.fromhex(hex_string)
            cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
            decrypted_padded = cipher.decrypt(encrypted_bytes)
            return json.loads(unpad(decrypted_padded, AES.block_size).decode('utf-8'))
        except: return None

    def request(self, endpoint, method="GET", custom_payload=None, token=None):
        url = f"{BASE_URL}{endpoint}"
        payload = {"nonce": str(int(time.time() * 1000))}
        if custom_payload:
            payload.update(custom_payload)
            
        encrypted_data = self.encrypt_payload(payload)
        headers = dict(self.headers)
        if token:
            headers['auth-token'] = token

        try:
            if method == "POST":
                resp = requests.post(url, headers=headers, json={'data': encrypted_data}, timeout=15)
            else:
                resp = requests.get(f"{url}?data={encrypted_data}", headers=headers, timeout=15)
            
            text = resp.text.strip()
            if text.startswith("{"):
                return resp.json()
            return self.decrypt_response(text)
        except Exception as e:
            return {"success": False, "message": str(e)}

    def login(self, username, password):
        if not username.startswith("+91"):
            username = "+91" + username
            
        payload = {
            "username": username, 
            "password": password,
            "nonce": str(int(time.time() * 1000))
        }
        encrypted_data = self.encrypt_payload(payload)
        
        try:
            resp = requests.post(
                f"{BASE_URL}/api/pp/user/login", 
                headers=self.headers, 
                json={'data': encrypted_data},
                timeout=15
            )
            
            text = resp.text.strip()
            if text.startswith("{"):
                res = resp.json()
            else:
                res = self.decrypt_response(text)
            
            if res and res.get("success"):
                return True, res["data"]["token"]
            
            err = None
            if res:
                if isinstance(res.get("data"), dict):
                    err = res["data"].get("message")
                if not err:
                    err = res.get("message")
            if not err:
                err = "Login Failed"
            return False, err
        except Exception as e:
            return False, str(e)
