import json
import os
import sys
import threading
import time
import requests
import asyncio
from telethon import TelegramClient, events
import customtkinter as ctk
import socketio
from datetime import datetime
from auth import Authenticator

# CONFIGURATION
ACCOUNTS_FILE = "accounts.json"
AUTO_ACCEPT_FILE = "auto_accept.txt"
TELEGRAM_FILE = "telegram.json"
WS_URL = "https://qvablkqvweq.psrtilhtnd.com"
class DetailWindow(ctk.CTkToplevel):
    def __init__(self, parent, data):
        super().__init__(parent)
        self.parent = parent
        self.data = data
        self.title("Transaction Details")
        self.geometry("520x750")
        self.attributes('-topmost', True)
        self.setup_ui(data)

    def setup_ui(self, data):
        fields = [
            {"label": "Amount", "display": f"₹ {data.get('amount')}", "copy": str(data.get('amount'))},
            {"label": "Status", "display": data.get("status", "N/A"), "copy": data.get("status", "")},
            {"label": "Transaction ID", "display": data.get("txnNo") or data.get("transaction_id") or "N/A", "copy": data.get("txnNo") or data.get("transaction_id") or ""},
            {"label": "Account Name", "display": data.get("accountHolderName", "N/A"), "copy": data.get("accountHolderName", "")},
            {"label": "Account Number", "display": data.get("accountNumber", "N/A"), "copy": data.get("accountNumber", "")},
            {"label": "IFSC Code", "display": data.get("ifscCode", "N/A"), "copy": data.get("ifscCode", "")},
            {"label": "Bank Name", "display": data.get("bankName", "N/A"), "copy": data.get("bankName", "")},
            {"label": "Branch", "display": data.get("branchName", "N/A"), "copy": data.get("branchName", "")},
            {"label": "Created At", "display": data.get("createdAt", "N/A"), "copy": data.get("createdAt", "")},
            {"label": "Memo", "display": data.get("memo", "N/A"), "copy": data.get("memo", "")},
            {"label": "Job ID", "display": data.get("job_id", "N/A"), "copy": data.get("job_id", "")}
        ]
        ctk.CTkLabel(self, text="TRANSACTION RECORD", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=20)
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        frame.grid_columnconfigure(0, weight=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=0)
        
        for i, field in enumerate(fields):
            ctk.CTkLabel(frame, text=f"{field['label']}:", font=ctk.CTkFont(weight="bold"), anchor="w").grid(row=i, column=0, padx=10, pady=5, sticky="w")
            ctk.CTkLabel(frame, text=str(field['display']), wraplength=200, justify="left").grid(row=i, column=1, padx=10, pady=5, sticky="w")
            
            # Copy Button
            btn_copy = ctk.CTkButton(frame, text="Copy", width=55, height=20, font=ctk.CTkFont(size=11), fg_color="#34495e", hover_color="#2c3e50")
            btn_copy.configure(command=lambda val=field['copy'], btn=btn_copy: self.copy_to_clipboard(val, btn))
            btn_copy.grid(row=i, column=2, padx=10, pady=5, sticky="e")

        # Cancel Button for Initiated transactions
        if data.get("status") == "INITIATED":
            self.btn_cancel = ctk.CTkButton(self, text="CANCEL TRANSACTION", fg_color="#c0392b", hover_color="#e74c3c", 
                                             command=self.handle_cancel)
            self.btn_cancel.pack(pady=10)

        ctk.CTkButton(self, text="CLOSE", command=self.destroy).pack(pady=10)

    def copy_to_clipboard(self, value, button):
        self.clipboard_clear()
        self.clipboard_append(str(value))
        self.update()
        
        orig_fg = button.cget("fg_color")
        button.configure(text="Copied!", fg_color="#2ecc71")
        self.after(1000, lambda: button.configure(text="Copy", fg_color=orig_fg))

    def handle_cancel(self):
        import tkinter.messagebox as messagebox
        confirm = messagebox.askyesno("Confirm Cancellation", "Are you sure you want to cancel this transaction?\nReason: BANK DECLINED DUE TO SECURITY ISSUE", parent=self)
        if not confirm:
            return
        txn_no = self.data.get("txnNo") or self.data.get("transaction_id")
        self.btn_cancel.configure(state="disabled", text="CANCELLING...")
        threading.Thread(target=self.parent.cancel_txn, args=(txn_no, self), daemon=True).start()

class WithdrawalBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Withdrawal Bot - Premium")
        self.geometry("600x900")
        self.load_settings()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        ctk.set_appearance_mode("dark")
        
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

        # Start Telethon client on startup if credentials exist
        if self.telegram_config.get("api_id") and self.telegram_config.get("phone"):
            self.start_telethon_client()

        self.container = ctk.CTkFrame(self)
        self.container.pack(fill="both", expand=True)
        self.show_login_screen(is_startup=True)

    def load_settings(self):
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r") as f:
                    data = json.load(f)
                    if "geometry" in data:
                        self.geometry(data["geometry"])
            except Exception: pass

    def on_closing(self):
        try:
            data = {}
            if os.path.exists("settings.json"):
                with open("settings.json", "r") as f:
                    data = json.load(f)
            data["geometry"] = self.geometry()
            with open("settings.json", "w") as f:
                json.dump(data, f)
        except Exception: pass
        self.destroy()
        os._exit(0)

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
                config = json.load(f) if 'f' in locals() else None
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
        """Read limits from auto_accept.txt. Returns (min, max)."""
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

    def show_login_screen(self, is_startup=False):
        self.clear_container()
        frame = ctk.CTkFrame(self.container, width=450, height=600)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(frame, text="ACCOUNT MANAGER", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=30)
        
        accs = list(self.accounts.keys())
        self.account_selector = ctk.CTkOptionMenu(frame, values=accs if accs else ["No Accounts"], width=250)
        self.account_selector.pack(pady=10)
        if accs and is_startup:
            sorted_accs = sorted(self.accounts.items(), key=lambda x: x[1].get("last_login", ""), reverse=True)
            last_account = sorted_accs[0][0]
            self.account_selector.set(last_account)
            self.after(3000, self.handle_quick_login)
            
        ctk.CTkButton(frame, text="QUICK LOGIN", command=self.handle_quick_login, width=250, fg_color="#2980b9").pack(pady=10)
        ctk.CTkLabel(frame, text="--- OR ---").pack(pady=10)
        self.phone_entry = ctk.CTkEntry(frame, placeholder_text="Phone Number", width=250)
        self.phone_entry.pack(pady=10)
        self.pass_entry = ctk.CTkEntry(frame, placeholder_text="Password", show="*", width=250)
        self.pass_entry.pack(pady=10)
        self.new_login_btn = ctk.CTkButton(frame, text="LOGIN NEW", command=self.handle_new_login, width=250)
        self.new_login_btn.pack(pady=10)
        self.login_status = ctk.CTkLabel(frame, text="", text_color="red")
        self.login_status.pack(pady=10)

    def handle_quick_login(self):
        u = self.account_selector.get()
        if u == "No Accounts": return
        self.current_user, self.token = u, self.accounts[u]["token"]
        self.show_dashboard()

    def handle_new_login(self):
        p, pw = self.phone_entry.get().strip(), self.pass_entry.get().strip()
        if not p or not pw: return
        self.new_login_btn.configure(state="disabled", text="Logging in...")
        threading.Thread(target=self.perform_login, args=(p, pw), daemon=True).start()

    def perform_login(self, phone, password):
        if not phone.startswith("+91"): phone = "+91" + phone
        s, r = self.auth_manager.login(phone, password)
        if s:
            self.token, self.current_user = r, phone
            self.save_account(phone, password, r)
            self.after(0, self.show_dashboard)
        else:
            self.after(0, lambda: [self.login_status.configure(text=f"Error: {r}"), self.new_login_btn.configure(state="normal", text="LOGIN NEW")])

    def show_dashboard(self):
        self.clear_container()
        self.tab_view = ctk.CTkTabview(self.container)
        self.tab_view.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_live = self.tab_view.add("LIVE FEED")
        self.tab_history = self.tab_view.add("ALL REQUESTS")
        self.tab_settings = self.tab_view.add("SETTINGS")
        
        # Header for Limits
        self.header_frame = ctk.CTkFrame(self.tab_live, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=10, pady=5)
        
        self.lbl_txn_count = ctk.CTkLabel(self.header_frame, text="Txn Count: --", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3498db")
        self.lbl_txn_count.pack(side="left", padx=10)
        
        self.lbl_txn_limit = ctk.CTkLabel(self.header_frame, text="Txn Limit: ₹ --", font=ctk.CTkFont(size=14, weight="bold"), text_color="#e67e22")
        self.lbl_txn_limit.pack(side="right", padx=10)

        # Auto-accept threshold display
        min_lim, max_lim = self.auto_accept_min, self.auto_accept_max
        if min_lim > 0:
            if max_lim < float('inf'):
                thresh_text = f"Auto-Accept: ₹ {int(min_lim)} - {int(max_lim)}"
            else:
                thresh_text = f"Auto-Accept: ₹ {int(min_lim)}+"
        else:
            thresh_text = "Auto-Accept: OFF"
        thresh_color = "#2ecc71" if min_lim > 0 else "#95a5a6"
        self.lbl_auto_accept = ctk.CTkLabel(self.tab_live, text=thresh_text, font=ctk.CTkFont(size=13, weight="bold"), text_color=thresh_color)
        self.lbl_auto_accept.pack(pady=2)

        self.live_scroll = ctk.CTkScrollableFrame(self.tab_live)
        self.live_scroll.pack(fill="both", expand=True)
        
        hf = ctk.CTkFrame(self.tab_history)
        hf.pack(fill="both", expand=True)
        ctk.CTkButton(hf, text="REFRESH HISTORY", command=self.fetch_history).pack(pady=10)
        self.history_scroll = ctk.CTkScrollableFrame(hf)
        self.history_scroll.pack(fill="both", expand=True)

        self.status_bar = ctk.CTkFrame(self.container, height=40)
        self.status_bar.pack(fill="x", side="bottom")
        ctk.CTkLabel(self.status_bar, text=f"User: {self.current_user}", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=20)
        self.status_indicator = ctk.CTkLabel(self.status_bar, text="● Connecting...", text_color="yellow")
        self.status_indicator.pack(side="right", padx=20)
        self.log_label = ctk.CTkLabel(self.status_bar, text="Ready.")
        self.log_label.pack(side="left", padx=20)

        self.setup_settings_tab()
        self.setup_socket_events()
        threading.Thread(target=self.connect_ws, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start() # Start Heartbeat
        self.fetch_history()
        self.fetch_dashboard_data() # Initial fetch

    def heartbeat_loop(self):
        counter = 0
        while True:
            if self.token:
                try:
                    res = self.auth_manager.request("/api/pp/user/heartbeat", token=self.token)
                    # If auth failed, try re-login
                    if res and not res.get("success") and "Authentication Failed" in str(res):
                        self.auto_relogin()
                except Exception:
                    pass  # Heartbeat is non-critical, silently handle errors
                # Fetch dashboard data every 30 seconds (3 heartbeat cycles)
                if counter % 3 == 0:
                    self.fetch_dashboard_data()
            counter += 1
            time.sleep(5) # Every 10 seconds

    def fetch_dashboard_data(self):
        threading.Thread(target=self._fetch_dashboard_thread, daemon=True).start()

    def _fetch_dashboard_thread(self):
        res = self.auth_manager.request("/api/pp/user/txns_metrics", token=self.token)
        if res and res.get("success"):
            data = res.get("data", {})
            count = data.get("availableWithdrawalTxnCount", "0")
            limit = data.get("currentAvailableWithdrawalLimit", "0")
            self.after(0, lambda: self.update_limit_labels(count, limit))

    def update_limit_labels(self, count, limit):
        self.lbl_txn_count.configure(text=f"Txn Count: {count}")
        self.lbl_txn_limit.configure(text=f"Txn Limit: ₹ {limit}")

    def clear_container(self):
        for widget in self.container.winfo_children(): widget.destroy()

    def auto_relogin(self):
        self.log("Session expired. Relogging...")
        p, pw = self.current_user, self.accounts[self.current_user]["password"]
        s, r = self.auth_manager.login(p, pw)
        if s:
            self.token = r
            self.save_account(p, pw, r)
            return True
        return False

    def fetch_history(self):
        threading.Thread(target=self._fetch_history_thread, daemon=True).start()

    def _fetch_history_thread(self):
        params = {"start_date": "", "end_date": "", "txn_status": "", "txn_no": "", "utr": "", "is_dispute": "", "is_security_withdrawal": "", "page": 1, "limit": 50}
        res = self.auth_manager.request("/api/pp/withdrawal/get_txns", token=self.token, custom_payload=params)
        if res and not res.get("success") and "Authentication Failed" in str(res):
            if self.auto_relogin(): res = self.auth_manager.request("/api/pp/withdrawal/get_txns", token=self.token, custom_payload=params)
        if res and res.get("success"): self.after(0, lambda: self.update_history_ui(res["data"]["txns_data"]))

    def update_history_ui(self, txns):
        for widget in self.history_scroll.winfo_children(): widget.destroy()
        for txn in txns:
            card = ctk.CTkFrame(self.history_scroll)
            card.pack(fill="x", padx=5, pady=5)
            sc = "#27ae60" if txn.get("status") == "INITIATED" else "#e74c3c" if txn.get("status") == "REVERTED" else "gray"
            ctk.CTkLabel(card, text=f"₹ {txn.get('amount')}", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
            ctk.CTkLabel(card, text=txn.get("status"), text_color=sc).grid(row=0, column=1, padx=10, sticky="e")
            ctk.CTkButton(card, text="DETAILS", width=80, height=25, command=lambda t=txn: DetailWindow(self, t)).grid(row=1, column=0, columnspan=2, pady=5)
            card.grid_columnconfigure(1, weight=1)

    def cancel_txn(self, txn_no, detail_window):
        self.log(f"Cancelling txn {txn_no}...")
        payload = {"txn_no": txn_no, "reason": "BNK DECLINED DUE TO SECURITY ISSUE"}
        res = self.auth_manager.request("/api/pp/withdrawal/failed", method="POST", custom_payload=payload, token=self.token)
        
        if res and res.get("success"):
            self.log("Transaction Cancelled Successfully.")
            self.after(0, lambda: detail_window.destroy() if detail_window.winfo_exists() else None)
            self.fetch_history()
        else:
            self.log(f"Cancel Error: {res.get('message')}")
            self.after(0, lambda: detail_window.btn_cancel.configure(state="normal", text="CANCEL TRANSACTION") if detail_window.winfo_exists() and detail_window.btn_cancel.winfo_exists() else None)

    def setup_socket_events(self):
        @self.sio.on('connect', namespace='/pas')
        def on_connect():
            self.after(0, lambda: self.update_status("Connected", "green"))
            self.sio.emit('get_client_transaction', {}, namespace='/pas', callback=self.handle_initial_list)
        
        @self.sio.on('get_withdrawal_txn', namespace='/pas')
        def on_new_txn(data): 
            self.after(0, lambda: self.add_withdrawal_card(data))

        @self.sio.on('remove_withdrawal_txn', namespace='/pas')
        def on_remove_txn(data):
            job_id = data.get("job_id")
            if job_id in self.withdrawals:
                card = self.withdrawals[job_id]["card"]
                self.after(0, lambda: self._safe_destroy_card(job_id, card))
                self.log(f"Transaction {job_id[:8]}... taken by other.")

    def handle_initial_list(self, data):
        # Server sends callback as a dict directly, not wrapped in a list
        res = None
        if isinstance(data, dict):
            res = data
        elif isinstance(data, list) and len(data) > 0:
            res = data[0]
        
        if res and res.get("success") and "data" in res:
            txn_list = res["data"]
            self.log(f"Loaded {len(txn_list)} pending transaction(s)")
            for txn in txn_list:
                self.after(0, lambda t=txn: self.add_withdrawal_card(t))

    def connect_ws(self):
        while True:
            try:
                if not self.sio.connected:
                    self.sio.connect('https://qvablkqvweq.psrtilhtnd.com', socketio_path='/ws/', namespaces=['/pas'], auth={'token': self.token}, transports=['websocket'], headers={'User-Agent': 'okhttp/4.12.0'})
                    self.sio.wait()
            except: time.sleep(5)

    def log(self, msg): self.after(0, lambda: self.log_label.configure(text=msg))
    def update_status(self, text, color): self.status_indicator.configure(text=f"● {text}", text_color=color)

    def _safe_destroy_card(self, job_id, card):
        if card and card.winfo_exists():
            card.destroy()
        if job_id in self.withdrawals:
            del self.withdrawals[job_id]

    def add_withdrawal_card(self, data):
        job_id = data.get("job_id")
        if not job_id or job_id in self.withdrawals: return
        
        amount = float(data.get("amount", 0))
        
        # Auto-accept: re-read threshold each time so user can change it live
        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()
        
        if self.auto_accept_min > 0 and self.auto_accept_min <= amount <= self.auto_accept_max:
            max_str = 'inf' if self.auto_accept_max == float('inf') else int(self.auto_accept_max)
            self.log(f"AUTO-ACCEPTING Rs {amount} (range: {int(self.auto_accept_min)}-{max_str})")
            self.sio.emit('accept_transaction', {"job_id": job_id}, namespace='/pas')
            threading.Thread(target=self._post_accept_poll, args=(job_id, None), daemon=True).start()
            return
        
        card = ctk.CTkFrame(self.live_scroll)
        card.pack(fill="x", padx=5, pady=5)
        
        # Store data and reference to card for removal
        self.withdrawals[job_id] = {"data": data, "card": card}
        
        ctk.CTkLabel(card, text=f"₹ {data.get('amount')}", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=15, pady=10, sticky="w")
        btn = ctk.CTkButton(card, text="ACCEPT", width=100, height=40, fg_color="#27ae60")
        btn.configure(command=lambda j=job_id, b=btn, c=card: self.accept_txn(j, b, c))
        btn.grid(row=0, column=1, padx=15, pady=10, sticky="e")
        card.grid_columnconfigure(0, weight=1)

    def accept_txn(self, job_id, button, card):
        self.log(f"Accepting job {job_id}...")
        button.configure(state="disabled", text="ACCEPTING...")
        self.sio.emit('accept_transaction', {"job_id": job_id}, namespace='/pas')
        threading.Thread(target=self._post_accept_poll, args=(job_id, card), daemon=True).start()

    def _post_accept_poll(self, job_id, card):
        time.sleep(2)
        params = {"start_date": "", "end_date": "", "txn_status": "", "txn_no": "", "utr": "", "is_dispute": "", "is_security_withdrawal": "", "page": 1, "limit": 10}
        res = self.auth_manager.request("/api/pp/withdrawal/get_txns", token=self.token, custom_payload=params)
        if res and res.get("success") and res["data"]["txns_data"]:
            txn_data = res["data"]["txns_data"][0]
            if card:
                self.after(0, lambda: [DetailWindow(self, txn_data), self._safe_destroy_card(job_id, card)])
            else:
                # Auto-accepted, just log it
                self.log(f"Auto-accepted Rs {txn_data.get('amount')} - {txn_data.get('txnNo', '')}")
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
                    self.after(0, lambda: self.log(f"Sent details to {target} via Telethon"))
            except Exception as e:
                self.after(0, lambda: self.log(f"Telethon Send Error: {e}"))
                
        asyncio.run_coroutine_threadsafe(_send(), self.telethon_loop)

    def setup_settings_tab(self):
        frame = ctk.CTkFrame(self.tab_settings)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(frame, text="AUTO-ACCEPT SETTINGS", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10, 20))
        
        limit_frame = ctk.CTkFrame(frame, fg_color="transparent")
        limit_frame.pack(fill="x", padx=10)
        
        ctk.CTkLabel(limit_frame, text="Min Limit (₹):").grid(row=0, column=0, padx=10, pady=5, sticky="e")
        self.entry_min_limit = ctk.CTkEntry(limit_frame, placeholder_text="e.g., 4000")
        self.entry_min_limit.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        if self.auto_accept_min > 0: self.entry_min_limit.insert(0, str(int(self.auto_accept_min)))
        
        ctk.CTkLabel(limit_frame, text="Max Limit (₹):").grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.entry_max_limit = ctk.CTkEntry(limit_frame, placeholder_text="e.g., 5000 (leave blank for no max)")
        self.entry_max_limit.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        if self.auto_accept_max < float('inf'): self.entry_max_limit.insert(0, str(int(self.auto_accept_max)))

        ctk.CTkLabel(frame, text="TELEGRAM USERBOT SETTINGS", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(30, 20))
        
        tg_frame = ctk.CTkFrame(frame, fg_color="transparent")
        tg_frame.pack(fill="x", padx=10)
        
        fields = [("API ID:", "api_id"), ("API Hash:", "api_hash"), ("Phone:", "phone"), ("Target User:", "target_user")]
        self.tg_entries = {}
        for i, (label_text, key) in enumerate(fields):
            ctk.CTkLabel(tg_frame, text=label_text).grid(row=i, column=0, padx=10, pady=5, sticky="e")
            entry = ctk.CTkEntry(tg_frame, width=250)
            entry.grid(row=i, column=1, padx=10, pady=5, sticky="w")
            entry.insert(0, self.telegram_config.get(key, ""))
            self.tg_entries[key] = entry

        # Enable Commands Checkbox
        self.chk_enable_commands = ctk.CTkCheckBox(frame, text="Enable Remote Commands (start/stop)")
        self.chk_enable_commands.pack(pady=10)
        if self.telegram_config.get("enable_commands", True):
            self.chk_enable_commands.select()
        else:
            self.chk_enable_commands.deselect()
            
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=10)
        
        ctk.CTkButton(btn_frame, text="SAVE SETTINGS", command=self.save_settings_from_gui).pack(side="left", padx=10)
        self.btn_tg_login = ctk.CTkButton(btn_frame, text="LOGIN TO TELEGRAM", command=self.handle_tg_login, fg_color="#8e44ad", hover_color="#9b59b6")
        self.btn_tg_login.pack(side="left", padx=10)
        
        self.otp_frame = ctk.CTkFrame(frame, fg_color="transparent")
        ctk.CTkLabel(self.otp_frame, text="Enter OTP:").pack(side="left", padx=5)
        self.entry_otp = ctk.CTkEntry(self.otp_frame, width=100)
        self.entry_otp.pack(side="left", padx=5)
        ctk.CTkButton(self.otp_frame, text="SUBMIT OTP", command=self.submit_tg_otp).pack(side="left", padx=5)
        
        self.tg_status_label = ctk.CTkLabel(frame, text="Telethon Status: Disconnected", text_color="red")
        self.tg_status_label.pack(pady=5)
        
        if self.telegram_config.get("api_id") and self.telegram_config.get("phone"):
            self.start_telethon_client()

    def handle_tg_login(self):
        self.save_settings_from_gui()
        self.start_telethon_client(force_login=True)

    def start_telethon_client(self, force_login=False):
        api_id = self.telegram_config.get("api_id")
        api_hash = self.telegram_config.get("api_hash")
        phone = self.telegram_config.get("phone")
        
        if not api_id or not api_hash or not phone:
            if hasattr(self, 'tg_status_label'):
                self.tg_status_label.configure(text="Telethon Status: Missing Credentials", text_color="red")
            return
            
        try:
            api_id = int(api_id)
        except:
            if hasattr(self, 'tg_status_label'):
                self.tg_status_label.configure(text="Telethon Status: API ID must be a number", text_color="red")
            return

        # Check if already running with same credentials
        if (getattr(self, 'telethon_client', None) is not None and 
            getattr(self, 'active_tg_credentials', None) == (api_id, api_hash, phone) and 
            not force_login):
            if hasattr(self, 'tg_status_label'):
                async def update_status_async():
                    if await self.telethon_client.is_user_authorized():
                        self.after(0, lambda: self.tg_status_label.configure(text="Telethon Status: Connected & Authorized", text_color="green"))
                    else:
                        self.after(0, lambda: self.tg_status_label.configure(text="Telethon Status: Not Logged In (Click Login)", text_color="red"))
                asyncio.run_coroutine_threadsafe(update_status_async(), self.telethon_loop)
            return

        if hasattr(self, 'tg_status_label'):
            self.tg_status_label.configure(text="Telethon Status: Connecting...", text_color="yellow")
        
        if self.telethon_client:
            asyncio.run_coroutine_threadsafe(self.telethon_client.disconnect(), self.telethon_loop)
            
        # Telethon creates a .session file based on the phone number
        self.telethon_client = TelegramClient(phone, api_id, api_hash)
        self.active_tg_credentials = (api_id, api_hash, phone)

        # Register message listener for start/stop commands
        @self.telethon_client.on(events.NewMessage(incoming=True))
        async def handle_new_telegram_message(event):
            if not self.telegram_config.get("enable_commands", True):
                return
            sender = await event.get_sender()
            if not sender:
                return
            target = self.telegram_config.get("target_user", "").strip().lower()
            if not target:
                return
            target_norm = target.lstrip('@')
            sender_username = (sender.username or "").lower().lstrip('@')
            sender_phone = (sender.phone or "").strip()
            sender_id = str(sender.id)
            is_authorized = (
                sender_username == target_norm or
                sender_phone == target or
                sender_id == target
            )
            if not is_authorized:
                return
            
            text = (event.raw_text or "").strip().lower()
            if text == "start":
                await self.handle_telegram_start(event)
            elif text == "stop":
                await self.handle_telegram_stop(event)
            elif text == "status":
                await self.handle_telegram_status(event)
            elif text == "restart":
                await self.handle_telegram_restart(event)
            elif text.startswith("limit"):
                await self.handle_telegram_limit(event, text)
        
        async def _connect():
            await self.telethon_client.connect()
            if not await self.telethon_client.is_user_authorized():
                if force_login:
                    try:
                        req = await self.telethon_client.send_code_request(phone)
                        self.tg_phone_code_hash = req.phone_code_hash
                        self.after(0, lambda: [
                            self.otp_frame.pack(pady=10) if hasattr(self, 'otp_frame') else None, 
                            self.tg_status_label.configure(text="Telethon Status: Waiting for OTP", text_color="orange") if hasattr(self, 'tg_status_label') else None
                        ])
                    except Exception as e:
                        if hasattr(self, 'tg_status_label'):
                            self.after(0, lambda: self.tg_status_label.configure(text=f"Telethon Error: {e}", text_color="red"))
                else:
                    if hasattr(self, 'tg_status_label'):
                        self.after(0, lambda: self.tg_status_label.configure(text="Telethon Status: Not Logged In (Click Login)", text_color="red"))
            else:
                if hasattr(self, 'tg_status_label'):
                    self.after(0, lambda: self.tg_status_label.configure(text="Telethon Status: Connected & Authorized", text_color="green"))
                
        asyncio.run_coroutine_threadsafe(_connect(), self.telethon_loop)

    def submit_tg_otp(self):
        otp = self.entry_otp.get().strip()
        phone = self.telegram_config.get("phone")
        if not otp: return
        
        async def _sign_in():
            try:
                await self.telethon_client.sign_in(phone=phone, code=otp, phone_code_hash=getattr(self, 'tg_phone_code_hash', None))
                self.after(0, lambda: [
                    self.otp_frame.pack_forget() if hasattr(self, 'otp_frame') else None, 
                    self.tg_status_label.configure(text="Telethon Status: Connected & Authorized", text_color="green") if hasattr(self, 'tg_status_label') else None
                ])
            except Exception as e:
                if hasattr(self, 'tg_status_label'):
                    self.after(0, lambda: self.tg_status_label.configure(text=f"Telethon Login Error: {e}", text_color="red"))
                
        asyncio.run_coroutine_threadsafe(_sign_in(), self.telethon_loop)

    def save_settings_from_gui(self):
        min_val = self.entry_min_limit.get().strip()
        max_val = self.entry_max_limit.get().strip()
        
        try:
            with open(AUTO_ACCEPT_FILE, 'w') as f:
                if min_val:
                    if max_val:
                        f.write(f"{min_val}-{max_val}")
                    else:
                        f.write(min_val)
                else:
                    f.write("0")
        except Exception as e:
            self.log(f"Error saving auto-accept limits: {e}")

        # Update running values
        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()

        # Update limits label
        min_lim, max_lim = self.auto_accept_min, self.auto_accept_max
        if min_lim > 0:
            if max_lim < float('inf'):
                thresh_text = f"Auto-Accept: ₹ {int(min_lim)} - {int(max_lim)}"
            else:
                thresh_text = f"Auto-Accept: ₹ {int(min_lim)}+"
        else:
            thresh_text = "Auto-Accept: OFF"
        thresh_color = "#2ecc71" if min_lim > 0 else "#95a5a6"
        self.lbl_auto_accept.configure(text=thresh_text, text_color=thresh_color)

        # Save Telegram settings
        for key, entry in self.tg_entries.items():
            self.telegram_config[key] = entry.get().strip()
            
        # Save enable_commands setting
        if hasattr(self, 'chk_enable_commands'):
            self.telegram_config["enable_commands"] = self.chk_enable_commands.get() == 1

        try:
            with open(TELEGRAM_FILE, 'w') as f:
                json.dump(self.telegram_config, f)
        except Exception as e:
            self.log(f"Error saving telegram config: {e}")
            
        self.log("Settings saved successfully.")

    async def handle_telegram_start(self, event):
        if self.token:
            await event.reply("⚠️ Bot is already running and logged in.")
            return
        
        accs = list(self.accounts.keys())
        if not accs:
            await event.reply("❌ No saved accounts found. Please log in via the GUI first.")
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
            
        self.after(0, lambda: self.perform_telegram_quick_login(selected_account))
        await event.reply(f"🚀 Starting bot with account: `{selected_account}`...")

    def perform_telegram_quick_login(self, phone):
        self.current_user, self.token = phone, self.accounts[phone]["token"]
        self.show_dashboard()
        self.log(f"Started via Telegram command")

    async def handle_telegram_stop(self, event):
        if not self.token:
            await event.reply("⚠️ Bot is not currently running.")
            return
            
        self.after(0, self.perform_telegram_logout)
        await event.reply("🛑 Bot stopped and logged out successfully.")

    def perform_telegram_logout(self):
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass
            
        self.token = None
        self.current_user = None
        self.show_login_screen()
        self.log("Stopped and logged out via Telegram command")

    async def handle_telegram_limit(self, event, text):
        parts = text.split()
        if len(parts) >= 2:
            try:
                min_val = parts[1]
                max_val = parts[2] if len(parts) > 2 else ""
                
                float(min_val)
                if max_val:
                    float(max_val)
                    
                self.after(0, lambda: self.update_limits_from_telegram(min_val, max_val))
                await event.reply(f"✅ Auto-accept limits updated: {min_val} to {max_val if max_val else 'infinity'}")
            except ValueError:
                await event.reply("❌ Invalid format. Use: `limit <min> [max]` (e.g., `limit 100 500` or `limit 100`)")
        else:
            await event.reply("❌ Invalid format. Use: `limit <min> [max]`")

    def update_limits_from_telegram(self, min_val, max_val):
        try:
            with open(AUTO_ACCEPT_FILE, 'w') as f:
                if min_val:
                    if max_val:
                        f.write(f"{min_val}-{max_val}")
                    else:
                        f.write(min_val)
                else:
                    f.write("0")
        except Exception as e:
            self.log(f"Error saving auto-accept limits: {e}")

        self.auto_accept_min, self.auto_accept_max = self.get_auto_accept_limits()

        if hasattr(self, 'entry_min_limit') and self.entry_min_limit.winfo_exists():
            self.entry_min_limit.delete(0, 'end')
            self.entry_min_limit.insert(0, min_val)
            self.entry_max_limit.delete(0, 'end')
            if max_val:
                self.entry_max_limit.insert(0, max_val)

        if hasattr(self, 'lbl_auto_accept') and self.lbl_auto_accept.winfo_exists():
            min_lim, max_lim = self.auto_accept_min, self.auto_accept_max
            if min_lim > 0:
                if max_lim < float('inf'):
                    thresh_text = f"Auto-Accept: ₹ {int(min_lim)} - {int(max_lim)}"
                else:
                    thresh_text = f"Auto-Accept: ₹ {int(min_lim)}+"
            else:
                thresh_text = "Auto-Accept: OFF"
            thresh_color = "#2ecc71" if min_lim > 0 else "#95a5a6"
            self.lbl_auto_accept.configure(text=thresh_text, text_color=thresh_color)
            
        self.log(f"Limits updated via Telegram to {min_val}-{max_val}")

    async def handle_telegram_status(self, event):
        running_state = "🟢 Logged In" if self.token else "🔴 Not Logged In"
        account = self.current_user if self.current_user else "None"
        
        min_lim, max_lim = self.auto_accept_min, self.auto_accept_max
        if min_lim > 0:
            if max_lim < float('inf'):
                limit_text = f"₹ {int(min_lim)} - {int(max_lim)}"
            else:
                limit_text = f"₹ {int(min_lim)}+"
        else:
            limit_text = "OFF"
            
        status_msg = (
            f"✅ **App is Running!**\n\n"
            f"👤 **Account:** `{account}`\n"
            f"🔌 **State:** {running_state}\n"
            f"🤖 **Auto-Accept:** {limit_text}\n"
            f"⚡ **Socket Connected:** {'Yes' if self.sio.connected else 'No'}\n"
            f"🕒 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await event.reply(status_msg)

    async def handle_telegram_restart(self, event):
        await event.reply("🔄 Restarting application... Please wait a moment.")
        self.log("Restart initiated via Telegram command")
        await asyncio.sleep(1)
        
        # We intentionally DO NOT gracefully disconnect Telethon here!
        # Calling await self.telethon_client.disconnect() from inside its own event handler
        # causes a complete deadlock, freezing the app and preventing it from closing.
        # We rely on os._exit(0) below to forcefully terminate and drop the connection.
        
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except: pass
            
        import tempfile
        import time
        
        executable_path = sys.executable if getattr(sys, 'frozen', False) else f"{sys.executable} app.py"
        app_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))
        
        bat_path = os.path.join(tempfile.gettempdir(), "restart_bot.bat")
        
        with open(bat_path, "w") as f:
            f.write("@echo off\n")
            f.write("echo Restarting WithdrawalBot...\n")
            # Use ping instead of timeout because timeout fails if there is no console!
            # When the batch script runs detached, timeout instantly crashes, causing the app
            # to restart immediately while SQLite is still locked, resulting in a silent crash.
            f.write("ping 127.0.0.1 -n 4 > NUL\n")
            
            # Strip Pyinstaller env vars
            f.write("set _PYI_APPLICATION_HOME_DIR=\n")
            f.write("set _PYI_ARCHIVE_FILE=\n")
            f.write("set _PYI_PARENT_PROCESS_LEVEL=\n")
            f.write("set _MEIPASS2=\n")
            f.write("set _MEIPASS=\n")
            f.write("set TCL_LIBRARY=\n")
            f.write("set TK_LIBRARY=\n")
            
            f.write(f'cd /d "{app_dir}"\n')
            f.write(f'start "" "{executable_path}"\n')
            f.write('del "%~f0"\n')
            
        os.startfile(bat_path)
        time.sleep(0.5)
        os._exit(0)
        
if __name__ == "__main__":
    app = WithdrawalBotApp()
    app.mainloop()
