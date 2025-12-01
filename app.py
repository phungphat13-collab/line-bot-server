# app.py (SERVER - ĐƠN GIẢN HOÀN TOÀN)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import time
import random
import string

# ==================== ⚙️ CẤU HÌNH ====================
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# TOKEN LINE BOT
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "ZpXWbVLYaj"

# ==================== 📊 BIẾN TOÀN CỤC ====================
# QUẢN LÝ PHIÊN DUY NHẤT
active_session = {
    "is_active": False,
    "username": None,
    "start_time": None,
    "session_id": None,
    "client_id": None  # ID của local daemon đang kết nối
}

# LỆNH DUY NHẤT CHO CLIENT HIỆN TẠI
current_command = None

# ==================== 🔧 HÀM TIỆN ÍCH ====================
def generate_session_id():
    """Tạo Session ID ngẫu nhiên"""
    return f"session_{int(time.time())}_{random.randint(1000, 9999)}"

def generate_client_id():
    """Tạo Client ID ngẫu nhiên"""
    return f"client_{int(time.time())}_{random.randint(1000, 9999)}"

def reset_system():
    """Reset toàn bộ hệ thống về trạng thái ban đầu"""
    global active_session, current_command
    
    active_session = {
        "is_active": False,
        "username": None,
        "start_time": None,
        "session_id": None,
        "client_id": None
    }
    
    current_command = None
    print("🔄 Đã reset hệ thống về trạng thái ban đầu")

# ==================== 📱 HÀM GỬI LINE ====================
def send_line_reply(reply_token, text):
    """Gửi tin nhắn reply LINE"""
    try:
        url = 'https://api.line.me/v2/bot/message/reply'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        data = {
            'replyToken': reply_token,
            'messages': [{'type': 'text', 'text': text}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=3)
        if response.status_code == 200:
            print(f"✅ Đã reply LINE: {text[:50]}...")
            return True
        else:
            print(f"❌ Reply LINE failed: {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Line reply failed: {e}")
        return False

def send_line_message(chat_id, text):
    """Gửi tin nhắn LINE push"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        data = {
            'to': chat_id,
            'messages': [{'type': 'text', 'text': text}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=3)
        if response.status_code == 200:
            print(f"✅ Đã gửi LINE: {text[:50]}...")
            return True
        else:
            print(f"❌ LINE push failed: {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Line push failed: {e}")
        return False

def send_to_group(text):
    """Gửi tin nhắn đến nhóm LINE"""
    if LINE_GROUP_ID:
        return send_line_message(LINE_GROUP_ID, text)
    return False

# ==================== 🌐 WEBHOOK LINE ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            reply_token = event.get('replyToken')
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                
                # LỆNH LOGIN
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # KIỂM TRA PHIÊN ĐANG CHẠY
                        if active_session["is_active"]:
                            current_user = active_session["username"]
                            send_line_reply(reply_token, 
                                f"⚠️ **{current_user} đang sử dụng tools.**\n\n"
                                f"📌 Vui lòng đợi {current_user} thoát web (.thoát web)\n"
                                f"💡 Trạng thái: CHỈ 1 PHIÊN tại thời điểm"
                            )
                            continue
                        
                        # TẠO COMMAND MỚI
                        global current_command
                        current_command = {
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "id": f"cmd_{int(time.time())}",
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        send_line_reply(reply_token, 
                            f"✅ **Đã nhận lệnh đăng nhập cho {username}**\n"
                            f"⏳ Đang chờ local daemon kết nối...\n"
                            f"💡 Lệnh sẽ được giữ trong 5 phút"
                        )
                        
                        print(f"📨 Lệnh login cho {username} đã được lưu")
                        
                    else:
                        send_line_reply(reply_token, "❌ Sai cú pháp! Dùng: .login username:password")
                
                # LỆNH THOÁT WEB
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    if active_session["is_active"]:
                        current_user = active_session["username"]
                        
                        # TẠO COMMAND STOP
                        current_command = {
                            "type": "stop_automation",
                            "username": current_user,
                            "id": f"cmd_{int(time.time())}",
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        send_line_reply(reply_token, f"🚪 **Đang yêu cầu {current_user} thoát web...**")
                        print(f"📤 Đã gửi lệnh stop cho {current_user}")
                    else:
                        send_line_reply(reply_token, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai', 'status']:
                    if active_session["is_active"]:
                        start_time = active_session["start_time"]
                        if start_time:
                            try:
                                start_dt = datetime.fromisoformat(start_time)
                                duration = datetime.now() - start_dt
                                hours = int(duration.total_seconds() // 3600)
                                minutes = int((duration.total_seconds() % 3600) // 60)
                                duration_text = f"{hours}h{minutes}p"
                            except:
                                duration_text = "Unknown"
                        else:
                            duration_text = "Unknown"
                        
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

👤 **User đang active:** {active_session['username']}
⏱️ **Thời gian chạy:** {duration_text}
🆔 **Session ID:** {active_session['session_id'][:10]}...

💡 Gõ '.thoát web' để kết thúc phiên này"""
                    else:
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

🟢 **Trạng thái:** STANDBY - Sẵn sàng nhận phiên mới
🎯 **Tình trạng:** Không có phiên làm việc nào đang chạy

💡 Gõ '.login username:password' để bắt đầu phiên làm việc mới"""
                    
                    send_line_reply(reply_token, status_text)
                
                # LỆNH HELP
                elif message_text in ['.help', 'help', 'hướng dẫn', '.huongdan']:
                    help_text = """📋 **LỆNH SỬ DỤNG:**
• `.login username:password` 
- Bắt đầu 1 phiên làm việc mới
• `.thoát web` 
- Kết thúc phiên làm việc hiện tại
• `.status`
 - Xem trạng thái hệ thống
• `.help` 
- Hướng dẫn sử dụng

🎯 **QUY TẮC HOẠT ĐỘNG:**
• **CHỈ 1 PHIÊN** làm việc tại thời điểm
• Mỗi phiên là HOÀN TOÀN MỚI
• Tự động reset sau khi kết thúc"""
                    
                    send_line_reply(reply_token, help_text)
                
                # LỆNH TEST
                elif message_text == '.test':
                    send_line_reply(reply_token, "✅ Bot đang hoạt động bình thường!")
        
        return jsonify({"status": "success", "message": "Webhook processed"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 🎯 API CHO LOCAL DAEMON ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API để local client đăng ký"""
    try:
        print(f"📥 Nhận yêu cầu register_local từ IP: {request.remote_addr}")
        
        # TẠO CLIENT ID MỚI
        client_id = generate_client_id()
        
        response_data = {
            "status": "registered", 
            "client_id": client_id,
            "has_command": False,
            "session_active": active_session["is_active"]
        }
        
        # KIỂM TRA NẾU CÓ COMMAND ĐANG CHỜ
        if current_command and current_command.get('type') == 'start_automation':
            if not active_session["is_active"]:  # Chỉ cho login nếu không có session đang chạy
                response_data.update({
                    "has_command": True,
                    "command": current_command
                })
                print(f"🔗 Gửi command login cho client: {client_id[:10]}...")
            else:
                print(f"⚠️ Có command nhưng session đang active, bỏ qua")
        
        print(f"✅ Đã đăng ký client: {client_id[:10]}...")
        return jsonify(response_data)
            
    except Exception as e:
        print(f"❌ Register error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_command/<client_id>', methods=['GET'])
def api_get_command(client_id):
    """API để local client lấy lệnh"""
    try:
        print(f"📤 Client {client_id[:10]}... đang check command")
        
        if current_command and active_session.get("client_id") == client_id:
            print(f"📤 Gửi command đến client {client_id[:10]}...: {current_command.get('type')}")
            return jsonify({
                "has_command": True,
                "command": current_command
            })
        else:
            return jsonify({"has_command": False})
    except Exception as e:
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên làm việc mới"""
    try:
        data = request.get_json()
        username = data.get('username')
        client_id = data.get('client_id')
        
        print(f"📥 Yêu cầu start_session: {username} (Client: {client_id[:10] if client_id else 'N/A'}...)")
        
        # KIỂM TRA PHIÊN HIỆN TẠI
        if active_session["is_active"]:
            current_user = active_session["username"]
            return jsonify({
                "status": "conflict",
                "message": f"Phiên làm việc đang được sử dụng bởi {current_user}"
            })
        
        # BẮT ĐẦU PHIÊN MỚI
        session_id = generate_session_id()
        
        active_session.update({
            "is_active": True,
            "username": username,
            "start_time": datetime.now().isoformat(),
            "session_id": session_id,
            "client_id": client_id
        })
        
        print(f"✅ ĐÃ BẮT ĐẦU PHIÊN: {username}")
        
        # Gửi thông báo đến LINE group
        send_to_group(f"🎯 **BẮT ĐẦU PHIÊN MỚI**\n👤 User: {username}")
        
        return jsonify({
            "status": "started",
            "message": f"Đã bắt đầu phiên làm việc cho {username}",
            "session_id": session_id
        })
        
    except Exception as e:
        print(f"Start session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/end_session', methods=['POST'])
def api_end_session():
    """API để client thông báo kết thúc phiên"""
    try:
        data = request.get_json()
        username = data.get('username')
        reason = data.get('reason', 'normal_exit')
        message = data.get('message', '')
        
        print(f"📥 Nhận end_session: username={username}, reason={reason}")
        
        # RESET TOÀN BỘ HỆ THỐNG
        if active_session["is_active"]:
            ended_username = active_session["username"]
            reset_system()
            
            print(f"✅ Đã kết thúc phiên của {ended_username}")
            
            if message:
                send_to_group(message)
            
            return jsonify({
                "status": "ended",
                "message": f"Đã kết thúc phiên làm việc của {ended_username}",
                "system_reset": True
            })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để kết thúc"
        })
        
    except Exception as e:
        print(f"End session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/complete_command', methods=['POST'])
def api_complete_command():
    """API đánh dấu lệnh đã hoàn thành"""
    try:
        data = request.get_json()
        client_id = data.get('client_id')
        command_id = data.get('command_id')
        
        print(f"📥 Nhận complete_command: client={client_id[:10] if client_id else 'unknown'}, cmd_id={command_id}")
        
        # XÓA COMMAND HIỆN TẠI
        global current_command
        if current_command and current_command.get('id') == command_id:
            current_command = None
            print(f"✅ Đã xóa lệnh {command_id}")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    """API để client gửi tin nhắn LINE"""
    try:
        data = request.get_json()
        target_id = data.get('user_id')
        message = data.get('message')
        
        if target_id and message:
            success = send_line_message(target_id, message)
            return jsonify({"status": "sent" if success else "error"})
        return jsonify({"status": "error", "message": "Missing parameters"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📊 HEALTH & MONITORING ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "server": "LINE Ticket Automation Server",
        "version": "SIMPLE - Mỗi phiên mới hoàn toàn",
        "timestamp": datetime.now().isoformat(),
        "active_session": {
            "is_active": active_session["is_active"],
            "username": active_session["username"],
            "client_id": active_session["client_id"][:10] + "..." if active_session["client_id"] else None
        },
        "has_pending_command": current_command is not None,
        "simplicity": "✅ Mỗi phiên là HOÀN TOÀN MỚI, tự động reset"
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "status": "ACTIVE",
        "active_session": active_session["is_active"],
        "active_user": active_session["username"],
        "simplicity": "Mỗi phiên là mới hoàn toàn"
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================================
🚀 SERVER START - ĐƠN GIẢN HOÀN TOÀN
🚀 ========================================================
🌐 Server URL: {SERVER_URL}
👥 LINE Group ID: {LINE_GROUP_ID}

🎯 NGUYÊN TẮC HOẠT ĐỘNG:
• CHỈ 1 PHIÊN duy nhất tại thời điểm
• Mỗi phiên là HOÀN TOÀN MỚI
• Tự động RESET sau khi kết thúc
• KHÔNG lưu trữ lịch sử phiên cũ

📊 TRẠNG THÁI HIỆN TẠI:
• Session: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
• Active User: {active_session["username"] if active_session["is_active"] else 'None'}
• Pending Command: {'Có' if current_command else 'Không có'}
• Time: {datetime.now().strftime('%H:%M:%S')}
========================================================
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False)
