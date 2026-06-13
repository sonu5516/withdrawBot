import flet as ft
import sys
import os

# Add parent directory to path so we can import shared bot_core and auth
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot_core import WithdrawalBotCore

def main(page: ft.Page):
    page.title = "Withdrawal Bot (Flet Android Edition)"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    status_text = ft.Text("Disconnected", color=ft.colors.RED)
    log_text = ft.Text("Ready.", italic=True)
    
    # UI Elements
    phone_input = ft.TextField(label="Phone Number", width=300)
    pass_input = ft.TextField(label="Password", password=True, can_reveal_password=True, width=300)
    
    txn_count_label = ft.Text("Txn Count: --", weight=ft.FontWeight.BOLD, color=ft.colors.BLUE)
    txn_limit_label = ft.Text("Txn Limit: ₹ --", weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE)
    auto_accept_label = ft.Text("Auto-Accept: OFF", weight=ft.FontWeight.BOLD, color=ft.colors.GREY)

    history_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
    live_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    # Core Callbacks
    def update_log(msg):
        log_text.value = msg
        page.update()

    def update_status(text, color):
        status_text.value = f"● {text}"
        status_text.color = ft.colors.GREEN if color == "green" else ft.colors.RED
        page.update()

    def handle_login_success(phone, token):
        login_view.visible = False
        dashboard_view.visible = True
        page.update()

    def handle_login_error(msg):
        update_log(msg)

    def handle_limits_update(count, limit):
        txn_count_label.value = f"Txn Count: {count}"
        txn_limit_label.value = f"Txn Limit: ₹ {limit}"
        page.update()
        
    def handle_history_update(txns):
        history_col.controls.clear()
        for txn in txns:
            sc = ft.colors.GREEN if txn.get("status") == "INITIATED" else ft.colors.RED if txn.get("status") == "REVERTED" else ft.colors.GREY
            history_col.controls.append(
                ft.Card(
                    content=ft.Container(
                        padding=10,
                        content=ft.Row([
                            ft.Text(f"₹ {txn.get('amount')}", weight=ft.FontWeight.BOLD),
                            ft.Text(txn.get("status"), color=sc)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    )
                )
            )
        page.update()
        
    def handle_new_txn(data):
        job_id = data.get("job_id")
        amount = data.get("amount")
        
        def accept_click(e):
            btn = e.control
            btn.text = "ACCEPTING..."
            btn.disabled = True
            page.update()
            bot.accept_txn(job_id)
            
        card = ft.Card(
            content=ft.Container(
                padding=10,
                content=ft.Row([
                    ft.Text(f"₹ {amount}", size=20, weight=ft.FontWeight.BOLD),
                    ft.ElevatedButton("ACCEPT", on_click=accept_click, bgcolor=ft.colors.GREEN, color=ft.colors.WHITE)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            )
        )
        live_col.controls.append(card)
        page.update()
        
    def handle_auto_accept_limits_update(min_val, max_val):
        if min_val > 0:
            if max_val < float('inf'):
                auto_accept_label.value = f"Auto-Accept: ₹ {int(min_val)} - {int(max_val)}"
            else:
                auto_accept_label.value = f"Auto-Accept: ₹ {int(min_val)}+"
            auto_accept_label.color = ft.colors.GREEN
        else:
            auto_accept_label.value = "Auto-Accept: OFF"
            auto_accept_label.color = ft.colors.GREY
        page.update()

    callbacks = {
        "log": update_log,
        "on_status_change": update_status,
        "on_login_success": handle_login_success,
        "on_login_error": handle_login_error,
        "on_limits_update": handle_limits_update,
        "on_history_update": handle_history_update,
        "on_new_txn": handle_new_txn,
        "on_auto_accept_limits_update": handle_auto_accept_limits_update
    }
    
    # Initialize Core Backend
    bot = WithdrawalBotCore(callbacks)

    # Login View
    def do_login(e):
        bot.perform_login(phone_input.value, pass_input.value)

    login_view = ft.Column([
        ft.Text("ACCOUNT MANAGER", size=24, weight=ft.FontWeight.BOLD),
        phone_input,
        pass_input,
        ft.ElevatedButton("LOGIN", on_click=do_login)
    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

    # Dashboard View
    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        tabs=[
            ft.Tab(
                text="LIVE FEED",
                content=ft.Column([
                    ft.Row([txn_count_label, txn_limit_label], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    auto_accept_label,
                    live_col
                ])
            ),
            ft.Tab(
                text="HISTORY",
                content=history_col
            )
        ],
        expand=1,
    )

    dashboard_view = ft.Column([
        tabs
    ], expand=True, visible=False)

    page.add(
        login_view,
        dashboard_view,
        ft.Divider(),
        ft.Row([status_text, log_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    )
    
    # Auto-login check
    if bot.accounts:
        sorted_accs = sorted(bot.accounts.items(), key=lambda x: x[1].get("last_login", ""), reverse=True)
        bot.quick_login(sorted_accs[0][0])

if __name__ == "__main__":
    ft.app(target=main)
