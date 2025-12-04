from flask import Flask, request, jsonify
from threading import Thread, Lock
import requests
import time
import logging
import json
import os
from datetime import datetime
import traceback

app = Flask(__name__)

# ==================== CẤU HÌNH ====================
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "MCerQE7Kk9"  # CHỈ DÙNG GROUP ID NÀY

# ==================== BIẾN TOÀN CỤC ====================
# Lưu thông tin kết nối LOCAL CLIENTS (dùng Group ID làm key)
local_clients = {}  # {group_id: {last_ping: timestamp, status: 'active', tasks: []}}

# Quản lý queue cho group
group_queues = {
    LINE_GROUP_ID: {
        "waiting_users": [],  # [{username: "", password: ""}]
        "current_user": None,
        "current_username": None,
        "current_task": None
    }
}

# Khóa đồng bộ
clients_lock = Lock()
queue_lock = Lock()

# ==================== LOGGING ====================
def setup_logging():
    """Cấu hình logging"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('server_group.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==================== TIỆN ÍCH ====================
def send_line_message(to_id, message, message_type="group"):
    """Gửi tin nhắn LINE đến Group"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        
        data = {
            'to': to_id,
            'messages': [{"type": "text", "text": message}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"📤 Sent to GROUP {to_id}: {message[:50]}...")
            return True
        else:
            logger.error(f"❌ Line API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        return False

# ==================== MONITOR THREAD ====================
def connection_monitor():
    """Giám sát kết nối local client (dùng Group ID)"""
    logger.info("🔍 Starting connection monitor for GROUP...")
    
    while True:
        try:
            current_time = time.time()
            disconnected_groups = []
            
            with clients_lock:
                # Kiểm tra timeout (60 giây)
                for group_id, client_info in list(local_clients.items()):
                    last_ping = client_info.get('last_ping', 0)
                    
                    if current_time - last_ping > 60:  # 60 giây timeout
                        disconnected_groups.append(group_id)
                        logger.warning(f"⏰ Connection timeout for GROUP: {group_id}")
            
            # Xóa client timeout
            for group_id in disconnected_groups:
                with clients_lock:
                    if group_id in local_clients:
                        del local_clients[group_id]
                        logger.info(f"🗑️ Removed timeout GROUP client: {group_id}")
                
                # Thông báo trong group
                send_line_message(
                    group_id,
                    "⚠️ Mất kết nối với local client! Vui lòng khởi động lại client."
                )
            
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"❌ Monitor error: {e}")
            time.sleep(30)

# ==================== API ENDPOINTS ====================

# ========== HEALTH & INFO ==========
@app.route('/')
def index():
    """Trang chủ"""
    with clients_lock:
        client_count = len(local_clients)
    
    with queue_lock:
        waiting_count = len(group_queues[LINE_GROUP_ID]["waiting_users"])
    
    return jsonify({
        "status": "online",
        "service": "LINE Bot Automation Server - GROUP ONLY",
        "group_id": LINE_GROUP_ID,
        "clients_connected": client_count,
        "group_queue_waiting": waiting_count,
        "server_time": datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "group_id": LINE_GROUP_ID,
        "clients_connected": len(local_clients)
    })

# ========== LOCAL CLIENT REGISTRATION ==========
@app.route('/register_group', methods=['POST'])
def register_group():
    """Đăng ký local client với Group ID"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)  # Mặc định dùng group_id đã cấu hình
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": f"Invalid group_id. Only {LINE_GROUP_ID} is allowed"}), 400
        
        with clients_lock:
            local_clients[group_id] = {
                'last_ping': time.time(),
                'status': 'active',
                'ip': request.remote_addr,
                'tasks': [],
                'automation_status': 'idle',
                'registered_at': time.time()
            }
        
        logger.info(f"✅ GROUP Client registered: {group_id} from {request.remote_addr}")
        
        return jsonify({
            "status": "success",
            "message": "GROUP client registered successfully",
            "group_id": group_id,
            "server_time": time.time()
        })
        
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/ping_group', methods=['POST'])
def ping_group():
    """Heartbeat từ local client (dùng Group ID)"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": f"Invalid group_id. Only {LINE_GROUP_ID} is allowed"}), 400
        
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['last_ping'] = time.time()
                local_clients[group_id]['status'] = 'active'
                
                return jsonify({
                    "status": "success",
                    "message": "pong",
                    "group_id": group_id,
                    "server_time": time.time()
                })
            else:
                # Tự động đăng ký nếu chưa có
                local_clients[group_id] = {
                    'last_ping': time.time(),
                    'status': 'active',
                    'ip': request.remote_addr,
                    'tasks': [],
                    'automation_status': 'idle',
                    'registered_at': time.time()
                }
                
                logger.info(f"🔄 Auto-registered GROUP from ping: {group_id}")
                return jsonify({
                    "status": "success",
                    "message": "auto_registered",
                    "group_id": group_id,
                    "server_time": time.time()
                })
        
    except Exception as e:
        logger.error(f"❌ Ping error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== TASK MANAGEMENT ==========
@app.route('/get_group_task', methods=['POST'])
def get_group_task():
    """Local client lấy task cho Group"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": f"Invalid group_id. Only {LINE_GROUP_ID} is allowed"}), 400
        
        with clients_lock:
            if group_id not in local_clients:
                return jsonify({"error": "GROUP client not registered"}), 404
            
            # Cập nhật ping
            local_clients[group_id]['last_ping'] = time.time()
            local_clients[group_id]['status'] = 'active'
            
            # Lấy task đầu tiên trong queue
            tasks = local_clients[group_id].get('tasks', [])
            task = tasks[0] if tasks else None
            
            # Xóa task đã lấy
            if task:
                local_clients[group_id]['tasks'] = tasks[1:]
        
        return jsonify({
            "status": "success",
            "task": task,
            "group_id": group_id,
            "server_time": time.time()
        })
        
    except Exception as e:
        logger.error(f"❌ Get task error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/update_group_status', methods=['POST'])
def update_group_status():
    """Cập nhật trạng thái automation cho Group"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        status = data.get('status')
        message = data.get('message', '')
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": f"Invalid group_id. Only {LINE_GROUP_ID} is allowed"}), 400
        
        if not status:
            return jsonify({"error": "Missing status"}), 400
        
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['last_ping'] = time.time()
                local_clients[group_id]['automation_status'] = status
        
        # Xử lý khi automation kết thúc
        if status in ['stopped', 'error', 'standby', 'idle']:
            with queue_lock:
                queue_info = group_queues[group_id]
                
                # Giải phóng slot nếu có người đang chạy
                if queue_info["current_user"] is not None:
                    queue_info["current_user"] = None
                    queue_info["current_username"] = None
                    queue_info["current_task"] = None
                    
                    logger.info(f"🔓 Freed slot in group {group_id}")
                    
                    # Thông báo cho người tiếp theo
                    if queue_info["waiting_users"]:
                        next_user = queue_info["waiting_users"].pop(0)
                        queue_info["current_user"] = "next_in_queue"
                        queue_info["current_username"] = next_user['username']
                        queue_info["current_task"] = {
                            "command": "start_automation",
                            "username": next_user['username'],
                            "password": next_user['password'],
                            "group_id": group_id
                        }
                        
                        # Gửi task cho local client
                        with clients_lock:
                            if group_id in local_clients:
                                local_clients[group_id]['tasks'].append(
                                    queue_info["current_task"]
                                )
                        
                        # Thông báo trong group
                        send_line_message(
                            group_id,
                            f"🔄 Đến lượt {next_user['username']}! Đang khởi động automation...",
                            "group"
                        )
        
        # Gửi thông báo cho group
        if message:
            send_line_message(group_id, message)
        
        return jsonify({"status": "success", "group_id": group_id})
        
    except Exception as e:
        logger.error(f"❌ Update status error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== LINE WEBHOOK ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Webhook từ LINE - CHỈ XỬ LÝ GROUP"""
    try:
        # Log chi tiết request
        logger.info("="*60)
        logger.info("📨 WEBHOOK RECEIVED")
        logger.info(f"📝 Method: {request.method}")
        
        # Nếu là GET request (LINE verify)
        if request.method == 'GET':
            logger.info("✅ GET request - LINE verification")
            return 'OK', 200
        
        # Parse JSON
        try:
            data = request.json
            events = data.get('events', [])
            
            if not events:
                logger.warning("⚠️ No events in webhook")
                return 'OK', 200
            
            # Xử lý từng event
            for event in events:
                event_type = event.get('type')
                source = event.get('source', {})
                group_id = source.get('groupId')
                
                # CHỈ xử lý nếu là GROUP message
                if event_type == 'message' and group_id:
                    # Kiểm tra group_id có khớp không
                    if group_id != LINE_GROUP_ID:
                        logger.warning(f"⚠️ Ignoring message from other group: {group_id}")
                        continue
                    
                    message = event.get('message', {})
                    if message.get('type') == 'text':
                        message_text = message.get('text', '').strip()
                        logger.info(f"📝 GROUP {group_id}: {message_text}")
                        
                        # Xử lý lệnh từ GROUP
                        handle_group_command(group_id, message_text)
                else:
                    logger.info(f"ℹ️ Ignoring non-group or non-message event: {event_type}")
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error: {e}")
            return 'Bad Request', 400
        
        logger.info("✅ Webhook processed successfully")
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return 'OK', 200

def handle_group_command(group_id, message_text):
    """Xử lý lệnh từ GROUP"""
    try:
        logger.info(f"🎯 GROUP Command: '{message_text}' from {group_id}")
        
        # Lệnh .help
        if message_text == '.help' or message_text == 'help':
            send_help_message(group_id)
        
        # Lệnh .login
        elif message_text.startswith('.login '):
            handle_group_login(group_id, message_text)
        
        # Lệnh .status
        elif message_text == '.status':
            handle_group_status(group_id)
        
        # Lệnh .queue
        elif message_text == '.queue':
            handle_group_queue(group_id)
        
        # Lệnh .test
        elif message_text == '.test':
            send_line_message(
                group_id,
                f"✅ Bot đang hoạt động!\n"
                f"👥 Group ID: {group_id}\n"
                f"🕒 Server time: {datetime.now().strftime('%H:%M:%S')}\n"
                f"🌐 Webhook: OK",
                "group"
            )
        
        # Lệnh .debug
        elif message_text == '.debug':
            with clients_lock:
                client_info = local_clients.get(group_id, {})
            
            debug_info = f"""
🔧 DEBUG INFO:
• Group ID: {group_id}
• Server: Đang hoạt động
• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Local client: {'🟢 Connected' if client_info else '🔴 Disconnected'}
• Automation: {client_info.get('automation_status', 'idle') if client_info else 'N/A'}
            """
            send_line_message(group_id, debug_info, "group")
            
    except Exception as e:
        logger.error(f"❌ Error handling group command: {e}")
        send_line_message(group_id, f"❌ Lỗi xử lý lệnh: {str(e)}", "group")

def handle_group_login(group_id, message_text):
    """Xử lý lệnh login trong GROUP"""
    try:
        # Parse thông tin
        parts = message_text.split(' ')
        if len(parts) < 2:
            send_line_message(
                group_id,
                "❌ Sai cú pháp. Dùng: .login username:password",
                "group"
            )
            return
        
        login_info = parts[1]
        if ':' not in login_info:
            send_line_message(
                group_id,
                "❌ Sai định dạng. Dùng: .login username:password",
                "group"
            )
            return
        
        username, password = login_info.split(':', 1)
        
        # Kiểm tra local client có kết nối không
        with clients_lock:
            if group_id not in local_clients:
                send_line_message(
                    group_id,
                    "❌ Local client chưa kết nối!\n"
                    "Vui lòng khởi động local client trước.",
                    "group"
                )
                return
            
            client_status = local_clients[group_id].get('status')
            if client_status != 'active':
                send_line_message(
                    group_id,
                    f"❌ Local client không hoạt động (status: {client_status})",
                    "group"
                )
                return
        
        # Xử lý queue cho group
        with queue_lock:
            if group_id not in group_queues:
                group_queues[group_id] = {
                    "waiting_users": [],
                    "current_user": None,
                    "current_username": None,
                    "current_task": None
                }
            
            queue_info = group_queues[group_id]
            
            # Kiểm tra nếu có người đang chạy
            if queue_info["current_user"] is not None:
                # Thêm vào queue
                queue_info["waiting_users"].append({
                    "username": username,
                    "password": password
                })
                
                position = len(queue_info["waiting_users"])
                send_line_message(
                    group_id,
                    f"🔄 Bạn đã được thêm vào hàng đợi. Vị trí: {position}\n"
                    f"👤 Người đang chạy: {queue_info['current_username']}\n"
                    f"📋 Dùng '.queue' để xem hàng đợi",
                    "group"
                )
                return
            
            # Bắt đầu automation cho user này
            queue_info["current_user"] = "running"
            queue_info["current_username"] = username
            queue_info["current_task"] = {
                "command": "start_automation",
                "username": username,
                "password": password,
                "group_id": group_id
            }
        
        # Gửi task cho local client
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['tasks'].append(
                    group_queues[group_id]["current_task"]
                )
        
        # Thông báo
        send_line_message(
            group_id,
            f"🚀 Bắt đầu automation cho {username}...",
            "group"
        )
        
        logger.info(f"Started automation for {username} in group {group_id}")
    
    except Exception as e:
        logger.error(f"❌ Group login error: {e}")
        send_line_message(
            group_id,
            f"❌ Lỗi hệ thống: {str(e)}",
            "group"
        )

def handle_group_status(group_id):
    """Xử lý lệnh status trong GROUP"""
    try:
        with clients_lock:
            client_info = local_clients.get(group_id, {})
        
        with queue_lock:
            queue_info = group_queues.get(group_id, {})
        
        status_text = "📊 **TRẠNG THÁI HỆ THỐNG**\n\n"
        
        # Trạng thái server
        status_text += "🖥️ **Server**: Đang hoạt động ✅\n"
        
        # Trạng thái local client
        if client_info:
            last_ping = int(time.time() - client_info.get('last_ping', 0))
            status_text += f"🔗 **Local client**: Đã kết nối ✅\n"
            status_text += f"   • Ping: {last_ping} giây trước\n"
            status_text += f"   • Automation: {client_info.get('automation_status', 'idle')}\n"
        else:
            status_text += "🔗 **Local client**: Chưa kết nối ❌\n"
        
        # Trạng thái group queue
        status_text += f"\n👥 **Group queue**:\n"
        status_text += f"   • Đang chạy: {queue_info.get('current_username', 'Không có')}\n"
        status_text += f"   • Người chờ: {len(queue_info.get('waiting_users', []))}\n"
        
        send_line_message(group_id, status_text, "group")
    
    except Exception as e:
        logger.error(f"❌ Status command error: {e}")

def handle_group_queue(group_id):
    """Xử lý lệnh queue trong GROUP"""
    try:
        with queue_lock:
            queue_info = group_queues.get(group_id, {})
        
        queue_text = "📋 **HÀNG ĐỢI AUTOMATION**\n\n"
        
        if queue_info.get('current_username'):
            queue_text += f"👤 **Đang chạy**: {queue_info['current_username']}\n\n"
        else:
            queue_text += "👤 **Đang chạy**: Không có\n\n"
        
        waiting_users = queue_info.get('waiting_users', [])
        if waiting_users:
            queue_text += "🔄 **Người chờ**:\n"
            for i, user in enumerate(waiting_users, 1):
                queue_text += f"{i}. {user['username']}\n"
            
            if len(waiting_users) > 3:
                queue_text += f"\n📊 Tổng cộng: {len(waiting_users)} người đang chờ"
        else:
            queue_text += "✅ **Không có người chờ**"
        
        send_line_message(group_id, queue_text, "group")
    
    except Exception as e:
        logger.error(f"❌ Queue command error: {e}")

def send_help_message(group_id):
    """Gửi hướng dẫn sử dụng cho GROUP"""
    help_text = """
🎯 **HƯỚNG DẪN SỬ DỤNG AUTOMATION**

📌 **Lệnh cơ bản:**
• `.login username:password` - Chạy automation
• `.status` - Xem trạng thái hệ thống
• `.queue` - Xem hàng đợi
• `.test` - Test kết nối bot
• `.debug` - Xem thông tin debug
• `.help` - Xem hướng dẫn này

⚙️ **Cấu hình local client:**
1. Tải file local_client_group.py
2. Chạy (tự động kết nối với group)
3. Để client chạy nền
4. Dùng lệnh trong group để điều khiển

🔄 **Workflow:**
1. Gửi `.login username:password` trong group
2. Nếu có người đang chạy, bạn sẽ vào hàng đợi
3. Khi đến lượt, bot tự động chạy
4. Bot xử lý ticket 1.*** tự động

⚠️ **Lưu ý:**
• Giữ local client luôn chạy
• Chỉ cần 1 client cho cả group
• Chờ 30s giữa các phiếu
"""
    
    send_line_message(group_id, help_text, "group")

# ==================== MAIN ====================
if __name__ == '__main__':
    # Khởi động monitor thread
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER - GROUP ONLY")
    logger.info(f"👥 Group ID: {LINE_GROUP_ID}")
    logger.info(f"🌐 Server URL: {SERVER_URL}")
    logger.info("="*60)
    
    # Chạy server
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
