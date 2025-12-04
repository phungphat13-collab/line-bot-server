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
LINE_CHANNEL_TOKEN = "Z45KyBW+4pEZM8OJDh0qM8+8AD2/hQxZdnMSGHRfbuPBMBWF5G3FAXKyS4GqXDzXA1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5gjAofn+Z3Hq/guCI0Q6V5uw6n5l1k/gWURHvcK1+loMQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "MCerQE7Kk9"  # GROUP ID TỪ LINK: https://line.me/ti/g/MCerQE7Kk9

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
            logger.error(f"❌ Line API error: {response.status_code} - {response.text}")
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
        "group_link": f"https://line.me/ti/g/{LINE_GROUP_ID}",
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

# ========== DEBUG ENDPOINTS ==========
@app.route('/test_webhook', methods=['GET'])
def test_webhook():
    """Test webhook endpoint"""
    return jsonify({
        "status": "webhook_test",
        "url": f"{SERVER_URL}/webhook",
        "method": "POST",
        "timestamp": time.time(),
        "message": "Webhook endpoint is accessible"
    })

@app.route('/send_test_message', methods=['GET'])
def send_test_message():
    """Gửi test message đến group"""
    try:
        message = f"🔧 Test từ server!\n🕒 {datetime.now().strftime('%H:%M:%S')}\n✅ Group: {LINE_GROUP_ID}"
        
        success = send_line_message(LINE_GROUP_ID, message)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Test message sent" if success else "Failed to send",
            "group_id": LINE_GROUP_ID,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time()
        })

@app.route('/check_bot_location', methods=['GET'])
def check_bot_location():
    """Kiểm tra bot đang ở group nào"""
    try:
        # Lấy danh sách group bot đang tham gia
        url = "https://api.line.me/v2/bot/group/list"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            groups = response.json().get('groups', [])
            
            result = {
                "bot_is_in_groups": len(groups),
                "target_group_id": LINE_GROUP_ID,
                "target_group_link": f"https://line.me/ti/g/{LINE_GROUP_ID}",
                "groups": [],
                "in_target_group": False
            }
            
            for group in groups:
                group_id = group.get('groupId')
                is_target = (group_id == LINE_GROUP_ID)
                
                if is_target:
                    result["in_target_group"] = True
                
                result["groups"].append({
                    "group_id": group_id,
                    "group_name": group.get('groupName', 'Unknown'),
                    "is_target_group": is_target,
                    "group_type": "C-prefix (old)" if group_id.startswith('C') else "link_id"
                })
            
            return jsonify(result)
        else:
            return jsonify({
                "error": f"Failed to get groups: {response.status_code}",
                "message": response.text
            })
            
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/join_target_group', methods=['GET'])
def join_target_group():
    """Hướng dẫn thêm bot vào group đích"""
    instructions = {
        "steps": [
            "1. Mở group Line mà bạn muốn bot hoạt động",
            f"2. Link group: https://line.me/ti/g/{LINE_GROUP_ID}",
            "3. Nhấn vào tên group → 'Thành viên'",
            "4. Chọn 'Thêm thành viên'",
            "5. Quét QR code từ LINE Developers Console",
            "6. Hoặc tìm tên bot và thêm vào",
            "",
            "📌 Lưu ý:",
            "- Đảm bảo bot chưa trong group nào khác",
            "- Nếu bot đã trong group khác, dùng lệnh '.cleanup' trong group này"
        ],
        "target_group": LINE_GROUP_ID,
        "qr_code_url": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://line.me/R/ti/g/{LINE_GROUP_ID}"
    }
    
    return jsonify(instructions)

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

# ... (giữ nguyên các endpoint khác: ping_group, get_group_task, update_group_status)

# ========== LINE WEBHOOK - FIXED ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    try:
        logger.info("="*50)
        logger.info("📨 WEBHOOK RECEIVED")
        
        if request.method == 'GET':
            logger.info("✅ GET request - LINE verification")
            return 'OK', 200
        
        try:
            data = request.json
            events = data.get('events', [])
            
            if not events:
                return 'OK', 200
            
            for event in events:
                event_type = event.get('type')
                source = event.get('source', {})
                source_type = source.get('type')
                group_id = source.get('groupId')
                user_id = source.get('userId')
                
                logger.info(f"🎯 Event Type: {event_type}")
                logger.info(f"🎯 Source Type: {source_type}")
                logger.info(f"🎯 Group ID: {group_id}")
                logger.info(f"🎯 User ID: {user_id}")
                
                # CHẤP NHẬN CẢ 2 LOẠI GROUP ID
                # 1. Group ID từ link: MCerQE7Kk9
                # 2. Group ID cũ: C958b8ae79a61fdb417157a29b7030844
                
                # Nếu là group ID cũ, chuyển thành group ID từ link
                if group_id == "C958b8ae79a61fdb417157a29b7030844":
                    logger.info(f"🔄 Converting old group ID to target group ID")
                    group_id = LINE_GROUP_ID
                
                if group_id == LINE_GROUP_ID:
                    logger.info(f"✅ Processing message from target group!")
                    
                    if event_type == 'message':
                        message = event.get('message', {})
                        if message.get('type') == 'text':
                            message_text = message.get('text', '').strip()
                            logger.info(f"💬 Message Text: {message_text}")
                            
                            # Xử lý lệnh
                            handle_group_command(group_id, message_text)
            
        except Exception as e:
            logger.error(f"❌ Error processing webhook: {e}")
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200

def handle_group_command(group_id, message_text):
    try:
        logger.info(f"🎯 Command: '{message_text}'")
        
        if message_text == '.help' or message_text == 'help':
            send_help_message(group_id)
        
        elif message_text == '.test':
            send_line_message(
                group_id,
                f"✅ Bot đang hoạt động!\n"
                f"👥 Group ID: {group_id}\n"
                f"🔗 Link: https://line.me/ti/g/{group_id}\n"
                f"🕒 Time: {datetime.now().strftime('%H:%M:%S')}\n"
                f"🌐 Server: {SERVER_URL}"
            )
            logger.info(f"✅ Sent test response to group")
        
        elif message_text == '.id':
            send_line_message(
                group_id,
                f"👥 **Thông tin Group:**\n"
                f"• ID: `{group_id}`\n"
                f"• Link: https://line.me/ti/g/{group_id}\n\n"
                f"📌 Sử dụng ID này để cấu hình client"
            )
        
        elif message_text == '.where':
            # Kiểm tra bot đang ở đâu
            send_line_message(
                group_id,
                f"📍 **Bot Location Check:**\n"
                f"• Target Group: `{LINE_GROUP_ID}`\n"
                f"• Current Group: `{group_id}`\n"
                f"• Match: {'✅' if group_id == LINE_GROUP_ID else '❌'}\n\n"
                f"📊 Kiểm tra chi tiết: {SERVER_URL}/check_bot_location"
            )
        
        elif message_text == '.join':
            # Hướng dẫn thêm bot vào group
            send_line_message(
                group_id,
                f"📋 **Hướng dẫn thêm bot vào group:**\n\n"
                f"1. Đảm bảo bạn là admin group\n"
                f"2. Nhấn vào tên group → Thành viên\n"
                f"3. Chọn 'Thêm thành viên'\n"
                f"4. Quét QR code hoặc tìm tên bot\n\n"
                f"🔗 QR Code: {SERVER_URL}/join_target_group"
            )
        
        elif message_text.startswith('.login '):
            # Giữ nguyên logic login
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
                        f"🔄 Đã thêm vào hàng đợi. Vị trí: {position}"
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
        
        elif message_text == '.status':
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
            else:
                status_text += "🔗 **Local client**: ❌ Chưa kết nối\n"
            
            status_text += f"\n👥 **Queue**:\n"
            status_text += f"   • Đang chạy: {queue_info.get('current_username', 'None')}\n"
            status_text += f"   • Người chờ: {len(queue_info.get('waiting_users', []))}\n"
            
            send_line_message(group_id, status_text)
        
        elif message_text == '.queue':
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
        logger.error(f"❌ Error handling command: {e}")
        send_line_message(group_id, f"❌ Lỗi: {str(e)}")

def send_help_message(group_id):
    help_text = f"""
🎯 **HƯỚNG DẪN**

📌 **Lệnh:**
• `.login username:password` - Chạy automation
• `.status` - Xem trạng thái hệ thống
• `.queue` - Xem hàng đợi
• `.test` - Test bot hoạt động
• `.id` - Xem Group ID hiện tại
• `.where` - Kiểm tra bot đang ở đâu
• `.join` - Hướng dẫn thêm bot vào group
• `.help` - Xem hướng dẫn này

⚡ **Cách dùng:**
1. Đảm bảo local client đang chạy
2. Gửi `.login username:password` trong group
3. Bot tự động xử lý ticket

🔧 **Group hiện tại:**
• ID: `{LINE_GROUP_ID}`
• Link: https://line.me/ti/g/{LINE_GROUP_ID}
"""
    
    send_line_message(group_id, help_text)

# ==================== MAIN ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info(f"🚀 LINE BOT SERVER")
    logger.info(f"👥 Group ID: {LINE_GROUP_ID}")
    logger.info(f"🔗 Link: https://line.me/ti/g/{LINE_GROUP_ID}")
    logger.info(f"🌐 Server: {SERVER_URL}")
    logger.info("="*60)
    
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
