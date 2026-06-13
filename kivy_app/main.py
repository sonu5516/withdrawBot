from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.lang import Builder
from kivy.clock import Clock
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot_core import WithdrawalBotCore

Builder.load_file('withdrawal.kv')

class LoginScreen(Screen):
    pass

class DashboardScreen(Screen):
    pass

class WithdrawalKivyApp(App):
    def build(self):
        self.sm = ScreenManager()
        self.login_screen = LoginScreen(name='login')
        self.dashboard_screen = DashboardScreen(name='dashboard')
        self.sm.add_widget(self.login_screen)
        self.sm.add_widget(self.dashboard_screen)

        # Setup callbacks
        callbacks = {
            "log": self.on_log,
            "on_status_change": self.on_status_change,
            "on_login_success": self.on_login_success,
            "on_login_error": self.on_login_error,
            "on_limits_update": self.on_limits_update,
            "on_history_update": self.on_history_update,
            "on_new_txn": self.on_new_txn
        }
        self.bot = WithdrawalBotCore(callbacks)

        # Auto login check
        if self.bot.accounts:
            sorted_accs = sorted(self.bot.accounts.items(), key=lambda x: x[1].get("last_login", ""), reverse=True)
            self.bot.quick_login(sorted_accs[0][0])

        return self.sm

    def do_login(self):
        phone = self.login_screen.ids.phone_input.text
        password = self.login_screen.ids.pass_input.text
        self.bot.perform_login(phone, password)

    def on_log(self, msg):
        Clock.schedule_once(lambda dt: setattr(self.dashboard_screen.ids.log_label, 'text', msg))

    def on_status_change(self, text, color):
        Clock.schedule_once(lambda dt: setattr(self.dashboard_screen.ids.status_label, 'text', text))

    def on_login_success(self, phone, token):
        Clock.schedule_once(lambda dt: setattr(self.sm, 'current', 'dashboard'))

    def on_login_error(self, msg):
        self.on_log(msg)

    def on_limits_update(self, count, limit):
        Clock.schedule_once(lambda dt: setattr(self.dashboard_screen.ids.limit_label, 'text', f"Count: {count} | Limit: ₹ {limit}"))

    def on_history_update(self, txns):
        # Update history UI (Placeholder for simplicity)
        pass

    def on_new_txn(self, data):
        # Add new txn to live feed (Placeholder for simplicity)
        pass

if __name__ == '__main__':
    WithdrawalKivyApp().run()
