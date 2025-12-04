from flask import Flask, request, jsonify
from threading import Thread, Lock
import requests
import time
import logging
from queue import Queue
import json
import os
from datetime import datetime
from functools import wraps

app = Flask(__name__)

# ==================== CẤU HÌNH ====================
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "MCerQE7Kk9"

# ==================== BIẾN TOÀN CỤC ====================
# Lưu thông tin kết nối local client
local_clients = {}  # {user_id: {last_ping: timestamp, status: 'active', ip: '', tasks: [], messages: []}}

# Quản lý queue cho group
group_queues = {
    LINE_GROUP_ID: {
        "waiting_users": [],
        "current_user": None,
        "current_username": None,
        "current_task": None
    }
}

# Lưu user mới nhất để auto detect
recent_users = []  # [{user_id, timestamp, source}]
last_user_id = None

# Khóa đồng bộ
clients_lock = Lock()
queue_lock = Lock()
users_lock = Lock()

# Queue tin nhắn
message_queue = Queue()

# ==================== LOGGING ====================
def setup_logging():
    """Cấu hình logging"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('server.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==================== TIỆN ÍCH ====================
def log_request_info():
    """Log thông tin request"""
    logger.info(f"Request: {request.method} {request.path}")
    if request.json:
        logger.info(f"Request data: {json.dumps(request.json, ensure_ascii=False)}")

def send_line_message(to_id, message, message_type="user"):
    """Gửi tin nhắn LINE"""
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
            logger.info(f"📤 Sent to {to_id[:15]}...: {message[:50]}...")
            return True
        else:
            logger.error(f"❌ Line API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        return False

def add_recent_user(user_id, source="webhook"):
    """Thêm user vào danh sách recent"""
    with users_lock:
        global last_user_id
        last_user_id = user_id
        
        # Thêm vào danh sách
        recent_users.append({
            "user_id": user_id,
            "timestamp": time.time(),
            "source": source
        })
        
        # Giới hạn chỉ lưu 20 user gần nhất
        if len(recent_users) > 20:
            recent_users.pop(0)
        
        logger.info(f"➕ Added recent user: {user_id} from {source}")

# ==================== MONITOR THREAD ====================
def connection_monitor():
    """Giám sát kết nối local client"""
    logger.info("🔍 Starting connection monitor...")
    
    while True:
        try:
            current_time = time.time()
            disconnected_users = []
            
            with clients_lock:
                # Kiểm tra timeout (60 giây)
                for user_id, client_info in list(local_clients.items()):
                    last_ping = client_info.get('last_ping', 0)
                    
                    if current_time - last_ping > 60:  # 60 giây timeout
                        disconnected_users.append(user_id)
                        logger.warning(f"⏰ Connection timeout: {user_id}")
                    
                    # Nếu quá 30 giây chưa ping, đánh dấu idle
                    elif current_time - last_ping > 30:
                        client_info['status'] = 'idle'
            
            # Xóa client timeout
            for user_id in disconnected_users:
                with clients_lock:
                    if user_id in local_clients:
                        del local_clients[user_id]
                        logger.info(f"🗑️ Removed timeout client: {user_id}")
                
                # Thông báo nếu đang chạy automation
                send_line_message(
                    user_id,
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
        "service": "LINE Bot Automation Server",
        "clients_connected": client_count,
        "group_queue_waiting": waiting_count,
        "server_time": datetime.now().isoformat(),
        "endpoints": {
            "/health": "Health check",
            "/status": "System status",
            "/recent_users": "Get recent users",
            "/register_local": "Register local client",
            "/ping": "Heartbeat",
            "/get_task": "Get tasks for client",
            "/update_status": "Update automation status",
            "/webhook": "LINE webhook"
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "clients_connected": len(local_clients)
    })

@app.route('/status', methods=['GET'])
def system_status():
    """Xem trạng thái hệ thống"""
    with clients_lock:
        clients_info = []
        for user_id, info in local_clients.items():
            clients_info.append({
                "user_id": user_id[:10] + "...",
                "status": info.get('status', 'unknown'),
                "last_ping": int(time.time() - info.get('last_ping', 0)),
                "automation": info.get('automation_status', 'idle')
            })
    
    with queue_lock:
        queue_info = group_queues[LINE_GROUP_ID]
        current_user = queue_info["current_user"]
        if current_user:
            current_user = current_user[:10] + "..."
    
    return jsonify({
        "server": "online",
        "total_clients": len(local_clients),
        "active_clients": [c for c in clients_info if c['status'] == 'active'],
        "group_queue": {
            "current_user": current_user,
            "waiting_count": len(queue_info["waiting_users"])
        },
        "recent_users_count": len(recent_users)
    })

# ========== USER MANAGEMENT ==========
@app.route('/recent_users', methods=['GET'])
def get_recent_users():
    """Lấy danh sách user gần nhất"""
    with users_lock:
        users = recent_users[-10:]  # Lấy 10 user gần nhất
    
    return jsonify({
        "recent_users": users,
        "count": len(users)
    })

@app.route('/get_recent_user', methods=['GET'])
def get_recent_user():
    """Lấy user mới nhất (cho auto detect)"""
    with users_lock:
        if recent_users:
            latest = recent_users[-1]
            return jsonify({
                "user_id": latest["user_id"],
                "timestamp": latest["timestamp"],
                "source": latest["source"]
            })
    
    return jsonify({"user_id": None})

@app.route('/get_my_id', methods=['POST'])
def get_my_id():
    """API để client tự lấy ID của mình"""
    data = request.json
    test_code = data.get('test_code', '')
    
    # Đơn giản là trả về user_id nếu có trong recent
    with users_lock:
        if recent_users:
            latest = recent_users[-1]
            return jsonify({
                "user_id": latest["user_id"],
                "message": "User ID của bạn"
            })
    
    return jsonify({
        "user_id": None,
        "message": "Không tìm thấy User ID. Vui lòng gửi tin nhắn cho bot trước."
    })

# ========== LOCAL CLIENT REGISTRATION ==========
@app.route('/register_local', methods=['POST'])
def register_local():
    """Đăng ký local client"""
    log_request_info()
    
    try:
        data = request.json
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        
        with clients_lock:
            local_clients[user_id] = {
                'last_ping': time.time(),
                'status': 'active',
                'ip': request.remote_addr,
                'tasks': [],
                'messages': [],
                'automation_status': 'idle',
                'registered_at': time.time()
            }
        
        logger.info(f"✅ Client registered: {user_id} from {request.remote_addr}")
        
        # Thêm vào recent users
        add_recent_user(user_id, "registration")
        
        return jsonify({
            "status": "success",
            "message": "Client registered successfully",
            "server_time": time.time(),
            "user_id": user_id
        })
        
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/ping', methods=['POST'])
def ping():
    """Heartbeat từ local client"""
    try:
        data = request.json
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        
        with clients_lock:
            if user_id in local_clients:
                local_clients[user_id]['last_ping'] = time.time()
                local_clients[user_id]['status'] = 'active'
                
                # Cập nhật IP nếu thay đổi
                if request.remote_addr != local_clients[user_id].get('ip'):
                    local_clients[user_id]['ip'] = request.remote_addr
                
                return jsonify({
                    "status": "success",
                    "message": "pong",
                    "server_time": time.time()
                })
            else:
                # Tự động đăng ký nếu chưa có
                local_clients[user_id] = {
                    'last_ping': time.time(),
                    'status': 'active',
                    'ip': request.remote_addr,
                    'tasks': [],
                    'messages': [],
                    'automation_status': 'idle',
                    'registered_at': time.time()
                }
                
                logger.info(f"🔄 Auto-registered from ping: {user_id}")
                return jsonify({
                    "status": "success",
                    "message": "auto_registered",
                    "server_time": time.time()
                })
        
    except Exception as e:
        logger.error(f"❌ Ping error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== TASK MANAGEMENT ==========
@app.route('/get_task', methods=['POST'])
def get_task():
    """Local client lấy task"""
    log_request_info()
    
    try:
        data = request.json
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        
        with clients_lock:
            if user_id not in local_clients:
                return jsonify({"error": "Client not registered"}), 404
            
            # Cập nhật ping
            local_clients[user_id]['last_ping'] = time.time()
            local_clients[user_id]['status'] = 'active'
            
            # Lấy task đầu tiên trong queue
            tasks = local_clients[user_id].get('tasks', [])
            task = tasks[0] if tasks else None
            
            # Xóa task đã lấy
            if task:
                local_clients[user_id]['tasks'] = tasks[1:]
            
            # Lấy messages
            messages = local_clients[user_id].get('messages', [])
            local_clients[user_id]['messages'] = []  # Xóa sau khi lấy
        
        return jsonify({
            "status": "success",
            "task": task,
            "messages": messages,
            "server_time": time.time()
        })
        
    except Exception as e:
        logger.error(f"❌ Get task error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/update_status', methods=['POST'])
def update_automation_status():
    """Cập nhật trạng thái automation"""
    log_request_info()
    
    try:
        data = request.json
        user_id = data.get('user_id')
        status = data.get('status')
        message = data.get('message', '')
        group_id = data.get('group_id')
        
        if not user_id or not status:
            return jsonify({"error": "Missing parameters"}), 400
        
        with clients_lock:
            if user_id in local_clients:
                local_clients[user_id]['last_ping'] = time.time()
                local_clients[user_id]['automation_status'] = status
        
        # Xử lý khi automation kết thúc
        if status in ['stopped', 'error', 'standby', 'idle']:
            if group_id and group_id in group_queues:
                with queue_lock:
                    queue_info = group_queues[group_id]
                    
                    # Giải phóng slot nếu user này đang chạy
                    if queue_info["current_user"] == user_id:
                        queue_info["current_user"] = None
                        queue_info["current_username"] = None
                        queue_info["current_task"] = None
                        
                        logger.info(f"🔓 Freed slot in group {group_id} for user {user_id}")
                        
                        # Thông báo cho người tiếp theo
                        if queue_info["waiting_users"]:
                            next_user = queue_info["waiting_users"].pop(0)
                            queue_info["current_user"] = next_user['user_id']
                            queue_info["current_username"] = next_user['username']
                            queue_info["current_task"] = {
                                "command": "start_automation",
                                "username": next_user['username'],
                                "password": next_user['password'],
                                "group_id": group_id
                            }
                            
                            # Gửi task cho user tiếp theo
                            with clients_lock:
                                if next_user['user_id'] in local_clients:
                                    local_clients[next_user['user_id']]['tasks'].append(
                                        queue_info["current_task"]
                                    )
                            
                            # Thông báo trong group
                            send_line_message(
                                group_id,
                                f"🔄 Đến lượt {next_user['username']}! Đang khởi động automation...",
                                "group"
                            )
        
        # Gửi thông báo cho user
        if message:
            send_line_message(user_id, message)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"❌ Update status error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== LINE WEBHOOK ==========
@app.route('/webhook', methods=['POST'])
def webhook():

"""
CẬP NHẬT QUAN TRỌNG CHO server.py
Thêm đoạn code sau vào hàm webhook() để debug chi tiết
"""

# ==================== WEBHOOK FIX ====================
@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Webhook từ LINE - FIXED VERSION"""
    try:
        # Log chi tiết request
        logger.info("="*60)
        logger.info("📨 WEBHOOK RECEIVED")
        logger.info(f"📝 Method: {request.method}")
        logger.info(f"📦 Headers: {dict(request.headers)}")
        
        # Nếu là GET request (LINE verify)
        if request.method == 'GET':
            logger.info("✅ GET request - LINE verification")
            return 'OK', 200
        
        # Lấy signature từ LINE
        signature = request.headers.get('X-Line-Signature', '')
        logger.info(f"🔐 Signature: {signature[:20]}...")
        
        # Lấy raw body
        body = request.get_data(as_text=True)
        logger.info(f"📄 Body length: {len(body)} chars")
        logger.info(f"📄 Body preview: {body[:200]}...")
        
        # Parse JSON
        try:
            data = request.json
            events = data.get('events', [])
            logger.info(f"📊 Events count: {len(events)}")
            
            # Log từng event
            for i, event in enumerate(events):
                logger.info(f"  Event {i+1}:")
                logger.info(f"    Type: {event.get('type')}")
                
                source = event.get('source', {})
                user_id = source.get('userId')
                group_id = source.get('groupId')
                
                if user_id:
                    logger.info(f"    User ID: {user_id}")
                    # Lưu user vào recent
                    add_recent_user(user_id, "line_webhook")
                
                if group_id:
                    logger.info(f"    Group ID: {group_id}")
                
                if event.get('type') == 'message':
                    message = event.get('message', {})
                    logger.info(f"    Message type: {message.get('type')}")
                    logger.info(f"    Message text: {message.get('text', '')}")
                    
                    # Xử lý lệnh
                    if message.get('type') == 'text':
                        message_text = message.get('text', '').strip()
                        reply_token = event.get('replyToken')
                        
                        logger.info(f"    📝 Processing: '{message_text}'")
                        
                        # Xử lý lệnh
                        handle_line_command(user_id, group_id, message_text, reply_token)
                        
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error: {e}")
            logger.error(f"   Raw body: {body}")
            return 'Bad Request', 400
        
        logger.info("✅ Webhook processed successfully")
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {type(e).__name__}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 'OK', 200  # Vẫn trả OK để LINE không retry

def add_recent_user(user_id, source="webhook"):
    """Thêm user vào danh sách recent - đảm bảo lưu"""
    try:
        with users_lock:
            global recent_users
            
            # Kiểm tra xem user đã có chưa
            existing = False
            for user in recent_users:
                if user.get("user_id") == user_id:
                    user["timestamp"] = time.time()
                    user["source"] = source
                    existing = True
                    break
            
            if not existing:
                recent_users.append({
                    "user_id": user_id,
                    "timestamp": time.time(),
                    "source": source
                })
                
                # Giới hạn 50 user gần nhất
                if len(recent_users) > 50:
                    recent_users = recent_users[-50:]
            
            logger.info(f"➕ Added/Updated user: {user_id} from {source}")
            
    except Exception as e:
        logger.error(f"❌ Error adding recent user: {e}")

def handle_line_command(user_id, group_id, message_text, reply_token):
    """Xử lý lệnh từ LINE - LOG CHI TIẾT"""
    try:
        logger.info(f"🎯 Handling command: '{message_text}' from {user_id}")
        
        # Lệnh .help
        if message_text == '.help' or message_text == 'help':
            logger.info("   Processing: .help command")
            send_help_message(user_id, group_id)
        
        # Lệnh .login
        elif message_text.startswith('.login '):
            logger.info(f"   Processing: .login command")
            handle_login_command(user_id, group_id, message_text)
        
        # Lệnh .status
        elif message_text == '.status':
            logger.info("   Processing: .status command")
            handle_status_command(user_id, group_id)
        
        # Lệnh .queue
        elif message_text == '.queue':
            logger.info("   Processing: .queue command")
            handle_queue_command(user_id, group_id)
        
        # Lệnh .myid
        elif message_text == '.myid':
            logger.info("   Processing: .myid command")
            send_line_message(
                user_id if not group_id else group_id,
                f"🆔 User ID của bạn: {user_id}",
                "group" if group_id else "user"
            )
        
        # Lệnh .test
        elif message_text == '.test':
            logger.info("   Processing: .test command")
            send_line_message(
                user_id if not group_id else group_id,
                f"✅ Bot đang hoạt động!\n"
                f"📱 User ID: {user_id[:15]}...\n"
                f"🕒 Server time: {datetime.now().strftime('%H:%M:%S')}\n"
                f"🌐 Webhook: OK",
                "group" if group_id else "user"
            )
            
            # Log thêm
            logger.info(f"   Sent test response to {user_id}")
        
        # Lệnh .debug
        elif message_text == '.debug':
            logger.info("   Processing: .debug command")
            debug_info = f"""
🔧 DEBUG INFO:
• User ID: {user_id}
• Group ID: {group_id or 'N/A'}
• Server: Đang hoạt động
• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Recent users: {len(recent_users)}
• Local clients: {len(local_clients)}
            """
            send_line_message(
                user_id if not group_id else group_id,
                debug_info,
                "group" if group_id else "user"
            )
        
        # Không phải lệnh, chuyển tiếp cho local client
        else:
            logger.info(f"   Forwarding to local client: '{message_text}'")
            forward_to_local_client(user_id, message_text)
            
    except Exception as e:
        logger.error(f"❌ Error handling command: {e}")
        import traceback
        logger.error(traceback.format_exc())

    
    """Webhook từ LINE"""
    try:
        # Lấy signature để verify (có thể thêm sau)
        signature = request.headers.get('X-Line-Signature', '')
        body = request.get_data(as_text=True)
        
        events = request.json.get('events', [])
        
        for event in events:
            # Lưu user vào recent users
            user_id = event['source'].get('userId')
            group_id = event['source'].get('groupId')
            
            if user_id:
                add_recent_user(user_id, "line_webhook")
            
            # Chỉ xử lý message events
            if event.get('type') != 'message':
                continue
            
            message_type = event['message'].get('type')
            
            # Chỉ xử lý text messages
            if message_type != 'text':
                continue
            
            reply_token = event.get('replyToken')
            message_text = event['message'].get('text', '').strip()
            
            logger.info(f"📥 LINE: {user_id} ({'group' if group_id else 'user'}): {message_text}")
            
            # Xử lý lệnh
            handle_line_command(user_id, group_id, message_text, reply_token)
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200  # Vẫn trả OK để LINE không gửi lại

def handle_line_command(user_id, group_id, message_text, reply_token):
    """Xử lý lệnh từ LINE"""
    
    # Lệnh .help
    if message_text == '.help' or message_text == 'help':
        send_help_message(user_id, group_id)
    
    # Lệnh .login
    elif message_text.startswith('.login '):
        handle_login_command(user_id, group_id, message_text)
    
    # Lệnh .status
    elif message_text == '.status':
        handle_status_command(user_id, group_id)
    
    # Lệnh .queue
    elif message_text == '.queue':
        handle_queue_command(user_id, group_id)
    
    # Lệnh .myid - trả về User ID của người gửi
    elif message_text == '.myid':
        send_line_message(
            user_id if not group_id else group_id,
            f"🆔 User ID của bạn: {user_id}",
            "group" if group_id else "user"
        )
    
    # Lệnh .test - để test kết nối
    elif message_text == '.test':
        send_line_message(
            user_id if not group_id else group_id,
            f"✅ Bot đang hoạt động! User ID của bạn: {user_id[:15]}...",
            "group" if group_id else "user"
        )
    
    # Lệnh .users - xem user đang kết nối (admin)
    elif message_text == '.users':
        handle_users_command(user_id, group_id)
    
    # Forward message cho local client nếu không phải lệnh
    else:
        forward_to_local_client(user_id, message_text)

def handle_login_command(user_id, group_id, message_text):
    """Xử lý lệnh login"""
    try:
        # Parse thông tin
        parts = message_text.split(' ')
        if len(parts) < 2:
            send_line_message(
                user_id if not group_id else group_id,
                "❌ Sai cú pháp. Dùng: .login username:password",
                "group" if group_id else "user"
            )
            return
        
        login_info = parts[1]
        if ':' not in login_info:
            send_line_message(
                user_id if not group_id else group_id,
                "❌ Sai định dạng. Dùng: .login username:password",
                "group" if group_id else "user"
            )
            return
        
        username, password = login_info.split(':', 1)
        
        # Kiểm tra local client có kết nối không
        with clients_lock:
            if user_id not in local_clients:
                send_line_message(
                    user_id if not group_id else group_id,
                    "❌ Local client chưa kết nối!\n"
                    "Vui lòng khởi động local client trước:\n"
                    "1. Tải file local_client.py\n"
                    "2. Chạy và nhập User ID của bạn\n"
                    "3. Chờ kết nối thành công\n"
                    "4. Gửi lại lệnh .login",
                    "group" if group_id else "user"
                )
                return
            
            client_status = local_clients[user_id].get('status')
            if client_status != 'active':
                send_line_message(
                    user_id if not group_id else group_id,
                    f"❌ Local client không hoạt động (status: {client_status})",
                    "group" if group_id else "user"
                )
                return
        
        # Xử lý theo group hoặc user
        if group_id:
            handle_group_login(user_id, group_id, username, password)
        else:
            handle_user_login(user_id, username, password)
    
    except Exception as e:
        logger.error(f"❌ Login command error: {e}")
        send_line_message(
            user_id if not group_id else group_id,
            f"❌ Lỗi xử lý lệnh: {str(e)}",
            "group" if group_id else "user"
        )

def handle_group_login(user_id, group_id, username, password):
    """Xử lý login trong group (có queue)"""
    try:
        # Đảm bảo group queue tồn tại
        with queue_lock:
            if group_id not in group_queues:
                group_queues[group_id] = {
                    "waiting_users": [],
                    "current_user": None,
                    "current_username": None,
                    "current_task": None
                }
            
            queue_info = group_queues[group_id]
            
            # Kiểm tra nếu user đang chạy
            if queue_info["current_user"] == user_id:
                send_line_message(
                    group_id,
                    f"⚠️ Bạn đang chạy automation với tài khoản {queue_info['current_username']}!",
                    "group"
                )
                return
            
            # Kiểm tra nếu có người đang chạy
            if queue_info["current_user"] is not None:
                # Thêm vào queue
                queue_info["waiting_users"].append({
                    "user_id": user_id,
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
                
                # Thêm vào local client task queue
                with clients_lock:
                    if user_id in local_clients:
                        local_clients[user_id]['tasks'].append({
                            "command": "queue_info",
                            "position": position,
                            "username": username
                        })
                
                return
            
            # Bắt đầu automation cho user này
            queue_info["current_user"] = user_id
            queue_info["current_username"] = username
            queue_info["current_task"] = {
                "command": "start_automation",
                "username": username,
                "password": password,
                "group_id": group_id
            }
        
        # Gửi task cho local client
        with clients_lock:
            if user_id in local_clients:
                local_clients[user_id]['tasks'].append(
                    group_queues[group_id]["current_task"]
                )
        
        # Thông báo
        send_line_message(
            group_id,
            f"🚀 Bắt đầu automation cho {username}...",
            "group"
        )
        
        send_line_message(
            user_id,
            f"🎯 Nhận lệnh login cho {username}. Đang khởi động automation...",
            "user"
        )
        
        logger.info(f"Started automation for {username} in group {group_id}")
    
    except Exception as e:
        logger.error(f"❌ Group login error: {e}")
        send_line_message(
            group_id,
            f"❌ Lỗi hệ thống: {str(e)}",
            "group"
        )

def handle_user_login(user_id, username, password):
    """Xử lý login cá nhân (không queue)"""
    try:
        # Tạo task
        task = {
            "command": "start_automation",
            "username": username,
            "password": password,
            "group_id": None
        }
        
        # Gửi task cho local client
        with clients_lock:
            if user_id in local_clients:
                local_clients[user_id]['tasks'].append(task)
        
        # Thông báo
        send_line_message(
            user_id,
            f"🚀 Bắt đầu automation cho {username}...",
            "user"
        )
        
        logger.info(f"Started individual automation for {username}")
        
    except Exception as e:
        logger.error(f"❌ User login error: {e}")
        send_line_message(
            user_id,
            f"❌ Lỗi hệ thống: {str(e)}",
            "user"
        )

def handle_status_command(user_id, group_id):
    """Xử lý lệnh status"""
    try:
        with clients_lock:
            client_info = local_clients.get(user_id, {})
        
        status_text = "📊 **TRẠNG THÁI HỆ THỐNG**\n\n"
        
        # Trạng thái server
        status_text += "🖥️ **Server**: Đang hoạt động ✅\n"
        
        # Trạng thái local client
        if client_info:
            last_ping = int(time.time() - client_info.get('last_ping', 0))
            status_text += f"🔗 **Local client**: Đã kết nối ✅\n"
            status_text += f"   • Trạng thái: {client_info.get('status', 'unknown')}\n"
            status_text += f"   • Ping: {last_ping} giây trước\n"
            status_text += f"   • Automation: {client_info.get('automation_status', 'idle')}\n"
        else:
            status_text += "🔗 **Local client**: Chưa kết nối ❌\n"
        
        # Trạng thái group queue nếu có
        if group_id and group_id in group_queues:
            with queue_lock:
                queue_info = group_queues[group_id]
            
            status_text += f"\n👥 **Group queue**:\n"
            status_text += f"   • Đang chạy: {queue_info['current_username'] or 'Không có'}\n"
            status_text += f"   • Người chờ: {len(queue_info['waiting_users'])}\n"
        
        send_line_message(
            user_id if not group_id else group_id,
            status_text,
            "group" if group_id else "user"
        )
    
    except Exception as e:
        logger.error(f"❌ Status command error: {e}")

def handle_queue_command(user_id, group_id):
    """Xử lý lệnh queue"""
    if not group_id:
        send_line_message(
            user_id,
            "ℹ️ Lệnh này chỉ dùng trong group",
            "user"
        )
        return
    
    try:
        with queue_lock:
            if group_id not in group_queues:
                send_line_message(
                    group_id,
                    "📋 Hàng đợi trống",
                    "group"
                )
                return
            
            queue_info = group_queues[group_id]
        
        queue_text = "📋 **HÀNG ĐỢI AUTOMATION**\n\n"
        
        if queue_info['current_username']:
            queue_text += f"👤 **Đang chạy**: {queue_info['current_username']}\n\n"
        else:
            queue_text += "👤 **Đang chạy**: Không có\n\n"
        
        if queue_info['waiting_users']:
            queue_text += "🔄 **Người chờ**:\n"
            for i, user in enumerate(queue_info['waiting_users'], 1):
                queue_text += f"{i}. {user['username']}\n"
            
            if len(queue_info['waiting_users']) > 3:
                queue_text += f"\n📊 Tổng cộng: {len(queue_info['waiting_users'])} người đang chờ"
        else:
            queue_text += "✅ **Không có người chờ**"
        
        send_line_message(
            group_id,
            queue_text,
            "group"
        )
    
    except Exception as e:
        logger.error(f"❌ Queue command error: {e}")

def handle_users_command(user_id, group_id):
    """Xử lý lệnh users (admin)"""
    try:
        with clients_lock:
            connected_users = list(local_clients.keys())
        
        users_text = "👥 **USERS ĐANG KẾT NỐI**\n\n"
        
        if connected_users:
            for i, uid in enumerate(connected_users[:10], 1):  # Hiển thị tối đa 10 user
                users_text += f"{i}. {uid[:15]}...\n"
            
            if len(connected_users) > 10:
                users_text += f"\n📊 Tổng cộng: {len(connected_users)} users"
        else:
            users_text += "❌ Không có user nào đang kết nối"
        
        send_line_message(
            user_id,
            users_text,
            "user"
        )
    
    except Exception as e:
        logger.error(f"❌ Users command error: {e}")

def send_help_message(user_id, group_id):
    """Gửi hướng dẫn sử dụng"""
    help_text = """
🎯 **HƯỚNG DẪN SỬ DỤNG AUTOMATION**

📌 **Lệnh cơ bản:**
• `.login username:password` - Chạy automation
• `.status` - Xem trạng thái hệ thống
• `.queue` - Xem hàng đợi (group only)
• `.myid` - Xem User ID của bạn
• `.test` - Test kết nối bot
• `.help` - Xem hướng dẫn này

⚙️ **Cấu hình local client:**
1. Tải file local_client.py
2. Chạy và nhập User ID khi được hỏi
3. Để client chạy nền
4. Dùng LINE điều khiển

🔄 **Workflow:**
1. Gửi `.login username:password` trong group
2. Nếu có người đang chạy, bạn sẽ vào hàng đợi
3. Khi đến lượt, bot tự động chạy
4. Bot xử lý ticket 1.*** tự động

⚠️ **Lưu ý:**
• Giữ local client luôn chạy
• Không đóng trình duyệt tự động
• Chờ 30s giữa các phiếu
"""
    
    send_line_message(
        user_id if not group_id else group_id,
        help_text,
        "group" if group_id else "user"
    )

def forward_to_local_client(user_id, message_text):
    """Chuyển tin nhắn cho local client"""
    with clients_lock:
        if user_id in local_clients:
            if 'messages' not in local_clients[user_id]:
                local_clients[user_id]['messages'] = []
            
            local_clients[user_id]['messages'].append({
                'text': message_text,
                'timestamp': time.time()
            })
            
            # Giới hạn số lượng messages
            if len(local_clients[user_id]['messages']) > 20:
                local_clients[user_id]['messages'] = local_clients[user_id]['messages'][-20:]

# ==================== MAIN ====================
if __name__ == '__main__':
    # Khởi động monitor thread
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER STARTING...")
    logger.info(f"🌐 Server URL: {SERVER_URL}")
    logger.info(f"👥 Group ID: {LINE_GROUP_ID}")
    logger.info(f"🔑 Token: {LINE_CHANNEL_TOKEN[:20]}...")
    logger.info("="*60)
    
    # Chạy server
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
