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
LINE_GROUP_ID = "MCerQE7Kk9"

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
        if to_id != LINE_GROUP_ID:
            logger.warning(f"⛔ Blocked sending to other group: {to_id}")
            return False
            
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

def auto_leave_other_groups():
    """Bot tự động rời tất cả group khác ngoài group chính"""
    try:
        logger.info("🔄 Kiểm tra bot đang ở nhóm nào...")
        
        time.sleep(1)
        
        url = "https://api.line.me/v2/bot/group/list"
        headers = {
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            groups = response.json().get('groups', [])
            
            if not groups:
                logger.info("🤖 Bot không ở trong nhóm nào")
                return "🤖 Bot không ở trong nhóm nào"
            
            logger.info(f"📋 Bot đang ở {len(groups)} nhóm")
            
            left_count = 0
            left_groups = []
            for group in groups:
                group_id = group.get('groupId')
                group_name = group.get('groupName', 'Unknown')
                
                if group_id != LINE_GROUP_ID:
                    logger.info(f"⚠️ Phát hiện nhóm khác: {group_name} ({group_id})")
                    
                    leave_url = f'https://api.line.me/v2/bot/group/{group_id}/leave'
                    try:
                        leave_response = requests.post(leave_url, headers=headers, timeout=5)
                        
                        if leave_response.status_code == 200:
                            logger.info(f"🚪 Đã rời nhóm: {group_name}")
                            left_count += 1
                            left_groups.append(group_name)
                        else:
                            logger.error(f"❌ Không thể rời nhóm {group_id}: {leave_response.status_code}")
                    except Exception as e:
                        logger.error(f"❌ Lỗi khi rời nhóm: {e}")
                else:
                    logger.info(f"✅ Giữ lại nhóm chính: {group_name}")
            
            if left_count > 0:
                result = f"✅ Đã rời {left_count} nhóm khác: {', '.join(left_groups)}"
                logger.info(result)
                return result
            else:
                result = "✅ Bot chỉ ở trong nhóm chính"
                logger.info(result)
                return result
                
        else:
            error_msg = f"❌ Không thể lấy danh sách group: {response.status_code}"
            logger.error(error_msg)
            return error_msg
            
    except Exception as e:
        error_msg = f"❌ Lỗi auto leave groups: {e}"
        logger.error(error_msg)
        return error_msg

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
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
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

# ========== LINE WEBHOOK (CHỈ CÓ 1 ENDPOINT NÀY) ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
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
            
            if group_id == LINE_GROUP_ID:
                if event_type == 'message':
                    message = event.get('message', {})
                    if message.get('type') == 'text':
                        message_text = message.get('text', '').strip()
                        logger.info(f"✅ Command from {LINE_GROUP_ID}: {message_text}")
                        
                        handle_group_command(group_id, message_text)
            
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200

def handle_group_command(group_id, message_text):
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
        
        elif message_text == '.cleanup':
            send_line_message(group_id, "🔄 Đang dọn dẹp bot khỏi các nhóm khác...")
            result = auto_leave_other_groups()
            send_line_message(group_id, f"✅ {result}")
        
        elif message_text == '.groups':
            check_bot_groups(group_id)
            
    except Exception as e:
        logger.error(f"❌ Error handling command: {e}")
        send_line_message(group_id, f"❌ Lỗi: {str(e)}")

def check_bot_groups(group_id):
    try:
        url = "https://api.line.me/v2/bot/group/list"
        headers = {
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            groups = response.json().get('groups', [])
            
            message = "📋 **BOT ĐANG Ở NHÓM:**\n\n"
            
            if not groups:
                message += "🤖 Bot chưa tham gia nhóm nào"
            else:
                for group in groups:
                    gid = group.get('groupId')
                    gname = group.get('groupName', 'Không có tên')
                    
                    if gid == LINE_GROUP_ID:
                        message += f"✅ **{gname}** (NHÓM CHÍNH)\n"
                        message += f"   ID: `{gid}`\n\n"
                    else:
                        message += f"⚠️ {gname}\n"
                        message += f"   ID: `{gid}`\n\n"
            
            message += f"📌 Dùng `.cleanup` để xóa bot khỏi nhóm khác"
            
        else:
            message = f"❌ Không thể lấy danh sách: {response.status_code}"
        
        send_line_message(group_id, message)
        
    except Exception as e:
        logger.error(f"Error checking groups: {e}")
        send_line_message(group_id, f"❌ Lỗi: {str(e)}")

def handle_group_login(group_id, message_text):
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
    help_text = f"""
🎯 **HƯỚNG DẪN**

📌 **Lệnh:**
• `.login username:password` - Chạy automation
• `.status` - Xem trạng thái hệ thống
• `.queue` - Xem hàng đợi
• `.test` - Test bot hoạt động
• `.debug` - Thông tin debug
• `.id` - Xem Group ID hiện tại
• `.groups` - Xem bot đang ở nhóm nào
• `.cleanup` - Xóa bot khỏi nhóm khác
• `.help` - Xem hướng dẫn này

⚡ **Cách dùng:**
1. Đảm bảo local client đang chạy
2. Gửi `.login username:password` trong group
3. Bot tự động xử lý ticket
4. Dùng `.cleanup` nếu bot bị mời vào nhóm khác

🔧 **Group ID hiện tại:**
`{LINE_GROUP_ID}`
"""
    
    send_line_message(group_id, help_text)

# ==================== MAIN ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info(f"🚀 LINE BOT SERVER - GROUP: {LINE_GROUP_ID}")
    logger.info(f"🌐 Server URL: {SERVER_URL}")
    logger.info("="*60)
    
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
