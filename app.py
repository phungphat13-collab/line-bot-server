# ==================== ⚙️ CẤU HÌNH ====================
# THÊM CẤU HÌNH HEARTBEAT
HEARTBEAT_INTERVAL = 30  # Gửi heartbeat mỗi 30 giây
HEARTBEAT_RETRY_COUNT = 3  # Số lần thử lại nếu thất bại

# ... (phần đầu giữ nguyên) ...

class HeartbeatManager:
    """Quản lý gửi heartbeat định kỳ đến server"""
    
    def __init__(self, server_communicator, session_manager):
        self.server = server_communicator
        self.session_manager = session_manager
        self.running = False
        self.heartbeat_thread = None
        self.last_success = None
        self.failure_count = 0
        
    def start(self):
        """Bắt đầu gửi heartbeat"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
        
        self.running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_worker)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        logger.info(f"{Colors.GREEN}[HEARTBEAT] Bắt đầu gửi heartbeat mỗi {HEARTBEAT_INTERVAL} giây{Colors.RESET}")
    
    def stop(self):
        """Dừng gửi heartbeat"""
        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5)
        logger.info(f"{Colors.YELLOW}[HEARTBEAT] Đã dừng{Colors.RESET}")
    
    def _heartbeat_worker(self):
        """Luồng gửi heartbeat"""
        while self.running:
            try:
                if self.server.user_id:  # Chỉ gửi nếu có client_id
                    # Chuẩn bị dữ liệu heartbeat
                    heartbeat_data = {
                        "status": "active",
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    # Thêm thông tin phiên nếu đang active
                    active_user = self.session_manager.get_active_user()
                    if active_user:
                        heartbeat_data["username"] = active_user
                        heartbeat_data["status"] = "in_session"
                    
                    # Gửi heartbeat đến server
                    try:
                        response = requests.post(
                            f"{self.server.server_url}/api/heartbeat/{self.server.user_id}",
                            json=heartbeat_data,
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if data.get('status') in ['ok', 'reconnected']:
                                self.last_success = datetime.now()
                                self.failure_count = 0
                                
                                if data.get('status') == 'reconnected':
                                    logger.info(f"{Colors.GREEN}[HEARTBEAT] Đã kết nối lại với server{Colors.RESET}")
                                
                                # Log mỗi 10 lần thành công
                                if self.failure_count == 0 and int(time.time()) % 300 < HEARTBEAT_INTERVAL:
                                    logger.debug(f"{Colors.GRAY}[HEARTBEAT] Đã gửi thành công{Colors.RESET}")
                            else:
                                self.failure_count += 1
                                logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Server trả về lỗi: {data.get('message')}{Colors.RESET}")
                        else:
                            self.failure_count += 1
                            logger.warning(f"{Colors.YELLOW}[HEARTBEAT] HTTP {response.status_code}: {response.text[:100]}...{Colors.RESET}")
                    
                    except requests.exceptions.RequestException as e:
                        self.failure_count += 1
                        logger.warning(f"{Colors.YELLOW}[HEARTBEAT] Không thể kết nối server: {e}{Colors.RESET}")
                    
                    # Nếu thất bại quá nhiều, thử đăng ký lại
                    if self.failure_count >= HEARTBEAT_RETRY_COUNT:
                        logger.error(f"{Colors.RED}[HEARTBEAT] Mất kết nối server sau {self.failure_count} lần thử{Colors.RESET}")
                        # Có thể thêm logic đăng ký lại ở đây
                
                # Chờ interval
                for _ in range(HEARTBEAT_INTERVAL):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"{Colors.RED}[HEARTBEAT] Lỗi worker: {e}{Colors.RESET}")
                time.sleep(HEARTBEAT_INTERVAL)

class ServerCommunicator:
    """Lớp xử lý giao tiếp với server - THÊM HEARTBEAT"""
    
    def __init__(self, server_url, group_id):
        self.server_url = server_url
        self.group_id = group_id
        self.user_id = None  # client_id từ server
        self.max_retries = 3
        self.retry_delay = 5
        self.heartbeat_manager = None  # ← THÊM
        
    def set_heartbeat_manager(self, heartbeat_manager):
        """Thiết lập heartbeat manager"""
        self.heartbeat_manager = heartbeat_manager
    
    def register(self):
        """Đăng ký với server và nhận client_id - CẬP NHẬT"""
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{self.server_url}/api/register_local",
                    json={"client_info": "local_daemon"},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'registered':
                        self.user_id = data.get('client_id')
                        logger.info(f"{Colors.GREEN}[OK] Đã đăng ký với client_id: {self.user_id}{Colors.RESET}")
                        
                        # KHỞI ĐỘNG HEARTBEAT NẾU ĐƯỢC YÊU CẦU
                        if data.get('heartbeat_required') and self.heartbeat_manager:
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
    
    # ... (phần còn lại của ServerCommunicator giữ nguyên) ...

class AutoTicketDaemon:
    """Lớp chính điều phối - CẬP NHẬT THÊM HEARTBEAT"""
    
    def __init__(self, server_url, group_id):
        self.time_manager = TimeManager(SHIFT_CHECK_TIMES)
        self.session_manager = SessionManager()
        self.server = ServerCommunicator(server_url, group_id)
        
        # THÊM HEARTBEAT MANAGER
        self.heartbeat_manager = HeartbeatManager(self.server, self.session_manager)
        self.server.set_heartbeat_manager(self.heartbeat_manager)
        
        self.automation = WebAutomation(self.time_manager, self.session_manager, self.server)
        self.processor = CommandProcessor(self.server, self.automation, self.time_manager, self.session_manager)
        self.health_monitor = HealthMonitor()
        self.running = False
        
        # Thống kê
        self.check_count = 0
        self.command_count = 0
    
    def start_daemon(self):
        """Bắt đầu chạy nền - CẬP NHẬT"""
        print(f"""{Colors.CYAN}{Colors.BOLD}
==========================================
        KHỞI ĐỘNG LOCAL DAEMON
     (ĐÃ ĐỒNG BỘ VỚI SERVER)
=========================================={Colors.RESET}""")
        print(f"{Colors.LIGHT_BLUE}[SERVER] {SERVER_URL}{Colors.RESET}")
        print(f"{Colors.LIGHT_BLUE}[GROUP] Line Group: {GROUP_ID}{Colors.RESET}")
        print(f"{Colors.GREEN}[SYSTEM] Hệ thống quản lý phiên làm việc đã kích hoạt{Colors.RESET}")
        print(f"{Colors.MAGENTA}[HEARTBEAT] Gửi nhịp tim mỗi 30 giây để duy trì kết nối{Colors.RESET}")
        
        # ... (phần còn lại giữ nguyên) ...
    
    def stop(self):
        """Dừng toàn bộ hệ thống - THÊM DỪNG HEARTBEAT"""
        self.running = False
        self.heartbeat_manager.stop()  # ← THÊM: Dừng heartbeat
        self.automation.stop()
        # Kết thúc mọi phiên làm việc đang active
        self.session_manager.force_end_session()
        logger.info(f"{Colors.CYAN}[STOP] Đã dừng hệ thống{Colors.RESET}")
        
        # Hiển thị thống kê
        stats = self.health_monitor.get_stats()
        print(f"\n{Colors.CYAN}📊 THỐNG KÊ HOẠT ĐỘNG:{Colors.RESET}")
        print(f"{Colors.YELLOW}• Thời gian chạy: {stats['uptime']}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Tổng lệnh xử lý: {self.command_count}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Tỷ lệ thành công: {stats['success_rate']}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Lần kiểm tra cuối: {stats['last_check']}{Colors.RESET}")
        print(f"{Colors.YELLOW}• Heartbeat: Đã dừng{Colors.RESET}")
