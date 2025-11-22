from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import time

# THÊM ĐOẠN NÀY VÀO app.py (sau các biến toàn cục)

@app.route('/api/get_all_commands', methods=['GET'])
def api_get_all_commands():
    """API để local client lấy tất cả lệnh (cho user nào chưa có ID)"""
    try:
        # Trả về lệnh đầu tiên trong hàng đợi
        if user_commands:
            # Lấy user_id và command đầu tiên
            user_id = next(iter(user_commands))
            command = user_commands[user_id]
            
            return jsonify({
                "has_command": True,
                "user_id": user_id,
                "command": command
            })
        else:
            return jsonify({"has_command": False})
    except Exception as e:
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API để local client đăng ký và nhận user_id"""
    try:
        data = request.get_json()
        client_ip = request.remote_addr
        
        # Tìm user_id có lệnh đang chờ
        if user_commands:
            user_id = next(iter(user_commands))
            
            # Cập nhật thông tin
            if user_id in user_sessions:
                user_sessions[user_id]['status'] = 'connected'
                user_sessions[user_id]['client_ip'] = client_ip
                user_sessions[user_id]['last_connect'] = datetime.now().isoformat()
            
            logger.info(f"🔗 Local client registered for {user_id}")
            
            return jsonify({
                "status": "registered", 
                "user_id": user_id,
                "has_command": True,
                "command": user_commands[user_id]
            })
        else:
            return jsonify({
                "status": "waiting", 
                "message": "No pending commands"
            })
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# Tắt log để tiết kiệm tài nguyên
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình LINE
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"

# Lưu trạng thái user và commands
user_sessions = {}
user_commands = {}
message_cooldown = {}

def send_line_message(chat_id, text, chat_type="user"):
    """Gửi tin nhắn LINE - TỐI ƯU CHO RENDER"""
    try:
        # Kiểm tra cooldown
        key = f"{chat_id}_{text[:20]}"
        current_time = time.time()
        if key in message_cooldown and current_time - message_cooldown[key] < 5:
            return False
            
        message_cooldown[key] = current_time
        
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        data = {
            'to': chat_id,
            'messages': [{'type': 'text', 'text': text}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Line message failed: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            user_id = source.get('userId')
            group_id = source.get('groupId')
            room_id = source.get('roomId')
            
            chat_type = "user"
            chat_id = user_id
            if group_id:
                chat_type = "group"
                chat_id = group_id
            elif room_id:
                chat_type = "room"
                chat_id = room_id
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                
                # Xử lý lệnh .login
                if message_text.startswith('.login '):
                    credentials = message_text[7:]  # Bỏ ".login "
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # Lưu thông tin user
                        user_sessions[user_id] = {
                            'username': username,
                            'password': password,
                            'group_id': group_id,
                            'room_id': room_id,
                            'status': 'waiting_command'
                        }
                        
                        # GỬI LỆNH XUỐNG LOCAL CLIENT
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id] = {
                            "id": command_id,
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        response_msg = f"""✅ ĐÃ NHẬN LỆNH TỪ LINE

👤 Username: {username}
🔐 Đã lưu thông tin đăng nhập
📨 Đang gửi lệnh đến máy local...

🖥️ Local client sẽ tự động chạy automation!"""
                        send_line_message(chat_id, response_msg, chat_type)
                        
                        # Log để debug
                        logger.info(f"📨 Sent command to {user_id}: start_automation for {username}")
                        
                    else:
                        send_line_message(chat_id, "❌ SAI CÚ PHÁP!\n👉 Dùng: .login username:password\n📝 Ví dụ: .login john_doe:123456", chat_type)
                
                # Lệnh dừng
                elif message_text.lower() in ['.stop', '.dừng', 'stop', 'dừng']:
                    if user_id in user_commands:
                        # Gửi lệnh dừng
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id] = {
                            "id": command_id,
                            "type": "stop_automation", 
                            "timestamp": datetime.now().isoformat()
                        }
                        send_line_message(chat_id, "🛑 Đã gửi lệnh DỪNG đến máy local", chat_type)
                    else:
                        send_line_message(chat_id, "❌ Không có automation nào đang chạy", chat_type)
                
                # Lệnh trạng thái
                elif message_text.lower() in ['.status', '.trạngthái', 'status']:
                    if user_id in user_sessions:
                        username = user_sessions[user_id].get('username', 'N/A')
                        status = user_sessions[user_id].get('status', 'unknown')
                        send_line_message(chat_id, f"📊 TRẠNG THÁI\n👤 User: {username}\n🔧 Status: {status}", chat_type)
                    else:
                        send_line_message(chat_id, "📊 Bạn chưa đăng nhập\n👉 Dùng: .login username:password", chat_type)
                
                # Lệnh help
                elif message_text.lower() in ['.help', 'help', 'hướng dẫn']:
                    help_text = """🤖 TICKET AUTOMATION BOT

📋 LỆNH:
• .login username:password - Chạy automation
• .stop - Dừng automation  
• .status - Kiểm tra trạng thái
• .help - Hướng dẫn này

📝 VÍ DỤ:
.login john_doe:123456

🔧 CÁCH HOẠT ĐỘNG:
1. Gửi lệnh .login từ LINE
2. Server gửi lệnh đến máy local của bạn
3. Local client tự động chạy Selenium
4. Nhận kết quả real-time qua LINE"""
                    send_line_message(chat_id, help_text, chat_type)
            
            elif event_type == 'join':
                welcome_msg = "🎉 Chào mừng! Tôi là Bot Ticket Automation\n👉 Gửi '.help' để xem hướng dẫn"
                send_line_message(chat_id, welcome_msg, chat_type)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# API để local client kết nối
@app.route('/api/connect_local', methods=['POST'])
def connect_local():
    """API để local client kết nối"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        client_ip = request.remote_addr
        
        if user_id in user_sessions:
            user_sessions[user_id]['status'] = 'connected'
            user_sessions[user_id]['client_ip'] = client_ip
            user_sessions[user_id]['last_connect'] = datetime.now().isoformat()
            
            # Thông báo cho user
            username = user_sessions[user_id].get('username')
            send_line_message(user_id, f"✅ MÁY LOCAL ĐÃ KẾT NỐI\n🖥️ IP: {client_ip}\n👤 User: {username}")
            
            return jsonify({"status": "connected", "message": "Kết nối thành công"})
        else:
            return jsonify({"status": "error", "message": "User không tồn tại"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# API để local client lấy lệnh
@app.route('/api/get_commands/<user_id>', methods=['GET'])
def api_get_commands(user_id):
    """API để local client lấy lệnh"""
    try:
        if user_id in user_commands:
            command = user_commands[user_id]
            return jsonify({
                "has_command": True,
                "command": command
            })
        else:
            return jsonify({"has_command": False})
    except Exception as e:
        return jsonify({"has_command": False, "error": str(e)})

# API đánh dấu lệnh đã hoàn thành
@app.route('/api/complete_command', methods=['POST'])
def api_complete_command():
    """API đánh dấu lệnh đã hoàn thành"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        command_id = data.get('command_id')
        
        if user_id in user_commands and user_commands[user_id]["id"] == command_id:
            del user_commands[user_id]
            logger.info(f"✅ Completed command {command_id} for {user_id}")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# API để local client gửi tin nhắn LINE
@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    """API để client gửi tin nhắn LINE"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        message = data.get('message')
        
        if user_id and message:
            send_line_message(user_id, message)
            return jsonify({"status": "sent"})
        return jsonify({"status": "error", "message": "Missing parameters"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# API cập nhật trạng thái từ local client
@app.route('/api/update_status', methods=['POST'])
def update_status():
    """API cập nhật trạng thái từ local client"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        status = data.get('status')
        message = data.get('message', '')
        
        if user_id in user_sessions:
            user_sessions[user_id]['status'] = status
            user_sessions[user_id]['last_update'] = datetime.now().isoformat()
            
            # Gửi thông báo cho user
            if message:
                send_line_message(user_id, message)
            
            return jsonify({"status": "updated"})
        else:
            return jsonify({"status": "error", "message": "User không tồn tại"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    active_users = len([u for u in user_sessions.values() if u.get('status') == 'connected'])
    pending_commands = len(user_commands)
    
    return jsonify({
        "status": "healthy",
        "server_url": SERVER_URL,
        "active_users": active_users,
        "pending_commands": pending_commands,
        "total_sessions": len(user_sessions),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "version": "2.0",
        "status": "running",
        "server_url": SERVER_URL,
        "endpoints": {
            "webhook": "/webhook",
            "health": "/health",
            "api_docs": "Check code comments"
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    print(f"🚀 Starting LINE Bot Server on port {port}")
    print(f"🌐 Server URL: {SERVER_URL}")
    app.run(host='0.0.0.0', port=port, debug=False)
