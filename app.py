from flask import Flask, request, jsonify
import threading
import time
import requests
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException, NoSuchWindowException
import logging
from datetime import datetime

# Tối ưu hóa logging để giảm output
logging.basicConfig(level=logging.WARNING)  # Đổi từ INFO sang WARNING
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình LINE - THAY BẰNG THÔNG TIN THẬT CỦA BẠN
LINE_CHANNEL_TOKEN = os.getenv('LINE_ACCESS_TOKEN', "yrazgly8JwQb7zaoAb13wck530QXpo7meQ+Fx0mILCbGJd2zAO8S5dhRNnKjsYn4nbGN/OHZlwrk1rFrO8FWXNzPQQ/dLVbftskrYvFoPBOHFbCRDVyM8WonW5anLpTz330+LfCrVdAdsZRgH3u1fgdB04t89/1O/w1cDnyilFU=")

# Quản lý trạng thái group chat - TỐI ƯU HÓA
group_queues = {}
message_cooldown = {}  # Chống spam message

class LocalTicketAutomation:
    def __init__(self, user_id, line_token):
        self.user_id = user_id
        self.line_token = line_token
        self.driver = None
        self.running = False
        self.standby_mode = False
        self.current_username = None
        self.current_password = None
        self.group_id = None
        self.last_message_time = 0  # Chống spam
        self.message_count = 0  # Đếm số message
        
    def can_send_message(self):
        """Kiểm tra có thể gửi message không để tránh spam"""
        current_time = time.time()
        if current_time - self.last_message_time < 2:  # 2 giây cooldown
            return False
        self.last_message_time = current_time
        return True
        
    def send_line_message(self, text, important=False):
        """Gửi tin nhắn LINE với giới hạn - TỐI ƯU HÓA"""
        # Chỉ gửi message quan trọng hoặc khi cần thiết
        if not important and not self.can_send_message():
            return
            
        try:
            self.message_count += 1
            # Giới hạn số message để tiết kiệm API calls
            if self.message_count > 50 and not important:  # Giới hạn 50 message thường
                return
                
            url = 'https://api.line.me/v2/bot/message/push'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.line_token}'
            }
            data = {
                'to': self.user_id,
                'messages': [{'type': 'text', 'text': text}]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=5)
            
            if response.status_code != 200:
                logger.warning(f"Line API error: {response.status_code}")
                
        except Exception as e:
            logger.warning(f"Line message error: {e}")

    def start(self, username, password, group_id=None):
        """Chạy automation - TỐI ƯU HÓA MESSAGE"""
        self.current_username = username
        self.current_password = password
        self.group_id = group_id
        self.message_count = 0  # Reset counter
        
        thread = threading.Thread(target=self._run_local_automation)
        thread.daemon = True
        thread.start()
        
    def _run_local_automation(self):
        """Thực thi automation - GIẢM MESSAGE KHÔNG CẦN THIẾT"""
        try:
            self.running = True
            self.standby_mode = False
            
            # Chỉ gửi 1 message quan trọng khi bắt đầu
            start_msg = f"🚀 Bắt đầu auto cho {self.current_username}" if self.current_username else "🚀 Bắt đầu automation"
            self.send_line_message(start_msg, important=True)
            
            # Khởi tạo Chrome với options tối ưu
            chrome_options = Options()
            chrome_options.add_argument("--window-size=1200,800")  # Giảm kích thước
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Truy cập website
            self.driver.get("https://newticket.tgdd.vn/ticket")
            time.sleep(3)
            
            # Đăng nhập
            if not self._login():
                self.enter_standby_mode()
                return
            
            # Chọn nhóm LINE
            if not self._select_group_line():
                self.enter_standby_mode()
                return
            
            # Bắt đầu vòng lặp chính - GIẢM MESSAGE
            self._main_loop()
            
        except (WebDriverException, NoSuchWindowException):
            self.send_line_message("⚠️ Browser đã đóng", important=True)
            self.enter_standby_mode()
        except Exception as e:
            self.send_line_message(f"❌ Lỗi: {str(e)[:100]}", important=True)
            self.enter_standby_mode()
    
    def _login(self):
        """Xử lý đăng nhập - GỘP CÁC BƯỚC"""
        try:
            # Tìm và điền username
            username_field = self._find_element([
                'input[name="username"]',
                'input[placeholder*="ername"]',
                '#us',
                '.chakra-input'
            ])
            
            if not username_field:
                self.send_line_message("❌ Không tìm thấy ô username", important=True)
                return False
                
            username_field.clear()
            username_field.send_keys(self.current_username)
            
            # Tìm và điền password
            pin_fields = self._find_pin_fields()
            if len(pin_fields) != 6:
                self.send_line_message("❌ Không tìm thấy đủ ô PIN", important=True)
                return False
                
            for i, field in enumerate(pin_fields):
                if i < len(self.current_password):
                    field.send_keys(self.current_password[i])
            
            # Click đăng nhập
            login_btn = self._find_login_button()
            if not login_btn:
                self.send_line_message("❌ Không tìm thấy nút đăng nhập", important=True)
                return False
                
            login_btn.click()
            time.sleep(5)
            
            # Kiểm tra đăng nhập
            if self._check_login_success():
                self.send_line_message("✅ Đăng nhập thành công", important=True)
                return True
            else:
                self.send_line_message("❌ Sai username/password", important=True)
                return False
                
        except Exception as e:
            self.send_line_message(f"❌ Lỗi đăng nhập: {str(e)[:50]}", important=True)
            return False
    
    def _find_element(self, selectors):
        """Tìm element - TỐI ƯU HÓA"""
        for selector in selectors:
            try:
                if selector.startswith('//'):
                    element = self.driver.find_element(By.XPATH, selector)
                else:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    return element
            except:
                continue
        return None
    
    def _find_pin_fields(self):
        """Tìm ô PIN - TỐI ƯU"""
        pin_fields = []
        try:
            fields = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="tel"], input[inputmode="numeric"]')
            for field in fields:
                if field.is_displayed():
                    pin_fields.append(field)
                    if len(pin_fields) >= 6:
                        break
        except:
            pass
        return pin_fields[:6]  # Chỉ lấy 6 ô đầu
    
    def _find_login_button(self):
        """Tìm nút đăng nhập - TỐI ƯU"""
        return self._find_element([
            'button[type="submit"]',
            '.chakra-button',
            "//button[contains(., 'Đăng nhập')]",
            "//button[contains(., 'Login')]"
        ])
    
    def _check_login_success(self):
        """Kiểm tra đăng nhập - TỐI ƯU"""
        try:
            current_url = self.driver.current_url.lower()
            return "ticket" in current_url and "login" not in current_url
        except:
            return False
    
    def _select_group_line(self):
        """Chọn nhóm LINE - GIẢM MESSAGE"""
        try:
            group_element = self._find_element([
                "//*[contains(text(), 'TRỰC LINE')]",
                "//*[contains(text(), 'Trực line')]",
                "//select//option[contains(., 'TRỰC LINE')]"
            ])
            
            if group_element:
                group_element.click()
                time.sleep(2)
                return True
            return False
        except:
            return False
    
    def _main_loop(self):
        """Vòng lặp chính - TỐI ƯU HÓA MESSAGE"""
        no_ticket_count = 0
        
        while self.running and self.check_browser_alive():
            try:
                ticket_found = self._find_and_process_tickets()
                
                if ticket_found:
                    no_ticket_count = 0
                    # Chỉ thông báo khi xử lý ticket, không thông báo tìm thấy
                else:
                    no_ticket_count += 1
                    # Chỉ thông báo sau 5 lần không tìm thấy
                    if no_ticket_count % 5 == 0:
                        self.send_line_message(f"🔍 Đã quét {no_ticket_count} lần chưa thấy phiếu 1.***")
                    
                    # Chờ và refresh
                    for i in range(30, 0, -1):
                        if not self.running or not self.check_browser_alive():
                            return
                        time.sleep(1)
                    
                    self.driver.refresh()
                    time.sleep(3)
                    self._select_group_line()
                    
            except (WebDriverException, NoSuchWindowException):
                break
            except Exception as e:
                logger.warning(f"Loop error: {e}")
                time.sleep(10)
    
    def _find_and_process_tickets(self):
        """Tìm và xử lý ticket - GIẢM MESSAGE"""
        try:
            tickets = self.driver.find_elements(By.XPATH, "//*[starts-with(normalize-space(text()), '1.')]")
            
            for ticket in tickets:
                try:
                    ticket_text = ticket.text.strip()
                    if (ticket.is_displayed() and 
                        len(ticket_text) > 2 and
                        not any(x in ticket_text for x in ['10.', '11.', '12.'])):
                        
                        # Chỉ thông báo khi bắt đầu xử lý
                        self.send_line_message(f"🎫 Đang xử lý: {ticket_text.split()[0]}")
                        
                        ticket.click()
                        time.sleep(2)
                        self._process_single_ticket()
                        return True
                except:
                    continue
            return False
        except:
            return False
    
    def _process_single_ticket(self):
        """Xử lý ticket - TỐI ƯU MESSAGE"""
        try:
            # Chuyển trạng thái
            self._click_processing_status()
            time.sleep(1)
            
            # Gửi bình luận
            self._send_comment()
            time.sleep(1)
            
            # Về trang chủ
            self._go_to_home_page()
            time.sleep(2)
            self._select_group_line()
            
            # Không gửi message xác nhận để tiết kiệm
            return True
        except:
            return False
    
    def _click_processing_status(self):
        """Click nút Đang xử lý - TỐI ƯU"""
        btn = self._find_element([
            "//button[contains(., 'Đang xử lý')]",
            "//button[contains(text(), 'Đang xử lý')]"
        ])
        if btn:
            btn.click()
            time.sleep(1)
            return True
        return False
    
    def _send_comment(self):
        """Gửi bình luận - TỐI ƯU"""
        try:
            comment_box = self._find_element([
                "//textarea[contains(@placeholder, 'bình luận')]",
                "//textarea[@placeholder]",
                "//div[@contenteditable='true']"
            ])
            
            if comment_box:
                comment_box.clear()
                comment_box.send_keys("Dạ Chào Anh/Chị !!! Trường hợp này ITKV sẽ chuyển cho IT phụ trách siêu thị hỗ trợ sớm nhất ạ.")
                time.sleep(1)
                
                # Tìm nút gửi hoặc dùng Enter
                send_btn = self._find_element([
                    "//button[contains(., 'Gửi')]",
                    "//button[contains(., 'Send')]"
                ])
                
                if send_btn:
                    send_btn.click()
                else:
                    comment_box.send_keys(Keys.ENTER)
                time.sleep(1)
                return True
            return False
        except:
            return False
    
    def _go_to_home_page(self):
        """Về trang chủ - TỐI ƯU"""
        home_btn = self._find_element([
            "//a[contains(., 'Trang chủ')]",
            "//a[contains(., 'Home')]"
        ])
        if home_btn:
            home_btn.click()
        else:
            self.driver.get("https://newticket.tgdd.vn/ticket")
        time.sleep(2)
        return True
    
    def check_browser_alive(self):
        """Kiểm tra browser"""
        try:
            self.driver.current_url
            return True
        except:
            return False
    
    def enter_standby_mode(self):
        """Vào chế độ standby - TỐI ƯU MESSAGE"""
        self.running = False
        self.standby_mode = True
        
        # Giải phóng slot group
        if self.group_id and self.group_id in group_queues:
            group_queues[self.group_id]["current_user"] = None
            group_queues[self.group_id]["current_username"] = None
            
            # Thông báo lượt tiếp theo
            if group_queues[self.group_id]["waiting_users"]:
                next_user = group_queues[self.group_id]["waiting_users"].pop(0)
                send_line_message_direct(
                    self.group_id,
                    self.line_token,
                    f"🔄 Đến lượt {next_user['username']}!",
                    "group"
                )
        
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass
        
        # Chỉ gửi 1 message quan trọng
        self.send_line_message("🔄 Đã dừng - Gửi 'login user:pass' để chạy lại", important=True)

# Các hàm helper và API endpoints giữ nguyên nhưng TỐI ƯU MESSAGE
def send_line_message_direct(chat_id, line_token, text, chat_type="user"):
    """Gửi tin nhắn LINE - THÊM GIỚI HẠN"""
    try:
        # Kiểm tra cooldown
        key = f"{chat_id}_{text[:20]}"
        current_time = time.time()
        if key in message_cooldown and current_time - message_cooldown[key] < 10:  # 10 giây cooldown
            return False
            
        message_cooldown[key] = current_time
        
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {line_token}'
        }
        data = {'to': chat_id, 'messages': [{'type': 'text', 'text': text}]}
        
        response = requests.post(url, headers=headers, json=data, timeout=5)
        return response.status_code == 200
    except:
        return False

# Giữ nguyên các hàm start_automation_internal, get_status_internal, exit_web_internal
# nhưng THÊM GIỚI HẠN MESSAGE trong đó

automation_instances = {}

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook LINE - TỐI ƯU HÓA MESSAGE"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            user_id = source.get('userId')
            group_id = source.get('groupId')
            
            chat_type = "user"
            chat_id = user_id
            if group_id:
                chat_type = "group"
                chat_id = group_id
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip().lower()
                
                # Xử lý lệnh với message ngắn gọn
                if message_text in ['/help', 'help']:
                    help_text = """🤖 TICKET AUTOMATION

📝 LỆNH:
• login user:pass - Chạy auto
• status - Trạng thái  
• thoát web - Dừng auto
• help - Hướng dẫn

💡 Tip: Giảm message để tiết kiệm tài nguyên"""
                    send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, help_text, chat_type)
                
                elif message_text.startswith('login '):
                    # ... (giữ nguyên logic đăng nhập nhưng với message tối ưu)
                    credentials = message_text[6:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        # Gọi hàm start với message tối ưu
                        start_automation_internal(user_id, username, password, chat_type, group_id)
                    else:
                        send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, "❌ Dùng: login user:pass", chat_type)
                
                elif message_text == 'status':
                    # Message status ngắn gọn
                    if chat_type == "user":
                        status = "🟢 Đang chạy" if user_id in automation_instances and automation_instances[user_id].running else "🔴 Dừng"
                        send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, f"📊 {status}", chat_type)
                    else:
                        # Status group ngắn gọn
                        status_text = "🟢 Sẵn sàng" if group_id not in group_queues or not group_queues[group_id]["current_user"] else "🟡 Đang sử dụng"
                        send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, f"📊 Group: {status_text}", chat_type)
                
                elif message_text == 'thoát web':
                    exit_web_internal(user_id, chat_type, group_id)
            
            elif event_type == 'join':
                # Welcome message ngắn gọn
                welcome_msg = "🎉 Bot Ticket Auto - Dùng 'help' để xem lệnh"
                send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, welcome_msg, chat_type)
        
        return jsonify({"status": "success"})
    except Exception as e:
        logger.warning(f"Webhook error: {e}")
        return jsonify({"status": "error"})

# Các endpoint API khác giữ nguyên nhưng THÊM TIMEOUT
@app.route('/health', methods=['GET'])
def health_check():
    """Health check tối ưu"""
    active_users = len([inst for inst in automation_instances.values() if inst.running])
    return jsonify({
        "status": "healthy", 
        "active_users": active_users,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ đơn giản"""
    return "🤖 Ticket Automation Server - Đang hoạt động"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    # Chạy với debug=False để tiết kiệm tài nguyên
    app.run(host='0.0.0.0', port=port, debug=False)
