import json
import os
import threading
import time
import requests
import asyncio
from telethon import TelegramClient, events
import socketio
from datetime import datetime
from auth import Authenticator

# CONFIGURATION
ACCOUNTS_FILE = "accounts.json"
AUTO_ACCEPT_FILE = "auto_accept.txt"
TELEGRAM_FILE = "telegram.json"
WS_URL = "https://qvablkqvweq.psrtilhtnd.com"

class WithdrawalBotCore:
    def __init__(self, callbacks=None):
        """
        callbacks is a dict of functions to interact with the UI:
        - log(msg)
        - on_status_change(text, color)
        - on_new_txn(txn_data)
        - on_remove_txn(job_id)
        - on_history_update(txns)
        - on_limits_update(count, limit)
        - on_telegram_status(status_text, color)
        - on_auto_accept_limits_update(min, max)
        - on_telegram_otp_needed()
        - on_auth_failed()
        - on_login_success(phone, token)
        - on_login_error(msg)
        """
        self.callbacks = callbacks or {}
        self.auth_manager = Authenticator()
        self.accounts = self.load_accounts()
        self.current_user = None
        self.token = None
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.withdrawals = {}
        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()
        self.telegram_config = self.load_telegram_config()
        self.telethon_loop = asyncio.new_event_loop()
        self.telethon_client = None
        
        threading.Thread(target=self.run_telethon_loop, daemon=True).start()

        if self.telegram_config.get("api_id") and self.telegram_config.get("phone"):
            self.start_telethon_client()

        self.setup_socket_events()
        threading.Thread(target=self.connect_ws, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()

    def call_cb(self, name, *args, **kwargs):
        if name in self.callbacks and self.callbacks[name]:
            try:
                self.callbacks[name](*args, **kwargs)
            except Exception as e:
                print(f"Callback error {name}: {e}")

    def load_accounts(self):
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, 'r') as f: return json.load(f)
        return {}

    def save_account(self, phone, password, token):
        self.accounts[phone] = {"password": password, "token": token, "last_login": datetime.now().isoformat()}
        with open(ACCOUNTS_FILE, 'w') as f: json.dump(self.accounts, f, indent=4)

    def load_telegram_config(self):
        if os.path.exists(TELEGRAM_FILE):
            try:
                with open(TELEGRAM_FILE, 'r') as f:
                    config = json.load(f)
                if "enable_commands" not in config:
                    config["enable_commands"] = True
                return config
            except Exception:
                pass
        return {"api_id": "", "api_hash": "", "phone": "", "target_user": "", "enable_commands": True}

    def run_telethon_loop(self):
        asyncio.set_event_loop(self.telethon_loop)
        self.telethon_loop.run_forever()

    def get_auto_accept_limits(self):
        try:
            if os.path.exists(AUTO_ACCEPT_FILE):
                with open(AUTO_ACCEPT_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content: return 0, float('inf')
                    if ',' in content:
                        parts = content.split(',')
                        return float(parts[0].strip()), float(parts[1].strip())
                    elif '-' in content:
                        parts = content.split('-')
                        return float(parts[0].strip()), float(parts[1].strip())
                    else:
                        lines = content.splitlines()
                        if len(lines) >= 2:
                            return float(lines[0].strip()), float(lines[1].strip())
                        else:
                            return float(lines[0].strip()), float('inf')
        except (ValueError, Exception):
            pass
        return 0, float('inf')

    def quick_login(self, phone):
        if phone in self.accounts:
            self.current_user = phone
            self.token = self.accounts[phone]["token"]
            self.call_cb("on_login_success", phone, self.token)
            self.fetch_dashboard_data()
            self.fetch_history()

    def perform_login(self, phone, password):
        if not phone.startswith("+91"): phone = "+91" + phone
        s, r = self.auth_manager.login(phone, password)
        if s:
            self.token, self.current_user = r, phone
            self.save_account(phone, password, r)
            self.call_cb("on_login_success", phone, r)
            self.fetch_dashboard_data()
            self.fetch_history()
        else:
            self.call_cb("on_login_error", f"Error: {r}")

    def auto_relogin(self):
        self.call_cb("log", "Session expired. Relogging...")
        if not self.current_user or self.current_user not in self.accounts:
            self.call_cb("on_auth_failed")
            return False
        p, pw = self.current_user, self.accounts[self.current_user]["password"]
        s, r = self.auth_manager.login(p, pw)
        if s:
            self.token = r
            self.save_account(p, pw, r)
            self.call_cb("log", "Relogged successfully.")
            return True
        self.call_cb("on_auth_failed")
        return False

    def logout(self):
        self.token = None
        self.current_user = None

    def heartbeat_loop(self):
        counter = 0
        while True:
            if self.token:
                try:
                    res = self.auth_manager.request("/api/pp/user/heartbeat", token=self.token)
                    if res and not res.get("success") and "Authentication Failed" in str(res):
                        self.auto_relogin()
                except Exception:
                    pass
                if counter % 3 == 0:
                    self.fetch_dashboard_data()
            counter += 1
            time.sleep(10)

    def fetch_dashboard_data(self):
        threading.Thread(target=self._fetch_dashboard_thread, daemon=True).start()

    def _fetch_dashboard_thread(self):
        if not self.token: return
        res = self.auth_manager.request("/api/pp/user/txns_metrics", token=self.token)
        if res and res.get("success"):
            data = res.get("data", {})
            count = data.get("availableWithdrawalTxnCount", "0")
            limit = data.get("currentAvailableWithdrawalLimit", "0")
            self.call_cb("on_limits_update", count, limit)

    def fetch_history(self):
        threading.Thread(target=self._fetch_history_thread, daemon=True).start()

    def _fetch_history_thread(self):
        if not self.token: return
        params = {"start_date": "", "end_date": "", "txn_status": "", "txn_no": "", "utr": "", "is_dispute": "", "is_security_withdrawal": "", "page": 1, "limit": 50}
        res = self.auth_manager.request("/api/pp/withdrawal/get_txns", token=self.token, custom_payload=params)
        if res and not res.get("success") and "Authentication Failed" in str(res):
            if self.auto_relogin():
                res = self.auth_manager.request("/api/pp/withdrawal/get_txns", token=self.token, custom_payload=params)
        if res and res.get("success"):
            self.call_cb("on_history_update", res["data"]["txns_data"])

    def cancel_txn(self, txn_no):
        self.call_cb("log", f"Cancelling txn {txn_no}...")
        payload = {"txn_no": txn_no, "reason": "Cancelled from Bot GUI"}
        res = self.auth_manager.request("/api/pp/withdrawal/failed", method="POST", custom_payload=payload, token=self.token)
        
        if res and res.get("success"):
            self.call_cb("log", "Transaction Cancelled Successfully.")
            self.fetch_history()
            return True
        else:
            self.call_cb("log", f"Cancel Error: {res.get('message')}")
            return False

    def setup_socket_events(self):
        @self.sio.on('connect', namespace='/pas')
        def on_connect():
            self.call_cb("on_status_change", "Connected", "green")
            self.sio.emit('get_client_transaction', {}, namespace='/pas', callback=self.handle_initial_list)
        
        @self.sio.on('get_withdrawal_txn', namespace='/pas')
        def on_new_txn(data): 
            self.process_new_txn(data)

        @self.sio.on('remove_withdrawal_txn', namespace='/pas')
        def on_remove_txn(data):
            job_id = data.get("job_id")
            if job_id in self.withdrawals:
                del self.withdrawals[job_id]
                self.call_cb("on_remove_txn", job_id)
                self.call_cb("log", f"Transaction {job_id[:8]}... taken by other.")

    def handle_initial_list(self, data):
        res = None
        if isinstance(data, dict):
            res = data
        elif isinstance(data, list) and len(data) > 0:
            res = data[0]
        
        if res and res.get("success") and "data" in res:
            txn_list = res["data"]
            self.call_cb("log", f"Loaded {len(txn_list)} pending transaction(s)")
            for txn in txn_list:
                self.process_new_txn(txn)

    def connect_ws(self):
        while True:
            try:
                if not self.sio.connected and self.token:
                    self.sio.connect(WS_URL, socketio_path='/ws/', namespaces=['/pas'], auth={'token': self.token}, transports=['websocket'], headers={'User-Agent': 'okhttp/4.12.0'})
                    self.sio.wait()
            except:
                pass
            time.sleep(5)

    def process_new_txn(self, data):
        job_id = data.get("job_id")
        if not job_id or job_id in self.withdrawals: return
        
        amount = float(data.get("amount", 0))
        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()
        
        if self.auto_accept_min > 0 and self.auto_accept_min <= amount <= self.auto_accept_max:
            max_str = 'inf' if self.auto_accept_max == float('inf') else int(self.auto_accept_max)
            self.call_cb("log", f"AUTO-ACCEPTING Rs {amount} (range: {int(self.auto_accept_min)}-{max_str})")
            self.sio.emit('accept_transaction', {"job_id": job_id}, namespace='/pas')
            threading.Thread(target=self._post_accept_poll, args=(job_id,), daemon=True).start()
            return
        
        self.withdrawals[job_id] = data
        self.call_cb("on_new_txn", data)

    def accept_txn(self, job_id):
        self.call_cb("log", f"Accepting job {job_id}...")
        self.sio.emit('accept_transaction', {"job_id": job_id}, namespace='/pas')
        threading.Thread(target=self._post_accept_poll, args=(job_id,), daemon=True).start()

    def _post_accept_poll(self, job_id):
        time.sleep(2)
        params = {"start_date": "", "end_date": "", "txn_status": "", "txn_no": "", "utr": "", "is_dispute": "", "is_security_withdrawal": "", "page": 1, "limit": 10}
        res = self.auth_manager.request("/api/pp/withdrawal/get_txns", token=self.token, custom_payload=params)
        if res and res.get("success") and res["data"]["txns_data"]:
            txn_data = res["data"]["txns_data"][0]
            self.call_cb("log", f"Accepted Rs {txn_data.get('amount')} - {txn_data.get('txnNo', '')}")
            self.send_telegram_notification(txn_data)
        self.fetch_history()

    def send_telegram_notification(self, txn_data):
        target = self.telegram_config.get("target_user")
        if not target or not self.telethon_client:
            return
            
        amount = txn_data.get('amount')
        txn_no = txn_data.get('txnNo') or txn_data.get('transaction_id')
        status = txn_data.get('status')
        bank = txn_data.get('bankName')
        
        msg = f"✅ **Transaction Accepted**\n\n💰 **Amount:** ₹ {amount}\n📄 **Status:** {status}\n🔢 **Txn ID:** `{txn_no}`\n🏦 **Bank:** {bank}"
        
        async def _send():
            try:
                if await self.telethon_client.is_user_authorized():
                    await self.telethon_client.send_message(target, msg)
                    self.call_cb("log", f"Sent details to {target} via Telethon")
            except Exception as e:
                self.call_cb("log", f"Telethon Send Error: {e}")
                
        asyncio.run_coroutine_threadsafe(_send(), self.telethon_loop)

    def start_telethon_client(self, force_login=False):
        api_id = self.telegram_config.get("api_id")
        api_hash = self.telegram_config.get("api_hash")
        phone = self.telegram_config.get("phone")
        
        if not api_id or not api_hash or not phone:
            self.call_cb("on_telegram_status", "Missing Credentials", "red")
            return
            
        try:
            api_id = int(api_id)
        except:
            self.call_cb("on_telegram_status", "API ID must be a number", "red")
            return

        if (getattr(self, 'telethon_client', None) is not None and 
            getattr(self, 'active_tg_credentials', None) == (api_id, api_hash, phone) and 
            not force_login):
            
            async def update_status_async():
                if await self.telethon_client.is_user_authorized():
                    self.call_cb("on_telegram_status", "Connected & Authorized", "green")
                else:
                    self.call_cb("on_telegram_status", "Not Logged In", "red")
            asyncio.run_coroutine_threadsafe(update_status_async(), self.telethon_loop)
            return

        self.call_cb("on_telegram_status", "Connecting...", "yellow")
        
        if self.telethon_client:
            asyncio.run_coroutine_threadsafe(self.telethon_client.disconnect(), self.telethon_loop)
            
        self.telethon_client = TelegramClient(phone, api_id, api_hash)
        self.active_tg_credentials = (api_id, api_hash, phone)

        @self.telethon_client.on(events.NewMessage(incoming=True))
        async def handle_new_telegram_message(event):
            if not self.telegram_config.get("enable_commands", True):
                return
            sender = await event.get_sender()
            if not sender: return
            
            target = self.telegram_config.get("target_user", "").strip().lower()
            if not target: return
            
            target_norm = target.lstrip('@')
            sender_username = (sender.username or "").lower().lstrip('@')
            sender_phone = (sender.phone or "").strip()
            sender_id = str(sender.id)
            is_authorized = (sender_username == target_norm or sender_phone == target or sender_id == target)
            if not is_authorized: return
            
            text = (event.raw_text or "").strip().lower()
            if text == "start":
                await self.handle_telegram_start(event)
            elif text == "stop":
                await self.handle_telegram_stop(event)
            elif text.startswith("limit"):
                await self.handle_telegram_limit(event, text)
        
        async def _connect():
            await self.telethon_client.connect()
            if not await self.telethon_client.is_user_authorized():
                if force_login:
                    try:
                        req = await self.telethon_client.send_code_request(phone)
                        self.tg_phone_code_hash = req.phone_code_hash
                        self.call_cb("on_telegram_otp_needed")
                        self.call_cb("on_telegram_status", "Waiting for OTP", "orange")
                    except Exception as e:
                        self.call_cb("on_telegram_status", f"Error: {e}", "red")
                else:
                    self.call_cb("on_telegram_status", "Not Logged In", "red")
            else:
                self.call_cb("on_telegram_status", "Connected & Authorized", "green")
                
        asyncio.run_coroutine_threadsafe(_connect(), self.telethon_loop)

    def submit_tg_otp(self, otp):
        phone = self.telegram_config.get("phone")
        if not otp: return
        
        async def _sign_in():
            try:
                await self.telethon_client.sign_in(phone=phone, code=otp, phone_code_hash=getattr(self, 'tg_phone_code_hash', None))
                self.call_cb("on_telegram_status", "Connected & Authorized", "green")
            except Exception as e:
                self.call_cb("on_telegram_status", f"Login Error: {e}", "red")
                
        asyncio.run_coroutine_threadsafe(_sign_in(), self.telethon_loop)

    def save_settings(self, min_val, max_val, tg_settings, enable_commands):
        try:
            with open(AUTO_ACCEPT_FILE, 'w') as f:
                if min_val:
                    if max_val: f.write(f"{min_val}-{max_val}")
                    else: f.write(min_val)
                else: f.write("0")
        except Exception as e:
            self.call_cb("log", f"Error saving limits: {e}")

        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()
        self.call_cb("on_auto_accept_limits_update", self.auto_accept_min, self.auto_accept_max)

        for key, val in tg_settings.items():
            self.telegram_config[key] = val
            
        self.telegram_config["enable_commands"] = enable_commands

        try:
            with open(TELEGRAM_FILE, 'w') as f:
                json.dump(self.telegram_config, f)
        except Exception as e:
            self.call_cb("log", f"Error saving TG config: {e}")
            
        self.call_cb("log", "Settings saved successfully.")

    async def handle_telegram_start(self, event):
        if self.token:
            await event.reply("⚠️ Bot is already running and logged in.")
            return
        
        accs = list(self.accounts.keys())
        if not accs:
            await event.reply("❌ No saved accounts found. Please log in via the app first.")
            return
            
        selected_account = None
        try:
            sorted_accs = sorted(self.accounts.items(), key=lambda x: x[1].get("last_login", ""), reverse=True)
            selected_account = sorted_accs[0][0]
        except Exception:
            selected_account = accs[0]
            
        if not selected_account:
            await event.reply("❌ No valid account found.")
            return
            
        self.quick_login(selected_account)
        self.call_cb("log", f"Started via Telegram command")
        await event.reply(f"🚀 Starting bot with account: `{selected_account}`...")

    async def handle_telegram_stop(self, event):
        if not self.token:
            await event.reply("⚠️ Bot is not currently running.")
            return
            
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass
            
        self.logout()
        self.call_cb("log", "Stopped and logged out via Telegram command")
        self.call_cb("on_auth_failed")
        await event.reply("🛑 Bot stopped and logged out successfully.")

    async def handle_telegram_limit(self, event, text):
        parts = text.split()
        if len(parts) >= 2:
            try:
                min_val = parts[1]
                max_val = parts[2] if len(parts) > 2 else ""
                
                float(min_val)
                if max_val: float(max_val)
                    
                self.update_limits_from_telegram(min_val, max_val)
                await event.reply(f"✅ Auto-accept limits updated: {min_val} to {max_val if max_val else 'infinity'}")
            except ValueError:
                await event.reply("❌ Invalid format. Use: `limit <min> [max]`")
        else:
            await event.reply("❌ Invalid format. Use: `limit <min> [max]`")

    def update_limits_from_telegram(self, min_val, max_val):
        try:
            with open(AUTO_ACCEPT_FILE, 'w') as f:
                if min_val:
                    if max_val: f.write(f"{min_val}-{max_val}")
                    else: f.write(min_val)
                else: f.write("0")
        except Exception:
            pass

        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()
        self.call_cb("on_auto_accept_limits_update", self.auto_accept_min, self.auto_accept_max)
        self.call_cb("log", f"Limits updated via Telegram to {min_val}-{max_val}")
