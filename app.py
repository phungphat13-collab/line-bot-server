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
LINE_GROUP_ID = "MCerQE7Kk9"  # CHỈ DUY NHẤT GROUP NÀY ĐƯỢC XỬ LÝ

# ==================== BIẾN TOÀN CỤC ====================
local_clients = {}
group_queues = {
    LINE_GROUP_ID: {
        "waiting_users": [],
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
def send_line_message(to_id, message):
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
            logger.info(f"📤 Sent to {to_id}: {message[:50]}...")
            return True
        else:
            logger.error(f"❌ Line API error: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        return False

# ==================== MONITOR THREAD ====================
def connection_monitor():
    """Giám sát kết nối local client"""
    logger.info("🔍 Starting connection monitor...")
    
    while True:
        try:
            current_time = time.time()
            disconnected_groups = []
            
            with clients_lock:
                for group_id, client_info in list(local_clients.items()):
                    last_ping = client_info.get('last_ping', 0)
                    if current_time - last_ping > 60:
                        disconnected_groups.append(group_id)
                        logger.warning(f"⏰ Timeout GROUP: {group_id}")
            
            for group_id in disconnected_groups:
                with clients_lock:
                    if group_id in local_clients:
                        del local_clients[group_id]
                        logger.info(f"🗑️ Removed: {group_id}")
                
                send_line_message(
                    group_id,
                    "⚠️ Mất kết nối với local client! Vui lòng khởi động lại."
                )
            
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"❌ Monitor error: {e}")
            time.sleep(30)

# ==================== API ENDPOINTS ====================

# ========== HEALTH & INFO ==========
@app.route('/')
def index():
    with clients_lock:
        client_count = len(local_clients)
    
    with queue_lock:
        waiting_count = len(group_queues[LINE_GROUP_ID]["waiting_users"])
    
    return jsonify({
        "status": "online",
        "service": "LINE Bot Automation Server",
        "group_id": LINE_GROUP_ID,
        "clients_connected": client_count,
        "waiting_users": waiting_count,
        "server_time": datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "group_id": LINE_GROUP_ID
    })

# ========== LOCAL CLIENT REGISTRATION ==========
@app.route('/register_group', methods=['POST'])
def register_group():
    """Đăng ký local client"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        # CHỈ CHẤP NHẬN GROUP ID CỦA BẠN
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": "Invalid group_id"}), 400
        
        with clients_lock:
            local_clients[group_id] = {
                'last_ping': time.time(),
                'status': 'active',
                'ip': request.remote_addr,
                'tasks': [],
                'automation_status': 'idle',
                'registered_at': time.time()
            }
        
        logger.info(f"✅ Client registered: {group_id}")
        
        return jsonify({
            "status": "success",
            "message": "Client registered",
            "group_id": group_id
        })
        
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/ping_group', methods=['POST'])
def ping_group():
    """Heartbeat từ local client"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": "Invalid group_id"}), 400
        
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['last_ping'] = time.time()
                local_clients[group_id]['status'] = 'active'
                
                return jsonify({
                    "status": "success",
                    "message": "pong",
                    "group_id": group_id
                })
            else:
                local_clients[group_id] = {
                    'last_ping': time.time(),
                    'status': 'active',
                    'ip': request.remote_addr,
                    'tasks': [],
                    'automation_status': 'idle',
                    'registered_at': time.time()
                }
                
                logger.info(f"🔄 Auto-registered: {group_id}")
                return jsonify({
                    "status": "success",
                    "message": "auto_registered",
                    "group_id": group_id
                })
        
    except Exception as e:
        logger.error(f"❌ Ping error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== TASK MANAGEMENT ==========
@app.route('/get_group_task', methods=['POST'])
def get_group_task():
    """Local client lấy task"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": "Invalid group_id"}), 400
        
        with clients_lock:
            if group_id not in local_clients:
                return jsonify({"error": "Client not registered"}), 404
            
            local_clients[group_id]['last_ping'] = time.time()
            
            tasks = local_clients[group_id].get('tasks', [])
            task = tasks[0] if tasks else None
            
            if task:
                local_clients[group_id]['tasks'] = tasks[1:]
        
        return jsonify({
            "status": "success",
            "task": task,
            "group_id": group_id
        })
        
    except Exception as e:
        logger.error(f"❌ Get task error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/update_group_status', methods=['POST'])
def update_group_status():
    """Cập nhật trạng thái automation"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        status = data.get('status')
        message = data.get('message', '')
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": "Invalid group_id"}), 400
        
        if not status:
            return jsonify({"error": "Missing status"}), 400
        
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['last_ping'] = time.time()
                local_clients[group_id]['automation_status'] = status
        
        if status in ['stopped', 'error', 'completed']:
            with queue_lock:
                queue_info = group_queues[group_id]
                
                if queue_info["current_user"] is not None:
                    queue_info["current_user"] = None
                    queue_info["current_username"] = None
                    queue_info["current_task"] = None
                    
                    logger.info(f"🔓 Freed slot in group {group_id}")
                    
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
                        
                        with clients_lock:
                            if group_id in local_clients:
                                local_clients[group_id]['tasks'].append(
                                    queue_info["current_task"]
                                )
                        
                        send_line_message(
                            group_id,
                            f"🔄 Đến lượt {next_user['username']}! Đang khởi động..."
                        )
        
        if message:
            send_line_message(group_id, message)
        
        return jsonify({"status": "success", "group_id": group_id})
        
    except Exception as e:
        logger.error(f"❌ Update status error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== LINE WEBHOOK - CHỈ XỬ LÝ GROUP CỦA BẠN ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Webhook từ LINE - CHỈ XỬ LÝ GROUP MCerQE7Kk9"""
    try:
        if request.method == 'GET':
            logger.info("✅ GET request - LINE verification")
            return 'OK', 200
        
        data = request.json
        events = data.get('events', [])
        
        if not events:
            return 'OK', 200
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            group_id = source.get('groupId')
            
            # DEBUG LOG
            logger.info(f"📨 Webhook received - Type: {event_type}, Group ID: {group_id}")
            
            # CHỈ XỬ LÝ NẾU LÀ GROUP CỦA BẠN
            if event_type == 'message' and group_id == LINE_GROUP_ID:
                message = event.get('message', {})
                if message.get('type') == 'text':
                    message_text = message.get('text', '').strip()
                    logger.info(f"✅ Processing command from {LINE_GROUP_ID}: {message_text}")
                    
                    handle_group_command(group_id, message_text)
            else:
                # BỎ QUA TẤT CẢ GROUP KHÁC VÀ USER RIÊNG LẺ
                if group_id and group_id != LINE_GROUP_ID:
                    logger.info(f"⏭️ Ignoring other group/user: {group_id}")
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200

def handle_group_command(group_id, message_text):
    """Xử lý lệnh từ GROUP"""
    try:
        logger.info(f"🎯 Command: '{message_text}'")
        
        if message_text == '.help' or message_text == 'help':
            send_help_message(group_id)
        
        elif message_text.startswith('.login '):
            handle_group_login(group_id, message_text)
        
        elif message_text == '.status':
            handle_group_status(group_id)
        
        elif message_text == '.queue':
            handle_group_queue(group_id)
        
        elif message_text == '.test':
            send_line_message(
                group_id,
                f"✅ Bot đang hoạt động!\n"
                f"👥 Group ID: {group_id}\n"
                f"🕒 Time: {datetime.now().strftime('%H:%M:%S')}"
            )
        
        elif message_text == '.debug':
            with clients_lock:
                client_info = local_clients.get(group_id, {})
            
            debug_info = f"""
🔧 DEBUG INFO:
• Group ID: {group_id}
• Server: ✅ Online
• Client: {'🟢 Connected' if client_info else '🔴 Disconnected'}
• Automation: {client_info.get('automation_status', 'idle') if client_info else 'N/A'}
            """
            send_line_message(group_id, debug_info)
        
        elif message_text == '.id':
            send_line_message(
                group_id,
                f"👥 **Group ID của bạn:**\n`{group_id}`\n\n"
                f"📌 Link group:\nhttps://line.me/ti/g/{group_id}"
            )
            
    except Exception as e:
        logger.error(f"❌ Error handling command: {e}")
        send_line_message(group_id, f"❌ Lỗi: {str(e)}")

def handle_group_login(group_id, message_text):
    """Xử lý lệnh login"""
    try:
        parts = message_text.split(' ')
        if len(parts) < 2:
            send_line_message(group_id, "❌ Sai cú pháp: .login username:password")
            return
        
        login_info = parts[1]
        if ':' not in login_info:
            send_line_message(group_id, "❌ Sai định dạng: .login username:password")
            return
        
        username, password = login_info.split(':', 1)
        
        with clients_lock:
            if group_id not in local_clients:
                send_line_message(group_id, "❌ Local client chưa kết nối!")
                return
            
            client_status = local_clients[group_id].get('status')
            if client_status != 'active':
                send_line_message(group_id, f"❌ Client không hoạt động: {client_status}")
                return
        
        with queue_lock:
            if group_id not in group_queues:
                group_queues[group_id] = {
                    "waiting_users": [],
                    "current_user": None,
                    "current_username": None,
                    "current_task": None
                }
            
            queue_info = group_queues[group_id]
            
            if queue_info["current_user"] is not None:
                queue_info["waiting_users"].append({
                    "username": username,
                    "password": password
                })
                
                position = len(queue_info["waiting_users"])
                send_line_message(
                    group_id,
                    f"🔄 Đã thêm vào hàng đợi. Vị trí: {position}\n"
                    f"👤 Đang chạy: {queue_info['current_username']}"
                )
                return
            
            queue_info["current_user"] = "running"
            queue_info["current_username"] = username
            queue_info["current_task"] = {
                "command": "start_automation",
                "username": username,
                "password": password,
                "group_id": group_id
            }
        
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['tasks'].append(
                    group_queues[group_id]["current_task"]
                )
        
        send_line_message(group_id, f"🚀 Bắt đầu cho {username}...")
        logger.info(f"Started automation for {username}")
    
    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        send_line_message(group_id, f"❌ Lỗi: {str(e)}")

def handle_group_status(group_id):
    """Xử lý lệnh status"""
    try:
        with clients_lock:
            client_info = local_clients.get(group_id, {})
        
        with queue_lock:
            queue_info = group_queues.get(group_id, {})
        
        status_text = "📊 **TRẠNG THÁI HỆ THỐNG**\n\n"
        
        status_text += "🖥️ **Server**: ✅ Online\n"
        
        if client_info:
            last_ping = int(time.time() - client_info.get('last_ping', 0))
            status_text += f"🔗 **Local client**: ✅ Đã kết nối\n"
            status_text += f"   • Ping: {last_ping}s trước\n"
            status_text += f"   • Automation: {client_info.get('automation_status', 'idle')}\n"
        else:
            status_text += "🔗 **Local client**: ❌ Chưa kết nối\n"
        
        status_text += f"\n👥 **Queue**:\n"
        status_text += f"   • Đang chạy: {queue_info.get('current_username', 'None')}\n"
        status_text += f"   • Người chờ: {len(queue_info.get('waiting_users', []))}\n"
        
        send_line_message(group_id, status_text)
    
    except Exception as e:
        logger.error(f"❌ Status error: {e}")

def handle_group_queue(group_id):
    """Xử lý lệnh queue"""
    try:
        with queue_lock:
            queue_info = group_queues.get(group_id, {})
        
        queue_text = "📋 **HÀNG ĐỢI**\n\n"
        
        if queue_info.get('current_username'):
            queue_text += f"👤 **Đang chạy**: {queue_info['current_username']}\n\n"
        else:
            queue_text += "👤 **Đang chạy**: None\n\n"
        
        waiting_users = queue_info.get('waiting_users', [])
        if waiting_users:
            queue_text += "🔄 **Người chờ**:\n"
            for i, user in enumerate(waiting_users, 1):
                queue_text += f"{i}. {user['username']}\n"
        else:
            queue_text += "✅ **Không có người chờ**"
        
        send_line_message(group_id, queue_text)
    
    except Exception as e:
        logger.error(f"❌ Queue error: {e}")

def send_help_message(group_id):
    """Gửi hướng dẫn"""
    help_text = """
🎯 **HƯỚNG DẪN**

📌 **Lệnh:**
• `.login username:password` - Chạy automation
• `.status` - Xem trạng thái
• `.queue` - Xem hàng đợi
• `.test` - Test bot
• `.debug` - Debug info
• `.id` - Xem Group ID
• `.help` - Hướng dẫn

⚡ **Cách dùng:**
1. Đảm bảo local client đang chạy
2. Gửi `.login username:password` trong group
3. Bot tự động xử lý
"""
    
    send_line_message(group_id, help_text)

# ==================== MAIN ====================
if __name__ == '__main__':
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    logger.info("="*60)
    logger.info(f"🚀 LINE BOT SERVER - GROUP: {LINE_GROUP_ID}")
    logger.info(f"🌐 Server URL: {SERVER_URL}")
    logger.info("="*60)
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
