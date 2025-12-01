# app.py (SERVER - FIX LỆNH VỀ LOCAL)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import time
import random

# ==================== ⚙️ CẤU HÌNH ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "ZpXWbVLYaj"

# ==================== 📊 BIẾN TOÀN CỤC ====================
# QUẢN LÝ PHIÊN
active_session = {
    "is_active": False,
    "username": None,
    "start_time": None,
    "session_id": None,
    "client_id": None
}

# LỆNH ĐANG CHỜ - KEY LÀ CLIENT_ID
pending_commands = {}

# CLIENT ĐÃ ĐĂNG KÝ
registered_clients = {}

def generate_client_id():
    return f"client_{int(time.time())}_{random.randint(1000, 9999)}"

def generate_session_id():
    return f"session_{int(time.time())}_{random.randint(1000, 9999)}"

def send_line_reply(reply_token, text):
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
        return response.status_code == 200
    except:
        return False

def send_line_message(chat_id, text):
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
        return response.status_code == 200
    except:
        return False

def send_to_group(text):
    if LINE_GROUP_ID:
        return send_line_message(LINE_GROUP_ID, text)
    return False

# ==================== 🌐 WEBHOOK LINE ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
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
                                f"⚠️ **{current_user} đang sử dụng tools.**\n"
                                f"📌 Vui lòng đợi {current_user} thoát web (.thoát web)"
                            )
                            continue
                        
                        # TẠO LỆNH CHO TẤT CẢ CLIENT ĐÃ ĐĂNG KÝ
                        command_id = f"cmd_{int(time.time())}"
                        command_data = {
                            "id": command_id,
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        # Gửi lệnh đến tất cả client đã đăng ký
                        for client_id in registered_clients.keys():
                            pending_commands[client_id] = command_data
                            print(f"📨 Gửi lệnh login đến client: {client_id[:10]}...")
                        
                        send_line_reply(reply_token, 
                            f"✅ **Đã nhận lệnh đăng nhập cho {username}**\n"
                            f"📤 Đang gửi lệnh đến local daemon..."
                        )
                        
                        print(f"📝 Lưu lệnh login cho {username}, gửi đến {len(registered_clients)} client")
                        
                    else:
                        send_line_reply(reply_token, "❌ Sai cú pháp! Dùng: .login username:password")
                
                # LỆNH THOÁT WEB
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng']:
                    if active_session["is_active"]:
                        current_user = active_session["username"]
                        client_id = active_session["client_id"]
                        
                        if client_id:
                            # Tạo lệnh stop cho client đang active
                            command_id = f"cmd_{int(time.time())}"
                            pending_commands[client_id] = {
                                "id": command_id,
                                "type": "stop_automation",
                                "username": current_user,
                                "timestamp": datetime.now().isoformat()
                            }
                            print(f"📤 Gửi lệnh stop đến client: {client_id[:10]}...")
                        
                        send_line_reply(reply_token, f"🚪 **Đang yêu cầu {current_user} thoát web...**")
                    else:
                        send_line_reply(reply_token, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai']:
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
                        
                        status_text = f"""📊 **TRẠNG THÁI**

👤 User: {active_session['username']}
⏱️ Thời gian: {duration_text}
🆔 Session: {active_session['session_id'][:10]}...
💡 Gõ '.thoát web' để kết thúc"""
                    else:
                        status_text = f"""📊 **TRẠNG THÁI**

🟢 Trạng thái: STANDBY
🎯 Sẵn sàng nhận phiên mới
📡 Client đã kết nối: {len(registered_clients)}
💡 Gõ '.login username:password' để bắt đầu"""
                    
                    send_line_reply(reply_token, status_text)
                
                # LỆNH HELP
                elif message_text in ['.help', 'help']:
                    help_text = """📋 **LỆNH:**
• .login username:password - Bắt đầu phiên
• .thoát web - Kết thúc phiên
• .status - Xem trạng thái
• .help - Hướng dẫn"""
                    send_line_reply(reply_token, help_text)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 🎯 API CHO LOCAL DAEMON ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API đăng ký client - QUAN TRỌNG"""
    try:
        client_ip = request.remote_addr
        client_id = generate_client_id()
        
        # Lưu client đã đăng ký
        registered_clients[client_id] = {
            "ip": client_ip,
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        }
        
        print(f"✅ Client đăng ký: {client_id[:10]}... từ IP: {client_ip}")
        print(f"📊 Tổng client đã đăng ký: {len(registered_clients)}")
        
        # Kiểm tra nếu có lệnh đang chờ cho client này
        has_command = client_id in pending_commands
        command = pending_commands.get(client_id) if has_command else None
        
        response_data = {
            "status": "registered", 
            "client_id": client_id,
            "has_command": has_command,
            "command": command,
            "session_active": active_session["is_active"],
            "active_user": active_session["username"]
        }
        
        if has_command:
            print(f"📨 Client {client_id[:10]}... có lệnh đang chờ: {command.get('type')}")
        
        return jsonify(response_data)
            
    except Exception as e:
        print(f"❌ Register error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_command/<client_id>', methods=['GET'])
def api_get_command(client_id):
    """API lấy lệnh - QUAN TRỌNG"""
    try:
        # Cập nhật last seen
        if client_id in registered_clients:
            registered_clients[client_id]['last_seen'] = datetime.now().isoformat()
        
        print(f"🔍 Client {client_id[:10]}... đang check command")
        
        if client_id in pending_commands:
            command = pending_commands[client_id]
            print(f"📤 Gửi command đến {client_id[:10]}...: {command.get('type')}")
            return jsonify({
                "has_command": True,
                "command": command
            })
        else:
            return jsonify({"has_command": False})
    except Exception as e:
        print(f"❌ Get command error: {e}")
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên"""
    try:
        data = request.get_json()
        username = data.get('username')
        client_id = data.get('client_id')
        
        print(f"📥 Start session: {username} (Client: {client_id[:10] if client_id else 'N/A'})")
        
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
        
        # Gửi thông báo LINE
        send_to_group(f"🎯 **BẮT ĐẦU PHIÊN**\n👤 User: {username}\n⏰ {datetime.now().strftime('%H:%M')}")
        
        return jsonify({
            "status": "started",
            "message": f"Đã bắt đầu phiên làm việc cho {username}",
            "session_id": session_id
        })
        
    except Exception as e:
        print(f"❌ Start session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/end_session', methods=['POST'])
def api_end_session():
    """API kết thúc phiên"""
    try:
        data = request.get_json()
        username = data.get('username')
        reason = data.get('reason', 'normal_exit')
        message = data.get('message', '')
        
        print(f"📥 End session: {username}, reason: {reason}")
        
        if active_session["is_active"]:
            ended_user = active_session["username"]
            ended_client = active_session["client_id"]
            
            # Xóa lệnh pending của client này
            if ended_client in pending_commands:
                del pending_commands[ended_client]
                print(f"🧹 Đã xóa lệnh pending của client {ended_client[:10]}...")
            
            # Reset session
            active_session.update({
                "is_active": False,
                "username": None,
                "start_time": None,
                "session_id": None,
                "client_id": None
            })
            
            print(f"✅ ĐÃ KẾT THÚC PHIÊN: {ended_user}")
            
            if message:
                send_to_group(message)
            
            return jsonify({
                "status": "ended",
                "message": f"Đã kết thúc phiên của {ended_user}",
                "system_reset": True
            })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để kết thúc"
        })
        
    except Exception as e:
        print(f"❌ End session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/complete_command', methods=['POST'])
def api_complete_command():
    """API hoàn thành lệnh"""
    try:
        data = request.get_json()
        client_id = data.get('client_id')
        command_id = data.get('command_id')
        
        print(f"📥 Complete command: client={client_id[:10] if client_id else 'unknown'}, cmd={command_id}")
        
        # Xóa lệnh đã hoàn thành
        if client_id in pending_commands and pending_commands[client_id]["id"] == command_id:
            del pending_commands[client_id]
            print(f"✅ Đã xóa lệnh {command_id} của client {client_id[:10]}...")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    """API gửi tin nhắn LINE"""
    try:
        data = request.get_json()
        target_id = data.get('user_id')
        message = data.get('message')
        
        if target_id and message:
            success = send_line_message(target_id, message)
            return jsonify({"status": "sent" if success else "error"})
        return jsonify({"status": "error", "message": "Thiếu tham số"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📊 HEALTH ====================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "server": "LINE Automation Server",
        "active_session": {
            "is_active": active_session["is_active"],
            "username": active_session["username"],
            "client_id": active_session["client_id"][:10] + "..." if active_session["client_id"] else None
        },
        "pending_commands": len(pending_commands),
        "registered_clients": len(registered_clients),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "LINE Ticket Automation",
        "active": active_session["is_active"],
        "user": active_session["username"],
        "clients": len(registered_clients)
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================
🚀 SERVER START - FIX LỆNH VỀ LOCAL
🚀 ========================================
🌐 Server: {SERVER_URL}
👥 Group: {LINE_GROUP_ID}

🎯 CẤU TRÚC:
• 1 phiên duy nhất
• Lệnh gửi đến tất cả client
• Tự động cleanup

📊 HIỆN TẠI:
• Session: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
• User: {active_session["username"] or 'None'}
• Clients: {len(registered_clients)}
• Time: {datetime.now().strftime('%H:%M:%S')}
========================================
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False)
