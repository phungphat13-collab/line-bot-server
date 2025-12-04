from flask import Flask, request, jsonify
from threading import Thread, Lock
import requests
import time
import logging
from queue import Queue
import json
import os

app = Flask(__name__)

# Cấu hình
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "MCerQE7Kk9"

# Biến toàn cục
local_connections = {}  # {user_id: {last_ping: timestamp, status: 'active', task: None}}
group_queues = {}  # {group_id: {"waiting_users": [], "current_user": None, "current_username": None}}
connection_lock = Lock()
message_queue = Queue()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Khởi tạo queue cho group
def init_group_queue():
    group_queues[LINE_GROUP_ID] = {
        "waiting_users": [],
        "current_user": None,
        "current_username": None
    }
    logger.info(f"Initialized queue for group {LINE_GROUP_ID}")

# Hàm gửi tin nhắn LINE trực tiếp
def send_line_message_direct(to_id, token, message, message_type="user"):
    """Gửi tin nhắn LINE trực tiếp"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        data = {
            'to': to_id,
            'messages': [{"type": "text", "text": message}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"📤 Message sent to {to_id}: {message}")
            return True
        else:
            logger.error(f"Line API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Line message error: {e}")
        return False

# Hàm kiểm tra và duy trì kết nối
def connection_monitor():
    """Thread giám sát và duy trì kết nối với local clients"""
    while True:
        try:
            current_time = time.time()
            disconnected_users = []
            
            with connection_lock:
                for user_id, connection_info in list(local_connections.items()):
                    # Kiểm tra timeout (30 giây)
                    if current_time - connection_info.get('last_ping', 0) > 30:
                        disconnected_users.append(user_id)
                        logger.warning(f"Connection timeout for user {user_id}")
                    
                    # Gửi ping nếu cần
                    elif current_time - connection_info.get('last_ping', 0) > 10:
                        # Có thể thêm logic gửi ping nếu cần
                        pass
            
            # Xóa các kết nối timeout
            for user_id in disconnected_users:
                with connection_lock:
                    if user_id in local_connections:
                        del local_connections[user_id]
                
                # Thông báo nếu đang chạy automation
                if user_id in local_connections and local_connections[user_id].get('status') == 'running':
                    send_line_message_direct(
                        user_id, 
                        LINE_CHANNEL_TOKEN, 
                        "⚠️ Mất kết nối với máy local! Vui lòng khởi động lại local client."
                    )
            
            time.sleep(5)
            
        except Exception as e:
            logger.error(f"Connection monitor error: {e}")
            time.sleep(10)

# Endpoint cho local client đăng ký
@app.route('/register_local', methods=['POST'])
def register_local():
    """Local client đăng ký kết nối"""
    try:
        data = request.json
        user_id = data.get('user_id')
        local_ip = request.remote_addr
        
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        
        with connection_lock:
            local_connections[user_id] = {
                'last_ping': time.time(),
                'status': 'active',
                'local_ip': local_ip,
                'task': None,
                'automation_status': 'standby'
            }
        
        logger.info(f"✅ Local client registered: {user_id} from {local_ip}")
        return jsonify({
            "status": "success",
            "message": "Local client registered",
            "server_time": time.time()
        })
        
    except Exception as e:
        logger.error(f"Register error: {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint cho local client gửi ping
@app.route('/ping', methods=['POST'])
def ping():
    """Local client gửi ping để duy trì kết nối"""
    try:
        data = request.json
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        
        with connection_lock:
            if user_id in local_connections:
                local_connections[user_id]['last_ping'] = time.time()
                local_connections[user_id]['status'] = 'active'
                return jsonify({
                    "status": "success",
                    "message": "pong",
                    "server_time": time.time()
                })
            else:
                return jsonify({"error": "User not registered"}), 404
        
    except Exception as e:
        logger.error(f"Ping error: {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint nhận message từ LINE
@app.route('/webhook', methods=['POST'])
def webhook():
    """Nhận webhook từ LINE và chuyển tiếp cho local client"""
    try:
        signature = request.headers.get('X-Line-Signature', '')
        body = request.get_data(as_text=True)
        
        # Xác thực signature (có thể thêm sau)
        
        events = request.json.get('events', [])
        
        for event in events:
            # Chỉ xử lý message events
            if event.get('type') != 'message':
                continue
            
            message_type = event['message'].get('type')
            
            # Chỉ xử lý text messages
            if message_type != 'text':
                continue
            
            user_id = event['source'].get('userId')
            group_id = event['source'].get('groupId')
            reply_token = event.get('replyToken')
            message_text = event['message'].get('text', '').strip()
            
            logger.info(f"📥 Received from {user_id} ({'group' if group_id else 'user'}): {message_text}")
            
            # Xử lý lệnh .login
            if message_text.startswith('.login '):
                handle_login_command(user_id, group_id, message_text)
            
            # Xử lý lệnh .status
            elif message_text == '.status':
                handle_status_command(user_id, group_id)
            
            # Xử lý lệnh .queue
            elif message_text == '.queue':
                handle_queue_command(user_id, group_id)
            
            # Xử lý lệnh .help
            elif message_text == '.help':
                send_help_message(user_id, group_id)
            
            # Chuyển tiếp message cho local client nếu đang chạy
            else:
                forward_to_local(user_id, message_text)
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'OK', 200

def handle_login_command(user_id, group_id, message_text):
    """Xử lý lệnh login"""
    try:
        # Parse thông tin đăng nhập
        parts = message_text.split(' ')
        if len(parts) < 2:
            send_line_message_direct(
                user_id if not group_id else group_id,
                LINE_CHANNEL_TOKEN,
                "❌ Sai cú pháp. Dùng: .login username:password",
                "group" if group_id else "user"
            )
            return
        
        login_info = parts[1]
        if ':' not in login_info:
            send_line_message_direct(
                user_id if not group_id else group_id,
                LINE_CHANNEL_TOKEN,
                "❌ Sai định dạng. Dùng: .login username:password",
                "group" if group_id else "user"
            )
            return
        
        username, password = login_info.split(':', 1)
        
        # Kiểm tra local client có kết nối không
        with connection_lock:
            if user_id not in local_connections:
                send_line_message_direct(
                    user_id if not group_id else group_id,
                    LINE_CHANNEL_TOKEN,
                    "❌ Local client chưa kết nối. Vui lòng khởi động local client trước.",
                    "group" if group_id else "user"
                )
                return
            
            connection_status = local_connections[user_id].get('status')
            if connection_status != 'active':
                send_line_message_direct(
                    user_id if not group_id else group_id,
                    LINE_CHANNEL_TOKEN,
                    "❌ Local client không hoạt động. Vui lòng kiểm tra kết nối.",
                    "group" if group_id else "user"
                )
                return
        
        # Xử lý queue cho group
        if group_id:
            handle_group_login_queue(user_id, group_id, username, password)
        else:
            # Trực tiếp khởi động automation cho user
            start_local_automation(user_id, username, password)
    
    except Exception as e:
        logger.error(f"Login command error: {e}")
        send_line_message_direct(
            user_id if not group_id else group_id,
            LINE_CHANNEL_TOKEN,
            f"❌ Lỗi xử lý lệnh: {str(e)}",
            "group" if group_id else "user"
        )

def handle_group_login_queue(user_id, group_id, username, password):
    """Xử lý queue cho group"""
    try:
        # Kiểm tra nếu group queue chưa được khởi tạo
        if group_id not in group_queues:
            group_queues[group_id] = {
                "waiting_users": [],
                "current_user": None,
                "current_username": None
            }
        
        queue_info = group_queues[group_id]
        
        # Kiểm tra nếu user đang chạy
        if queue_info["current_user"] == user_id:
            send_line_message_direct(
                group_id,
                LINE_CHANNEL_TOKEN,
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
            send_line_message_direct(
                group_id,
                LINE_CHANNEL_TOKEN,
                f"🔄 Bạn đã được thêm vào hàng đợi. Vị trí: {position}\n"
                f"👤 Người đang chạy: {queue_info['current_username']}\n"
                f"📋 Dùng '.queue' để xem hàng đợi",
                "group"
            )
            return
        
        # Bắt đầu automation cho user đầu tiên
        queue_info["current_user"] = user_id
        queue_info["current_username"] = username
        
        send_line_message_direct(
            group_id,
            LINE_CHANNEL_TOKEN,
            f"🚀 Bắt đầu automation cho {username}...",
            "group"
        )
        
        start_local_automation(user_id, username, password, group_id)
    
    except Exception as e:
        logger.error(f"Group queue error: {e}")

def start_local_automation(user_id, username, password, group_id=None):
    """Khởi động automation trên local client"""
    try:
        with connection_lock:
            if user_id not in local_connections:
                return False
            
            # Gửi lệnh start cho local client
            task_data = {
                "command": "start_automation",
                "username": username,
                "password": password,
                "group_id": group_id
            }
            
            local_connections[user_id]['task'] = task_data
            local_connections[user_id]['automation_status'] = 'starting'
            
            # Gửi thông báo
            send_line_message_direct(
                user_id,
                LINE_CHANNEL_TOKEN,
                f"🚀 Đang khởi động automation cho {username}...",
                "user"
            )
            
            return True
    
    except Exception as e:
        logger.error(f"Start automation error: {e}")
        return False

def forward_to_local(user_id, message_text):
    """Chuyển tiếp message cho local client"""
    try:
        with connection_lock:
            if user_id in local_connections:
                # Lưu message để local client lấy
                if 'messages' not in local_connections[user_id]:
                    local_connections[user_id]['messages'] = []
                
                local_connections[user_id]['messages'].append({
                    'text': message_text,
                    'timestamp': time.time()
                })
                
                # Giới hạn số lượng messages
                if len(local_connections[user_id]['messages']) > 10:
                    local_connections[user_id]['messages'] = local_connections[user_id]['messages'][-10:]
    
    except Exception as e:
        logger.error(f"Forward to local error: {e}")

def handle_status_command(user_id, group_id):
    """Xử lý lệnh status"""
    try:
        with connection_lock:
            status_text = "📊 **TRẠNG THÁI HỆ THỐNG**\n\n"
            
            # Trạng thái server
            status_text += f"🖥️ **Server**: Đang hoạt động\n"
            status_text += f"👥 **Người dùng đang kết nối**: {len(local_connections)}\n\n"
            
            # Trạng thái local client của user
            if user_id in local_connections:
                conn_info = local_connections[user_id]
                status_text += f"🔗 **Local client của bạn**:\n"
                status_text += f"   • Trạng thái: {conn_info.get('status', 'unknown')}\n"
                status_text += f"   • IP: {conn_info.get('local_ip', 'unknown')}\n"
                status_text += f"   • Automation: {conn_info.get('automation_status', 'unknown')}\n"
                last_ping = time.time() - conn_info.get('last_ping', 0)
                status_text += f"   • Ping: {int(last_ping)} giây trước\n"
            else:
                status_text += "🔗 **Local client của bạn**: Chưa kết nối\n"
            
            # Trạng thái group nếu có
            if group_id and group_id in group_queues:
                queue_info = group_queues[group_id]
                status_text += f"\n👥 **Group queue**:\n"
                status_text += f"   • Đang chạy: {queue_info['current_username'] or 'Không có'}\n"
                status_text += f"   • Người chờ: {len(queue_info['waiting_users'])}\n"
        
        send_line_message_direct(
            user_id if not group_id else group_id,
            LINE_CHANNEL_TOKEN,
            status_text,
            "group" if group_id else "user"
        )
    
    except Exception as e:
        logger.error(f"Status command error: {e}")

def handle_queue_command(user_id, group_id):
    """Xử lý lệnh queue"""
    if not group_id:
        send_line_message_direct(
            user_id,
            LINE_CHANNEL_TOKEN,
            "ℹ️ Lệnh này chỉ dùng trong group",
            "user"
        )
        return
    
    try:
        if group_id not in group_queues:
            send_line_message_direct(
                group_id,
                LINE_CHANNEL_TOKEN,
                "📋 Hàng đợi trống",
                "group"
            )
            return
        
        queue_info = group_queues[group_id]
        
        queue_text = "📋 **HÀNG ĐỢI AUTOMATION**\n\n"
        queue_text += f"👤 **Đang chạy**: {queue_info['current_username'] or 'Không có'}\n\n"
        
        if queue_info['waiting_users']:
            queue_text += "🔄 **Người chờ**:\n"
            for i, user in enumerate(queue_info['waiting_users'], 1):
                queue_text += f"{i}. {user['username']} (User: {user['user_id'][:8]}...)\n"
        else:
            queue_text += "✅ **Không có người chờ**"
        
        send_line_message_direct(
            group_id,
            LINE_CHANNEL_TOKEN,
            queue_text,
            "group"
        )
    
    except Exception as e:
        logger.error(f"Queue command error: {e}")

def send_help_message(user_id, group_id):
    """Gửi hướng dẫn sử dụng"""
    help_text = """
🎯 **HƯỚNG DẪN SỬ DỤNG AUTOMATION**

📌 **Lệnh cơ bản:**
• `.login username:password` - Chạy automation
• `.status` - Xem trạng thái hệ thống
• `.queue` - Xem hàng đợi (group only)
• `.help` - Xem hướng dẫn này

⚙️ **Cấu hình:**
1. Chạy local client trên máy tính
2. Dùng `.login` để bắt đầu
3. Hệ thống tự động xử lý ticket 1.***

⚠️ **Lưu ý:**
• Giữ local client luôn chạy
• Không đóng trình duyệt tự động
• Chờ 30s giữa các phiếu
"""
    
    send_line_message_direct(
        user_id if not group_id else group_id,
        LINE_CHANNEL_TOKEN,
        help_text,
        "group" if group_id else "user"
    )

# Endpoint cho local client lấy task
@app.route('/get_task', methods=['POST'])
def get_task():
    """Local client lấy task từ server"""
    try:
        data = request.json
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        
        with connection_lock:
            if user_id not in local_connections:
                return jsonify({"error": "User not registered"}), 404
            
            # Cập nhật ping
            local_connections[user_id]['last_ping'] = time.time()
            
            # Trả về task nếu có
            task = local_connections[user_id].get('task')
            messages = local_connections[user_id].get('messages', [])
            
            # Xóa messages đã gửi
            if messages:
                local_connections[user_id]['messages'] = []
            
            # Xóa task đã gửi
            if task:
                local_connections[user_id]['task'] = None
            
            return jsonify({
                "status": "success",
                "task": task,
                "messages": messages,
                "server_time": time.time()
            })
        
    except Exception as e:
        logger.error(f"Get task error: {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint cho local client cập nhật trạng thái
@app.route('/update_status', methods=['POST'])
def update_status():
    """Local client cập nhật trạng thái automation"""
    try:
        data = request.json
        user_id = data.get('user_id')
        status = data.get('status')
        message = data.get('message', '')
        group_id = data.get('group_id')
        
        if not user_id or not status:
            return jsonify({"error": "Missing parameters"}), 400
        
        with connection_lock:
            if user_id in local_connections:
                local_connections[user_id]['last_ping'] = time.time()
                local_connections[user_id]['automation_status'] = status
                
                # Xử lý khi automation kết thúc
                if status in ['stopped', 'error', 'standby'] and group_id:
                    if group_id in group_queues:
                        # Giải phóng slot
                        if group_queues[group_id]['current_user'] == user_id:
                            group_queues[group_id]['current_user'] = None
                            group_queues[group_id]['current_username'] = None
                            
                            # Thông báo cho người tiếp theo
                            if group_queues[group_id]['waiting_users']:
                                next_user = group_queues[group_id]['waiting_users'].pop(0)
                                group_queues[group_id]['current_user'] = next_user['user_id']
                                group_queues[group_id]['current_username'] = next_user['username']
                                
                                # Gửi thông báo cho group
                                send_line_message_direct(
                                    group_id,
                                    LINE_CHANNEL_TOKEN,
                                    f"🔄 Đến lượt {next_user['username']}! Gửi '.login {next_user['username']}:{next_user['password']}' để bắt đầu.",
                                    "group"
                                )
        
        # Gửi thông báo cho user
        if message:
            send_line_message_direct(
                user_id,
                LINE_CHANNEL_TOKEN,
                message,
                "user"
            )
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Update status error: {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint kiểm tra server
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "local_connections": len(local_connections),
        "server_time": time.time()
    })

# Khởi chạy server
if __name__ == '__main__':
    # Khởi tạo group queue
    init_group_queue()
    
    # Khởi động connection monitor thread
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    logger.info(f"🚀 Server starting on port {os.getenv('PORT', 5000)}")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
