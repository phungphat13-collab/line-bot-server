# local_daemon.py - 24/7 LIÊN TỤC KẾT NỐI
import requests
import time
import json
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException, NoSuchWindowException, TimeoutException
import logging
import sys
import os
from datetime import datetime, time as dt_time, timedelta

# ==================== ⚙️ CẤU HÌNH 24/7 ====================
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
GROUP_ID = "ZpXWbVLYaj"  # ID nhóm LINE

# ⚠️ CHỈ 4 MỐC THỜI GIAN KẾT THÚC CA
SHIFT_CHECK_TIMES = [
    {"shift": "Ca 1", "time": dt_time(11, 0)},   # 11:00
    {"shift": "Ca 2", "time": dt_time(15, 0)},   # 15:00
    {"shift": "Ca 3", "time": dt_time(18, 30)},  # 18:30
    {"shift": "Ca 4", "time": dt_time(7, 0)}     # 7:00 (ngày tiếp theo)
]

# CẤU HÌNH HEARTBEAT 24/7
HEARTBEAT_INTERVAL = 30  # Gửi heartbeat mỗi 30 giây
HEARTBEAT_RETRY_COUNT = 3  # Số lần thử lại nếu thất bại
MAX_CONSECUTIVE_FAILURES = 10  # Tối đa 10 lần thất bại liên tiếp

# MÀU SẮC CHO TEXT
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    ORANGE = '\033[38;5;214m'
    PINK = '\033[38;5;205m'
    LIGHT_BLUE = '\033[38;5;117m'
    LIGHT_GREEN = '\033[38;5;120m'
    GOLD = '\033[38;5;220m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GRAY = '\033[38;5;245m'

# CẤU HÌNH LOGGING
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('automation.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== ❤️ HEARTBEAT MANAGER 24/7 ====================

class HeartbeatManager:
    """Quản lý gửi heartbeat định kỳ đến server - HOẠT ĐỘNG 24/7"""
    
    def __init__(self, server_communicator, session_manager):
        self.server = server_communicator
        self.session_manager = session_manager
        self.running = False
        self.heartbeat_thread = None
        self.last_success = None
        self.failure_count = 0
        self.consecutive_failures = 0
        self.heartbeat_counter = 0
        self.start_time = datetime.now()
        
    def start(self):
        """Bắt đầu gửi heartbeat - LUÔN CHẠY KỂ CẢ STANDBY"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
        
        self.running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_worker_24_7)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        logger.info(f"{Colors.GREEN}[HEARTBEAT] Bắt đầu gửi heartbeat 24/7 mỗi {HEARTBEAT_INTERVAL} giây{Colors.RESET}")
    
    def stop(self):
        """Dừng gửi heartbeat"""
        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5)
        logger.info(f"{Colors.YELLOW}[HEARTBEAT] Đã dừng{Colors.RESET}")
    
    def _heartbeat_worker_24_7(self):
        """Luồng gửi heartbeat HOẠT ĐỘNG 24/7"""
        last_log_time = time.time()
        
        while self.running:
            try:
                self.heartbeat_counter += 1
                current_counter = self.heartbeat_counter
                
                # 🔄 KIỂM TRA VÀ ĐẢM BẢO CÓ CLIENT_ID
                if not self.server.user_id:
                    logger.info(f"{Colors.YELLOW}[HEARTBEAT #{current_counter}] Chưa có client_id, thử đăng ký lại...{Colors.RESET}")
                    registration_data = self.server.register()
                    if not registration_data:
                        logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Không thể đăng ký lại với server{Colors.RESET}")
                        time.sleep(HEARTBEAT_INTERVAL)
                        continue
                
                # CHUẨN BỊ DỮ LIỆU HEARTBEAT
                heartbeat_data = {
                    "status": "standby",  # Mặc định là standby
                    "timestamp": datetime.now().isoformat(),
                    "counter": current_counter,
                    "version": "3.0_24_7",
                    "uptime": str(datetime.now() - self.start_time).split('.')[0]
                }
                
                # THÊM THÔNG TIN PHIÊN NẾU ĐANG ACTIVE
                active_user = self.session_manager.get_active_user()
                if active_user:
                    heartbeat_data["username"] = active_user
                    heartbeat_data["status"] = "in_session"
                    
                    # Thêm thông tin session
                    session_info = self.session_manager.get_session_info()
                    if session_info.get('login_time'):
                        try:
                            if isinstance(session_info['login_time'], datetime):
                                login_time = session_info['login_time']
                            else:
                                login_time = datetime.fromisoformat(session_info['login_time'].replace('Z', '+00:00'))
                            
                            session_duration = datetime.now() - login_time
                            hours = int(session_duration.total_seconds() // 3600)
                            minutes = int((session_duration.total_seconds() % 3600) // 60)
                            heartbeat_data["session_duration"] = f"{hours}h{minutes}m"
                        except:
                            pass
                
                # GỬI HEARTBEAT ĐẾN SERVER
                success = self._send_heartbeat_with_retry(heartbeat_data)
                
                if success:
                    self.consecutive_failures = 0
                    self.last_success = datetime.now()
                    
                    # HIỂN THỊ LOG MỖI 5 PHÚT (10 LẦN HEARTBEAT) ĐỂ KHÔNG SPAM LOG
                    current_time = time.time()
                    if current_time - last_log_time > 300:  # 5 phút
                        status_display = "IN SESSION" if active_user else "STANDBY"
                        uptime = datetime.now() - self.start_time
                        hours = int(uptime.total_seconds() // 3600)
                        minutes = int((uptime.total_seconds() % 3600) // 60)
                        
                        logger.info(f"{Colors.GREEN}[HEARTBEAT #{current_counter}] {status_display} - Đã gửi {current_counter} lần - Uptime: {hours}h{minutes}m{Colors.RESET}")
                        last_log_time = current_time
                else:
                    self.consecutive_failures += 1
                    self.failure_count += 1
                    
                    # NẾU THẤT BẠI NHIỀU LẦN, THỬ ĐĂNG KÝ LẠI
                    if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error(f"{Colors.RED}[HEARTBEAT] Mất kết nối nghiêm trọng ({self.consecutive_failures} lần liên tiếp){Colors.RESET}")
                        logger.info(f"{Colors.YELLOW}[HEARTBEAT] Thử đăng ký lại với server...{Colors.RESET}")
                        
                        # RESET CLIENT_ID VÀ ĐĂNG KÝ LẠI
                        self.server.user_id = None
                        registration_data = self.server.register()
                        if registration_data:
                            self.consecutive_failures = 0
                            logger.info(f"{Colors.GREEN}[HEARTBEAT] Đã đăng ký lại thành công{Colors.RESET}")
                        else:
                            logger.error(f"{Colors.RED}[HEARTBEAT] Không thể đăng ký lại{Colors.RESET}")
                
                # CHỜ INTERVAL
                for i in range(HEARTBEAT_INTERVAL):
                    if not self.running:
                        break
                    
                    # HIỂN THỊ COUNTDOWN MỖI 30 GIÂY
                    time_left = HEARTBEAT_INTERVAL - i
                    if time_left == 30 and current_counter % 2 == 0:  # Mỗi phút hiển thị 1 lần
                        status = "[SESSION]" if active_user else "[STANDBY]"
                        logger.debug(f"{Colors.GRAY}[HEARTBEAT] {status} #{current_counter} - Gửi tiếp sau {time_left}s...{Colors.RESET}")
                    
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"{Colors.RED}[HEARTBEAT] Lỗi không xác định: {e}{Colors.RESET}")
                time.sleep(HEARTBEAT_INTERVAL)
    
    def _send_heartbeat_with_retry(self, heartbeat_data, max_retries=2):
        """Gửi heartbeat với cơ chế retry"""
        for retry in range(max_retries + 1):
            try:
                response = requests.post(
                    f"{self.server.server_url}/api/heartbeat/{self.server.user_id}",
                    json=heartbeat_data,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('status') == 'reconnected':
                        logger.info(f"{Colors.GREEN}[HEARTBEAT] Đã kết nối lại với server{Colors.RESET}")
                        return True
                    elif data.get('status') == 'ok':
                        # LOG DEBUG MỖI 30 LẦN HEARTBEAT
                        if self.heartbeat_counter % 30 == 0:
                            logger.debug(f"{Colors.GRAY}[HEARTBEAT] ✓ Server nhận heartbeat ({heartbeat_data['status']}){Colors.RESET}")
                        return True
                    else:
                        logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Server trả về lỗi: {data.get('message')}{Colors.RESET}")
                
                elif response.status_code == 404:
                    # CLIENT KHÔNG TỒN TẠI TRÊN SERVER
                    logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Client không tồn tại trên server, đăng ký lại...{Colors.RESET}")
                    self.server.user_id = None
                    return False
                
                else:
                    logger.warning(f"{Colors.YELLOW}[HEARTBEAT] HTTP {response.status_code}{Colors.RESET}")
            
            except requests.exceptions.ConnectionError:
                logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Lỗi kết nối (lần {retry + 1}){Colors.RESET}")
            except requests.exceptions.Timeout:
                logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Timeout (lần {retry + 1}){Colors.RESET}")
            except Exception as e:
                logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Lỗi: {e} (lần {retry + 1}){Colors.RESET}")
            
            # NẾU CHƯA THÀNH CÔNG VÀ CÒN RETRY, CHỜ MỘT CHÚT RỒI THỬ LẠI
            if retry < max_retries:
                time.sleep(2 ** retry)  # Exponential backoff: 1s, 2s, 4s...
        
        return False
    
    def get_stats(self):
        """Lấy thống kê heartbeat"""
        return {
            "heartbeat_counter": self.heartbeat_counter,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "uptime": str(datetime.now() - self.start_time).split('.')[0],
            "status": "running" if self.running else "stopped"
        }

# ==================== 🏥 HEALTH MONITOR ====================

class HealthMonitor:
    """Giám sát sức khỏe hệ thống 24/7"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.last_check = None
        self.error_count = 0
        self.success_count = 0
        self.heartbeat_stats = {
            "total_sent": 0,
            "total_failed": 0,
            "last_success": None
        }
    
    def check_server_connection(self, server_url):
        """Kiểm tra kết nối đến server"""
        try:
            response = requests.get(f"{server_url}/health", timeout=5)
            if response.status_code == 200:
                self.last_check = datetime.now()
                self.error_count = 0
                self.success_count += 1
                return True
        except Exception as e:
            logger.error(f"{Colors.RED}[HEALTH] Lỗi kết nối server: {e}{Colors.RESET}")
            self.error_count += 1
        return False
    
    def update_heartbeat_stats(self, success):
        """Cập nhật thống kê heartbeat"""
        self.heartbeat_stats["total_sent"] += 1
        if success:
            self.heartbeat_stats["last_success"] = datetime.now()
        else:
            self.heartbeat_stats["total_failed"] += 1
    
    def get_stats(self):
        """Lấy thống kê"""
        uptime = datetime.now() - self.start_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        
        # Tính tỷ lệ thành công
        total_attempts = self.success_count + self.error_count
        success_rate = f"{(self.success_count/total_attempts*100):.1f}%" if total_attempts > 0 else "0%"
        
        # Tính tỷ lệ heartbeat
        hb_success_rate = "100%"
        if self.heartbeat_stats["total_sent"] > 0:
            hb_success = self.heartbeat_stats["total_sent"] - self.heartbeat_stats["total_failed"]
            hb_success_rate = f"{(hb_success/self.heartbeat_stats['total_sent']*100):.1f}%"
        
        return {
            "uptime": f"{hours}h{minutes}p",
            "last_check": self.last_check.strftime("%H:%M:%S") if self.last_check else "N/A",
            "error_count": self.error_count,
            "success_count": self.success_count,
            "success_rate": success_rate,
            "heartbeat_sent": self.heartbeat_stats["total_sent"],
            "heartbeat_failed": self.heartbeat_stats["total_failed"],
            "heartbeat_success_rate": hb_success_rate,
            "last_heartbeat": self.heartbeat_stats["last_success"].strftime("%H:%M:%S") if self.heartbeat_stats["last_success"] else "N/A"
        }

# ==================== 📋 SESSION MANAGER ====================

class SessionManager:
    """Lớp quản lý phiên làm việc client-side"""
    
    def __init__(self):
        self.active_session = {
            "username": None,
            "login_time": None,
            "is_active": False,
            "session_id": None,
            "server_session": None,
            "client_id": None
        }
        self.lock = threading.Lock()
    
    def start_session(self, username, client_id, session_info=None):
        """Bắt đầu phiên làm việc mới"""
        with self.lock:
            session_id = session_info.get('session_id') if session_info else f"local_session_{int(time.time())}"
            
            self.active_session = {
                "username": username,
                "login_time": datetime.now(),
                "is_active": True,
                "session_id": session_id,
                "server_session": session_info,
                "client_id": client_id
            }
            return True, f"Phiên làm việc cho {username} đã bắt đầu (Client: {client_id[:10]}...)"
    
    def end_session(self, username=None):
        """Kết thúc phiên làm việc"""
        with self.lock:
            if self.active_session["is_active"]:
                ended_user = self.active_session["username"]
                ended_client = self.active_session["client_id"]
                self.active_session = {
                    "username": None,
                    "login_time": None,
                    "is_active": False,
                    "session_id": None,
                    "server_session": None,
                    "client_id": None
                }
                return True, f"Đã kết thúc phiên làm việc của {ended_user} (Client: {ended_client[:10]}...)"
            return False, "Không có phiên làm việc đang hoạt động"
    
    def force_end_session(self):
        """Buộc kết thúc phiên"""
        with self.lock:
            if self.active_session["is_active"]:
                ended_user = self.active_session["username"]
                ended_client = self.active_session["client_id"]
                self.active_session = {
                    "username": None,
                    "login_time": None,
                    "is_active": False,
                    "session_id": None,
                    "server_session": None,
                    "client_id": None
                }
                return True, f"Đã buộc kết thúc phiên làm việc của {ended_user} (Client: {ended_client[:10]}...)"
            return False, "Không có phiên làm việc đang hoạt động"
    
    def get_active_user(self):
        """Lấy user đang hoạt động"""
        with self.lock:
            return self.active_session["username"] if self.active_session["is_active"] else None
    
    def get_client_id(self):
        """Lấy client_id đang hoạt động"""
        with self.lock:
            return self.active_session["client_id"] if self.active_session["is_active"] else None
    
    def is_session_active(self):
        """Kiểm tra có phiên làm việc đang hoạt động không"""
        with self.lock:
            return self.active_session["is_active"]
    
    def get_session_info(self):
        """Lấy thông tin phiên"""
        with self.lock:
            return self.active_session.copy()

# ==================== ⏰ TIME MANAGER ====================

class TimeManager:
    """Lớp quản lý thời gian đơn giản - CHỈ CHECK 4 MỐC THỜI GIAN"""
    
    def __init__(self, shift_check_times):
        self.shift_check_times = shift_check_times
    
    def should_end_session_by_time(self):
        """Kiểm tra xem đã đến mốc thời gian kết thúc ca chưa"""
        now = datetime.now()
        current_time = now.time()
        
        for shift_info in self.shift_check_times:
            check_time = shift_info["time"]
            shift_name = shift_info["shift"]
            
            # Kiểm tra nếu đúng mốc thời gian (±1 phút để tránh miss)
            if self._is_time_match(current_time, check_time):
                logger.info(f"⏰ ĐẾN MỐC THỜI GIAN: {shift_name} - {check_time.strftime('%H:%M')}")
                return True, shift_name
        
        return False, None
    
    def _is_time_match(self, current_time, check_time, tolerance_minutes=1):
        """Kiểm tra thời gian có khớp với mốc check không (±tolerance phút)"""
        current_dt = datetime.combine(datetime.today(), current_time)
        check_dt = datetime.combine(datetime.today(), check_time)
        
        # Điều chỉnh cho Ca 4 (7:00 sáng hôm sau)
        if check_time == dt_time(7, 0) and current_time < dt_time(7, 0):
            # Nếu bây giờ < 7h, check_dt phải là hôm qua
            check_dt = datetime.combine(datetime.today() - timedelta(days=1), check_time)
        
        time_diff = abs((current_dt - check_dt).total_seconds())
        return time_diff <= tolerance_minutes * 60
    
    def get_next_shift_check(self):
        """Lấy thông tin mốc thời gian tiếp theo cần check"""
        now = datetime.now()
        current_time = now.time()
        
        for shift_info in self.shift_check_times:
            check_time = shift_info["time"]
            
            # Chuyển sang datetime để so sánh
            check_dt = datetime.combine(now.date(), check_time)
            
            # Điều chỉnh cho Ca 4
            if check_time == dt_time(7, 0):
                if current_time >= dt_time(7, 0):
                    # Nếu đã qua 7h hôm nay, thì check tiếp là 7h ngày mai
                    check_dt = datetime.combine(now.date() + timedelta(days=1), check_time)
            
            if now < check_dt:
                time_until = (check_dt - now).total_seconds()
                hours = int(time_until // 3600)
                minutes = int((time_until % 3600) // 60)
                return {
                    "shift": shift_info["shift"],
                    "time": check_time,
                    "time_until": f"{hours}h{minutes}p",
                    "seconds_until": time_until
                }
        
        # Nếu không tìm thấy, trả về Ca 1 ngày mai
        next_day = now.date() + timedelta(days=1)
        first_shift = self.shift_check_times[0]  # Ca 1
        check_dt = datetime.combine(next_day, first_shift["time"])
        time_until = (check_dt - now).total_seconds()
        hours = int(time_until // 3600)
        minutes = int((time_until % 3600) // 60)
        
        return {
            "shift": first_shift["shift"],
            "time": first_shift["time"],
            "time_until": f"{hours}h{minutes}p",
            "seconds_until": time_until
        }

# ==================== 📡 SERVER COMMUNICATOR ====================

class ServerCommunicator:
    """Lớp xử lý giao tiếp với server - 24/7"""
    
    def __init__(self, server_url, group_id):
        self.server_url = server_url
        self.group_id = group_id
        self.user_id = None  # client_id từ server
        self.max_retries = 3
        self.retry_delay = 5
        self.heartbeat_manager = None
    
    def set_heartbeat_manager(self, heartbeat_manager):
        """Thiết lập heartbeat manager"""
        self.heartbeat_manager = heartbeat_manager
    
    def send_message(self, text):
        """Gửi tin nhắn LINE NHÓM"""
        if not self.group_id:
            logger.error(f"{Colors.RED}[ERROR] Không gửi được LINE (chưa có group_id): {text}{Colors.RESET}")
            return False
            
        try:
            response = requests.post(
                f"{self.server_url}/api/send_message",
                json={
                    "user_id": self.group_id,
                    "message": text
                },
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"{Colors.GREEN}[SENT] Đã gửi tới GROUP: {text[:100]}...{Colors.RESET}")
                return True
            else:
                logger.error(f"{Colors.RED}[ERROR] Gửi LINE group thất bại: {response.text}{Colors.RESET}")
                return False
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Lỗi gửi LINE group: {e}{Colors.RESET}")
            return False
    
    def register(self):
        """Đăng ký với server và nhận client_id - CÓ RETRY"""
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{self.server_url}/api/register_local",
                    json={"client_info": "local_daemon_24_7"},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'registered':
                        self.user_id = data.get('client_id')
                        logger.info(f"{Colors.GREEN}[OK] Đã đăng ký với client_id: {self.user_id}{Colors.RESET}")
                        
                        # KHỞI ĐỘNG HEARTBEAT NẾU ĐƯỢC YÊU CẦU
                        if data.get('heartbeat_required') and self.heartbeat_manager:
                            if not self.heartbeat_manager.running:
                                self.heartbeat_manager.start()
                        
                        # Kiểm tra nếu có lệnh đang chờ
                        if data.get('has_command'):
                            command = data.get('command')
                            logger.info(f"{Colors.YELLOW}[WAIT] Có lệnh đang chờ: {command.get('type')}{Colors.RESET}")
                        
                        return data
                
                logger.warning(f"{Colors.YELLOW}[RETRY] Đăng ký thất bại lần {attempt + 1}{Colors.RESET}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    
            except Exception as e:
                logger.error(f"{Colors.RED}[ERROR] Lỗi đăng ký lần {attempt + 1}: {e}{Colors.RESET}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        return None
    
    def check_commands(self):
        """Kiểm tra lệnh từ server"""
        if not self.user_id:
            return None
            
        try:
            response = requests.get(
                f"{self.server_url}/api/get_commands/{self.user_id}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('has_command'):
                    command = data.get('command')
                    logger.info(f"{Colors.CYAN}[CMD] Nhận được lệnh: {command.get('type')}{Colors.RESET}")
                    return command
            return None
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Kiểm tra lệnh thất bại: {e}{Colors.RESET}")
            return None
    
    def start_server_session(self, username):
        """Bắt đầu phiên trên server"""
        try:
            response = requests.post(
                f"{self.server_url}/api/start_session",
                json={
                    "username": username,
                    "user_id": self.user_id
                },
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Lỗi bắt đầu session server: {e}{Colors.RESET}")
            return {"status": "error", "message": str(e)}
    
    def end_server_session(self, username, reason="normal_exit", message=""):
        """Kết thúc phiên trên server"""
        try:
            response = requests.post(
                f"{self.server_url}/api/end_session",
                json={
                    "username": username,
                    "reason": reason,
                    "message": message,
                    "user_id": self.user_id
                },
                timeout=5
            )
            return response.json()
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Lỗi kết thúc session server: {e}{Colors.RESET}")
            return {"status": "error", "message": str(e)}
    
    def force_end_server_session(self, reason="browser_closed_abruptly", message=""):
        """Buộc kết thúc phiên trên server"""
        try:
            response = requests.post(
                f"{self.server_url}/api/force_end_session",
                json={
                    "reason": reason,
                    "message": message,
                    "user_id": self.user_id
                },
                timeout=5
            )
            return response.json()
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Lỗi force end session server: {e}{Colors.RESET}")
            return {"status": "error", "message": str(e)}
    
    def get_session_info(self):
        """Lấy thông tin phiên từ server"""
        try:
            response = requests.get(
                f"{self.server_url}/api/get_session_info",
                timeout=5
            )
            return response.json()
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Lỗi lấy session info: {e}{Colors.RESET}")
            return {"is_active": False}
    
    def mark_command_completed(self, command_id, command_type=None):
        """Đánh dấu lệnh đã xử lý"""
        try:
            response = requests.post(
                f"{self.server_url}/api/complete_command",
                json={
                    "user_id": self.user_id,
                    "command_id": command_id,
                    "command_type": command_type
                },
                timeout=5
            )
            if response.status_code == 200:
                logger.info(f"{Colors.GREEN}[OK] Đã hoàn thành lệnh: {command_id} ({command_type}){Colors.RESET}")
                return True
            else:
                logger.error(f"{Colors.RED}[ERROR] Hoàn thành lệnh thất bại: {response.text}{Colors.RESET}")
                return False
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Hoàn thành lệnh thất bại: {e}{Colors.RESET}")
            return False
    
    def check_client_status(self):
        """Kiểm tra trạng thái client trên server"""
        if not self.user_id:
            return None
            
        try:
            response = requests.get(
                f"{self.server_url}/api/client_status/{self.user_id}",
                timeout=5
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Kiểm tra client status thất bại: {e}{Colors.RESET}")
            return None

# ==================== 🤖 WEB AUTOMATION ====================

class WebAutomation:
    """Lớp xử lý automation web - ĐÃ ĐƠN GIẢN HÓA"""
    
    def __init__(self, time_manager, session_manager, server_communicator):
        self.driver = None
        self.running = False
        self.current_username = None
        self.time_manager = time_manager
        self.session_manager = session_manager
        self.server = server_communicator
        self.browser_monitor_thread = None
        self.browser_abruptly_closed = False
    
    # ... (CÁC PHƯƠNG THỨC KHÁC GIỮ NGUYÊN NHƯ TRONG CODE CŨ) ...
    # CHỈ THÊM HEARTBEAT VÀO CÁC PHƯƠNG THỨC HIỆN CÓ
    
    def login(self, username, password):
        """Đăng nhập vào hệ thống - CẬP NHẬT"""
        try:
            # Reset trạng thái thoát đột ngột
            self.browser_abruptly_closed = False
            
            logger.info(f"{Colors.BLUE}[LOGIN] Đang đăng nhập cho {username}{Colors.RESET}")
            
            # GỬI HEARTBEAT ĐẶC BIỆT KHI BẮT ĐẦU LOGIN
            self._send_login_heartbeat(username, "start")
            
            # ... (PHẦN LOGIN GIỮ NGUYÊN) ...
            
        except Exception as e:
            logger.error(f"{Colors.RED}[LOGIN] Lỗi đăng nhập: {e}{Colors.RESET}")
            # GỬI HEARTBEAT LỖI
            self._send_login_heartbeat(username, "error", str(e))
            return False, f"Lỗi đăng nhập: {str(e)}"
    
    def _send_login_heartbeat(self, username, status, message=""):
        """Gửi heartbeat đặc biệt cho quá trình login"""
        if self.server.user_id:
            try:
                heartbeat_data = {
                    "status": f"login_{status}",
                    "username": username,
                    "message": message,
                    "timestamp": datetime.now().isoformat()
                }
                requests.post(
                    f"{self.server.server_url}/api/heartbeat/{self.server.user_id}",
                    json=heartbeat_data,
                    timeout=5
                )
            except:
                pass

# ==================== 🎮 COMMAND PROCESSOR ====================

class CommandProcessor:
    """Lớp xử lý lệnh - ĐÃ ĐỒNG BỘ"""
    
    def __init__(self, server_communicator, web_automation, time_manager, session_manager):
        self.server = server_communicator
        self.automation = web_automation
        self.time_manager = time_manager
        self.session_manager = session_manager
    
    def process_command(self, command_data):
        """Xử lý lệnh nhận được"""
        if not command_data:
            return
            
        command_type = command_data.get('type')
        command_id = command_data.get('id')
        
        logger.info(f"{Colors.CYAN}[CMD] Xử lý lệnh: {command_type}{Colors.RESET}")
        
        if command_type == 'start_automation':
            self._handle_start_command(command_data)
        elif command_type == 'stop_automation':
            self._handle_stop_command(command_data)
        
        # Đánh dấu lệnh đã xử lý
        if command_id:
            self.server.mark_command_completed(command_id, command_type)
    
    def _handle_start_command(self, command_data):
        """Xử lý lệnh bắt đầu automation"""
        username = command_data.get('username')
        password = command_data.get('password')
        
        if not username or not password:
            self.server.send_message("[ERROR] Thiếu username/password")
            return
        
        logger.info(f"{Colors.MAGENTA}[LOGIN] Nhận lệnh login cho {username}{Colors.RESET}")
        
        # Kiểm tra phiên local
        active_user = self.session_manager.get_active_user()
        if active_user:
            logger.error(f"{Colors.RED}[ERROR] Đã có phiên local của {active_user}{Colors.RESET}")
            return
        
        # 🔥 BẮT ĐẦU PHIÊN TRÊN SERVER TRƯỚC
        logger.info(f"{Colors.BLUE}[SESSION] Đang bắt đầu phiên trên server...{Colors.RESET}")
        server_session = self.server.start_server_session(username)
        
        if server_session.get('status') == 'conflict':
            # CÓ USER KHÁC ĐANG SỬ DỤNG
            conflict_msg = server_session.get('message', 'Có phiên đang chạy')
            logger.error(f"{Colors.RED}[CONFLICT] {conflict_msg}{Colors.RESET}")
            self.server.send_message(f"[CONFLICT] {conflict_msg}")
            return
        
        if server_session.get('status') != 'started':
            # LỖI KHÁC
            error_msg = server_session.get('message', 'Không thể bắt đầu phiên')
            logger.error(f"{Colors.RED}[ERROR] {error_msg}{Colors.RESET}")
            self.server.send_message(f"[ERROR] {error_msg}")
            return
        
        logger.info(f"{Colors.GREEN}[SESSION] Đã bắt đầu phiên trên server thành công{Colors.RESET}")
        
        # BẮT ĐẦU PHIÊN LOCAL
        success, session_message = self.session_manager.start_session(
            username, 
            self.server.user_id,
            server_session.get('session_info')
        )
        if not success:
            logger.error(f"{Colors.RED}[ERROR] {session_message}{Colors.RESET}")
            self.server.force_end_server_session("session_start_failed", "Không thể bắt đầu phiên local")
            return
        
        logger.info(f"{Colors.GREEN}[SESSION] Đã bắt đầu phiên local cho {username}{Colors.RESET}")
        self.automation.current_username = username
        
        # Chạy automation trong thread riêng
        thread = threading.Thread(target=self._run_automation, args=(username, password))
        thread.daemon = True
        thread.start()
    
    def _run_automation(self, username, password):
        """Chạy automation"""
        if self.automation.running:
            self.automation.stop()
            time.sleep(3)
        
        self.automation.running = True
        
        try:
            logger.info(f"{Colors.BLUE}[AUTO] Đang khởi động automation cho {username}{Colors.RESET}")
            
            if not self.automation.init_driver():
                # 🔥 TRƯỜNG HỢP 2: LỖI KHỞI TẠO DRIVER
                error_msg = "Không thể khởi tạo trình duyệt"
                logger.error(f"{Colors.RED}[ERROR] {error_msg}{Colors.RESET}")
                
                # 🔥 BƯỚC 1: GỬI THÔNG BÁO LINE TRƯỚC
                self.server.send_message(
                    f"❌ **{username} - {error_msg}**\n"
                    f"📌 Hệ thống đã về STANDBY"
                )
                
                # 🔥 BƯỚC 2: GỌI API ĐỂ RESET PHIÊN TRÊN SERVER
                self.server.force_end_server_session(
                    "driver_init_failed", 
                    error_msg
                )
                
                # 🔥 BƯỚC 3: RESET LOCAL
                self.session_manager.end_session(username)
                self.automation.current_username = None
                self.automation.running = False
                return
            
            # THỬ ĐĂNG NHẬP
            login_success, login_message = self.automation.login(username, password)
            
            if not login_success:
                # 🔥 TRƯỜNG HỢP 3: ĐĂNG NHẬP KHÔNG THÀNH CÔNG
                logger.error(f"{Colors.RED}[LOGIN] {login_message}{Colors.RESET}")
                
                # 🔥 BƯỚC 1: GỬI THÔNG BÁO LINE TRƯỚC
                self.server.send_message(
                    f"❌ **{username} đăng nhập thất bại**\n"
                    f"📌 {login_message}\n"
                    f"📌 Hệ thống đã về STANDBY"
                )
                
                # 🔥 BƯỚC 2: GỌI API ĐỂ RESET PHIÊN TRÊN SERVER
                self.server.force_end_server_session(
                    "login_failed", 
                    login_message
                )
                
                # 🔥 BƯỚC 3: RESET LOCAL
                try:
                    if self.automation.driver:
                        self.automation.driver.quit()
                        self.automation.driver = None
                except:
                    pass
                
                self.session_manager.end_session(username)
                self.automation.current_username = None
                self.automation.running = False
                return
            
            # CHỌN NHÓM LINE
            if not self.automation.select_group_line():
                # 🔥 TRƯỜNG HỢP: KHÔNG TÌM THẤY NHÓM LINE
                error_msg = "Không tìm thấy nhóm LINE"
                logger.error(f"{Colors.RED}[ERROR] {error_msg}{Colors.RESET}")
                
                # XỬ LÝ NHƯ .thoát web
                self.automation._handle_session_end(
                    username=username,
                    reason="group_select_failed",
                    message=f"❌ **{username} - {error_msg}**\n📌 Hệ thống đã về STANDBY"
                )
                return
            
            logger.info(f"{Colors.GREEN}[OK] Bắt đầu xử lý ticket cho {username}{Colors.RESET}")
            
            # HIỂN THỊ THÔNG TIN MỐC THỜI GIAN TIẾP THEO
            next_check = self.time_manager.get_next_shift_check()
            logger.info(f"{Colors.YELLOW}[TIME] Mốc thời gian tiếp theo: {next_check['shift']} lúc {next_check['time'].strftime('%H:%M')} (còn {next_check['time_until']}){Colors.RESET}")
            
            self.automation.find_and_process_tickets()
                
        except Exception as e:
            logger.error(f"{Colors.RED}[ERROR] Lỗi automation: {e}{Colors.RESET}")
            
            # XỬ LÝ NHƯ .thoát web KHI CÓ LỖI
            if username:
                self.automation._handle_session_end(
                    username=username,
                    reason="automation_error",
                    message=f"⚠️ **{username} - Lỗi hệ thống**\n📌 {str(e)[:100]}\n📌 Hệ thống đã về STANDBY"
                )
    
    def _handle_stop_command(self, command_data):
        """Xử lý lệnh dừng automation - TRƯỜNG HỢP .thoát web"""
        username = command_data.get('username')
        active_user = self.session_manager.get_active_user()
        
        if not active_user:
            logger.info(f"{Colors.YELLOW}[STOP] Không có phiên nào để dừng{Colors.RESET}")
            return
        
        if username and username != active_user:
            logger.error(f"{Colors.RED}[STOP] Không thể dừng phiên của user khác{Colors.RESET}")
            return
        
        logger.info(f"{Colors.YELLOW}[STOP] Đang dừng phiên của {active_user} (lệnh .thoát web){Colors.RESET}")
        
        # GỌI HÀM STOP CỦA AUTOMATION (sẽ xử lý như .thoát web)
        self.automation.stop()

# ==================== 🏗️ AUTO TICKET DAEMON 24/7 ====================

class AutoTicketDaemon:
    """Lớp chính điều phối toàn bộ hệ thống - HOẠT ĐỘNG 24/7"""
    
    def __init__(self, server_url, group_id):
        self.time_manager = TimeManager(SHIFT_CHECK_TIMES)
        self.session_manager = SessionManager()
        self.server = ServerCommunicator(server_url, group_id)
        
        # THÊM HEARTBEAT MANAGER 24/7
        self.heartbeat_manager = HeartbeatManager(self.server, self.session_manager)
        self.server.set_heartbeat_manager(self.heartbeat_manager)
        
        self.automation = WebAutomation(self.time_manager, self.session_manager, self.server)
        self.processor = CommandProcessor(self.server, self.automation, self.time_manager, self.session_manager)
        self.health_monitor = HealthMonitor()
        self.running = False
        
        # Thống kê
        self.check_count = 0
        self.command_count = 0
        self.heartbeat_count = 0
        self.start_time = datetime.now()
        self.connection_established = False
    
    def start_daemon(self):
        """Bắt đầu chạy nền - 24/7 MODE"""
        print(f"""{Colors.CYAN}{Colors.BOLD}
==========================================
   KHỞI ĐỘNG LOCAL DAEMON - 24/7 MODE
    (LUÔN KẾT NỐI VỚI SERVER)
=========================================={Colors.RESET}""")
        print(f"{Colors.LIGHT_BLUE}[SERVER] {SERVER_URL}{Colors.RESET}")
        print(f"{Colors.LIGHT_BLUE}[GROUP] Line Group: {GROUP_ID}{Colors.RESET}")
        print(f"{Colors.GREEN}[SYSTEM] Hệ thống đã kích hoạt chế độ 24/7{Colors.RESET}")
        print(f"{Colors.MAGENTA}[HEARTBEAT] Luôn gửi nhịp tim mỗi 30 giây{Colors.RESET}")
        print(f"{Colors.YELLOW}[MODE] STANDBY → Heartbeat → Chờ lệnh .login{Colors.RESET}")
        
        # HIỂN THỊ MỐC THỜI GIAN
        print(f"{Colors.YELLOW}[TIME] 4 MỐC THỜI GIAN KẾT THÚC CA:{Colors.RESET}")
        for shift in SHIFT_CHECK_TIMES:
            print(f"{Colors.YELLOW}  • {shift['shift']}: {shift['time'].strftime('%H:%M')}{Colors.RESET}")
        
        # LẤY MỐC TIẾP THEO
        next_check = self.time_manager.get_next_shift_check()
        print(f"{Colors.CYAN}──────────────────────────────────────{Colors.RESET}")
        print(f"{Colors.MAGENTA}[NEXT] Mốc tiếp theo: {next_check['shift']} lúc {next_check['time'].strftime('%H:%M')} (còn {next_check['time_until']}){Colors.RESET}")
        
        # ĐĂNG KÝ VỚI SERVER - THỬ CHO ĐẾN KHI THÀNH CÔNG
        print(f"{Colors.BLUE}[CONNECT] Đang kết nối với server...{Colors.RESET}")
        
        max_retries = 10
        for attempt in range(max_retries):
            if self._initial_connect():
                print(f"{Colors.GREEN}[SUCCESS] Kết nối server thành công sau {attempt + 1} lần thử{Colors.RESET}")
                self.connection_established = True
                break
            else:
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)
                    print(f"{Colors.YELLOW}[RETRY] Thử lại sau {wait_time} giây... ({attempt + 1}/{max_retries}){Colors.RESET}")
                    time.sleep(wait_time)
                else:
                    print(f"{Colors.RED}[WARNING] Không thể kết nối server sau {max_retries} lần thử{Colors.RESET}")
                    print(f"{Colors.YELLOW}[INFO] Vẫn tiếp tục thử kết nối trong nền...{Colors.RESET}")
        
        # BẮT ĐẦU HEARTBEAT 24/7 (LUÔN CHẠY KỂ CẢ CHƯA ĐĂNG KÝ THÀNH CÔNG)
        self.heartbeat_manager.start()
        
        self.running = True
        failed_attempts = 0
        last_status_display = time.time()
        
        print(f"{Colors.GREEN}[READY] Hệ thống đã sẵn sàng 24/7{Colors.RESET}")
        print(f"{Colors.YELLOW}[STATUS] Hiển thị trạng thái mỗi 30 giây...{Colors.RESET}")
        print(f"{Colors.CYAN}──────────────────────────────────────{Colors.RESET}")
        
        while self.running:
            try:
                self.check_count += 1
                
                # HIỂN THỊ TRẠNG THÁI MỖI 30 GIÂY
                current_time = time.time()
                if current_time - last_status_display > 30:
                    self._display_status_24_7()
                    last_status_display = current_time
                
                # KIỂM TRA HEALTH MỖI 2 PHÚT
                if self.check_count % 40 == 0:
                    if not self.health_monitor.check_server_connection(self.server.server_url):
                        logger.warning(f"{Colors.YELLOW}[HEALTH] Kết nối server không ổn định{Colors.RESET}")
                
                # KIỂM TRA LỆNH
                command = self.server.check_commands()
                if command:
                    self.command_count += 1
                    logger.info(f"{Colors.MAGENTA}[COMMAND] Nhận được lệnh: {command.get('type')}{Colors.RESET}")
                    self.processor.process_command(command)
                    self.check_count = 0
                    failed_attempts = 0
                else:
                    # NẾU KHÔNG CÓ LỆNH, KIỂM TRA KẾT NỐI ĐỊNH KỲ
                    if self.check_count % 20 == 0:
                        if not self.server.user_id:
                            # THỬ ĐĂNG KÝ LẠI NẾU MẤT CLIENT_ID
                            logger.info(f"{Colors.BLUE}[RECONNECT] Mất client_id, thử đăng ký lại...{Colors.RESET}")
                            self._initial_connect()
                        else:
                            # KIỂM TRA TRẠNG THÁI CLIENT TRÊN SERVER
                            client_status = self.server.check_client_status()
                            if client_status and not client_status.get('is_alive', True):
                                logger.warning(f"{Colors.YELLOW}[STATUS] Server báo client không sống, thử đăng ký lại...{Colors.RESET}")
                                self.server.user_id = None
                
                # NẾU NHIỀU LẦN KHÔNG NHẬN ĐƯỢC LỆNH, THỬ ĐĂNG KÝ LẠI
                if self.check_count % 50 == 0 and failed_attempts < 3:
                    logger.info(f"{Colors.BLUE}[RECONNECT] Kiểm tra lại kết nối server...{Colors.RESET}")
                    if not self.server.user_id:
                        self._initial_connect()
                    failed_attempts += 1
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                print(f"\n{Colors.CYAN}[STOP] DỪNG THEO YÊU CẦU{Colors.RESET}")
                self.stop()
                break
            except Exception as e:
                logger.error(f"{Colors.RED}Daemon error: {e}{Colors.RESET}")
                time.sleep(10)
    
    def _initial_connect(self):
        """Kết nối ban đầu với server"""
        try:
            # Đăng ký với server
            data = self.server.register()
            if data:
                logger.info(f"{Colors.GREEN}[REGISTER] Đã đăng ký với client_id: {self.server.user_id}{Colors.RESET}")
                
                # Kiểm tra nếu có lệnh đang chờ
                if data.get('has_command'):
                    command = data.get('command')
                    logger.info(f"{Colors.YELLOW}[WAIT] Có lệnh đang chờ ngay sau đăng ký: {command.get('type')}{Colors.RESET}")
                    # Xử lý lệnh ngay
                    self.processor.process_command(command)
                
                return True
            return False
        except Exception as e:
            logger.error(f"{Colors.RED}Initial connect error: {e}{Colors.RESET}")
            return False
    
    def _display_status_24_7(self):
        """Hiển thị trạng thái hệ thống 24/7"""
        # Lấy mốc thời gian tiếp theo
        next_check = self.time_manager.get_next_shift_check()
        
        # Trạng thái client
        if self.server.user_id:
            client_status = f"{Colors.LIGHT_BLUE}ClientID: {self.server.user_id[:10]}...{Colors.RESET}"
        else:
            client_status = f"{Colors.RED}[SEARCH] Đang tìm kết nối...{Colors.RESET}"
        
        # Trạng thái phiên
        active_user = self.session_manager.get_active_user()
        if active_user:
            session_status = f"{Colors.GREEN}[SESSION] {active_user}{Colors.RESET}"
            automation_status = f"{Colors.GREEN}[RUNNING]{Colors.RESET}"
        else:
            session_status = f"{Colors.YELLOW}[STANDBY] Chờ lệnh{Colors.RESET}"
            automation_status = f"{Colors.RED}[STOPPED]{Colors.RESET}"
        
        # Kiểm tra session trên server
        server_session = self.server.get_session_info()
        if server_session.get('is_active'):
            server_status = f"{Colors.GREEN}[SERVER] ACTIVE{Colors.RESET}"
        else:
            server_status = f"{Colors.YELLOW}[SERVER] STANDBY{Colors.RESET}"
        
        # Heartbeat stats
        heartbeat_stats = self.heartbeat_manager.get_stats()
        hb_counter = heartbeat_stats.get('heartbeat_counter', 0)
        
        # Uptime
        uptime = datetime.now() - self.start_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        uptime_str = f"{hours}h{minutes}m"
        
        print(f"{Colors.WHITE}[{datetime.now().strftime('%H:%M:%S')}]{Colors.RESET} {Colors.CYAN}Uptime: {uptime_str}{Colors.RESET} {Colors.WHITE}|{Colors.RESET} {Colors.MAGENTA}Next: {next_check['shift']} ({next_check['time_until']}){Colors.RESET} {Colors.WHITE}|{Colors.RESET} {client_status} {Colors.WHITE}|{Colors.RESET} {session_status} {Colors.WHITE}|{Colors.RESET} {server_status} {Colors.WHITE}|{Colors.RESET} {Colors.CYAN}❤️{hb_counter}{Colors.RESET} {Colors.GRAY}✓{self.command_count}{Colors.RESET}")
    
    def stop(self):
        """Dừng toàn bộ hệ thống"""
        self.running = False
        self.heartbeat_manager.stop()
        self.automation.stop()
        # Kết thúc mọi phiên làm việc đang active
        self.session_manager.force_end_session()
        logger.info(f"{Colors.CYAN}[STOP] Đã dừng hệ thống{Colors.RESET}")
        
        # Hiển thị thống kê
        health_stats = self.health_monitor.get_stats()
        heartbeat_stats = self.heartbeat_manager.get_stats()
        
        print(f"\n{Colors.CYAN}📊 THỐNG KÊ HOẠT ĐỘNG 24/7:{Colors.RESET}")
        print(f"{Colors.YELLOW}• Thời gian chạy: {health_stats['uptime']}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Tổng lệnh xử lý: {self.command_count}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Tổng heartbeat: {heartbeat_stats.get('heartbeat_counter', 0)}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Tỷ lệ kết nối: {health_stats['success_rate']}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Tỷ lệ heartbeat: {health_stats['heartbeat_success_rate']}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Lần kết nối cuối: {health_stats['last_check']}{Colors.RESET}")

# ==================== 🚀 CHẠY CHƯƠNG TRÌNH ====================

def main():
    try:
        print(f"{Colors.CYAN}{Colors.BOLD}=========================================={Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}   HỆ THỐNG TỰ ĐỘNG TICKET - 24/7 MODE   {Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}=========================================={Colors.RESET}")
        
        # Kiểm tra dependencies
        try:
            import selenium
            print(f"{Colors.GREEN}[CHECK] Selenium: OK{Colors.RESET}")
        except ImportError:
            print(f"{Colors.RED}[ERROR] Chưa cài đặt selenium{Colors.RESET}")
            print(f"{Colors.YELLOW}[HINT] Chạy: pip install selenium{Colors.RESET}")
            return
        
        try:
            import requests
            print(f"{Colors.GREEN}[CHECK] Requests: OK{Colors.RESET}")
        except ImportError:
            print(f"{Colors.RED}[ERROR] Chưa cài đặt requests{Colors.RESET}")
            print(f"{Colors.YELLOW}[HINT] Chạy: pip install requests{Colors.RESET}")
            return
        
        print(f"{Colors.GREEN}[SYSTEM] Tất cả dependencies đã sẵn sàng{Colors.RESET}")
        
        # Khởi động daemon
        daemon = AutoTicketDaemon(SERVER_URL, GROUP_ID)
        daemon.start_daemon()
        
    except KeyboardInterrupt:
        print(f"\n{Colors.CYAN}[EXIT] Thoát chương trình{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Lỗi khởi động: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
