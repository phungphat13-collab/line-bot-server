# app.py (SERVER - FIX HOÀN CHỈNH CHO LOCAL DAEMON)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime, time as dt_time, timedelta  # THÊM TIMEDELTA Ở ĐÂY
import time
import threading
import gc
import random
import string

# ==================== ⚙️ CẤU HÌNH ====================
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# TOKEN LINE BOT
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"

# ID nhóm LINE để nhận thông báo
LINE_GROUP_ID = "ZpXWbVLYaj"

# ==================== 📊 BIẾN TOÀN CỤC ====================
# QUẢN LÝ PHIÊN LÀM VIỆC
active_session = {
    "is_active": False,
    "username": None,
    "line_user_id": None,      # LINE User ID (người gửi lệnh)
    "client_user_id": None,    # Client User ID (local daemon)
    "start_time": None,
    "session_id": None,
    "end_reason": None,
    "end_time": None,
    "last_activity": None
}

# LỆNH ĐANG CHỜ XỬ LÝ - FIX: key = client_user_id hoặc line_user_id
pending_commands = {}  # Format: {"client_user_id": command} hoặc {"line_user_id": command}

# CLIENT REGISTRY - FIX: lưu client info
client_registry = {}  # Format: {"CLIENT_USER_ID": {"line_user_id": "xxx", "ip": "xxx", "last_seen": "xxx"}}

# CHỐNG SPAM MESSAGE
message_cooldown = {}

# ==================== 🧹 DỌN DẸP DỮ LIỆU ====================
def cleanup_old_data():
    """Dọn dẹp dữ liệu cũ"""
    try:
        current_time = time.time()
        
        # Xóa cooldown cũ (5 phút)
        expired_cooldowns = [k for k, v in message_cooldown.items() 
                           if current_time - v > 300]
        for key in expired_cooldowns:
            del message_cooldown[key]
            
        # Xóa commands trống hoặc cũ (quá 30 phút)
        expired_commands = []
        for cmd_id, cmd in pending_commands.items():
            if cmd.get('timestamp'):
                try:
                    cmd_time = datetime.fromisoformat(cmd['timestamp'])
                    if (datetime.now() - cmd_time).total_seconds() > 1800:
                        expired_commands.append(cmd_id)
                except:
                    expired_commands.append(cmd_id)
        
        for cmd_id in expired_commands:
            del pending_commands[cmd_id]
            
        # Xóa client registry cũ (quá 1 giờ không hoạt động)
        expired_clients = []
        for client_id, client_info in client_registry.items():
            if client_info.get('last_seen'):
                try:
                    last_seen = datetime.fromisoformat(client_info['last_seen'])
                    if (datetime.now() - last_seen).total_seconds() > 3600:
                        expired_clients.append(client_id)
                except:
                    expired_clients.append(client_id)
        
        for client_id in expired_clients:
            del client_registry[client_id]
            
    except Exception as e:
        print(f"Cleanup error: {e}")

# ==================== 🛡️ CHỐNG SLEEP ====================
def keep_alive():
    """Giữ server không bị sleep"""
    time.sleep(15)
    
    while True:
        try:
            requests.get(f"{SERVER_URL}/health", timeout=2)
            print(f"✅ Keep-alive at {datetime.now().strftime('%H:%M')}")
            
            cleanup_old_data()
            gc.collect()
            
        except Exception as e:
            print(f"⚠️ Keep-alive: {e}")
        
        time.sleep(300)

# Khởi chạy keep-alive
keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()
print("🛡️ Keep-alive started")

# ==================== 🔧 HÀM TIỆN ÍCH ====================
def generate_client_user_id():
    """Tạo Client User ID ngẫu nhiên"""
    return f"client_{int(time.time())}_{random.randint(1000, 9999)}"

def generate_session_id():
    """Tạo Session ID ngẫu nhiên"""
    return f"session_{int(time.time())}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"

def update_client_last_seen(client_user_id, ip_address=None):
    """Cập nhật thời gian hoạt động cuối của client"""
    if client_user_id in client_registry:
        client_registry[client_user_id]['last_seen'] = datetime.now().isoformat()
        if ip_address:
            client_registry[client_user_id]['ip'] = ip_address

# ==================== 📱 HÀM GỬI LINE ====================
def send_line_reply(reply_token, text):
    """Gửi tin nhắn reply LINE (ngay lập tức)"""
    try:
        key = f"reply_{reply_token}"
        current_time = time.time()
        if key in message_cooldown and current_time - message_cooldown[key] < 5:
            return False
            
        message_cooldown[key] = current_time
        
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
            print(f"❌ Reply LINE failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.warning(f"Line reply failed: {e}")
        return False

def send_line_message(chat_id, text, chat_type="user"):
    """Gửi tin nhắn LINE push"""
    try:
        key = f"{chat_id}_{hash(text) % 10000}"
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
        
        response = requests.post(url, headers=headers, json=data, timeout=3)
        if response.status_code == 200:
            print(f"✅ Đã gửi LINE push: {text[:50]}...")
            return True
        else:
            print(f"❌ LINE push failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.warning(f"Line push failed: {e}")
        return False

def send_to_group(text):
    """Gửi tin nhắn đến nhóm LINE"""
    try:
        if LINE_GROUP_ID:
            return send_line_message(LINE_GROUP_ID, text, "group")
        else:
            print("❌ Không có LINE_GROUP_ID")
            return False
    except Exception as e:
        logger.error(f"Send to group error: {e}")
        return False

# ==================== 🔧 HÀM QUẢN LÝ PHIÊN ====================
def update_session_activity():
    """Cập nhật thời gian hoạt động cuối của phiên"""
    if active_session["is_active"]:
        active_session["last_activity"] = datetime.now().isoformat()

def start_new_session(username, line_user_id, client_user_id):
    """Bắt đầu phiên làm việc mới"""
    if active_session["is_active"]:
        current_user = active_session["username"]
        return False, f"Phiên làm việc đang được sử dụng bởi {current_user}"
    
    session_id = generate_session_id()
    
    # Cập nhật thông tin session
    active_session.update({
        "is_active": True,
        "username": username,
        "line_user_id": line_user_id,
        "client_user_id": client_user_id,
        "start_time": datetime.now().isoformat(),
        "session_id": session_id,
        "end_reason": None,
        "end_time": None,
        "last_activity": datetime.now().isoformat()
    })
    
    print(f"✅ ĐÃ BẮT ĐẦU PHIÊN: {username} (LINE: {line_user_id[:8] if line_user_id else 'N/A'}..., Client: {client_user_id[:10] if client_user_id else 'N/A'}...)")
    
    return True, f"Đã bắt đầu phiên làm việc cho {username}"

def end_current_session(username=None, reason="normal_exit", message=""):
    """Kết thúc phiên - LUÔN RESET PHIÊN"""
    if not active_session["is_active"]:
        print(f"⚠️ Không có phiên nào để kết thúc")
        return False, "Không có phiên làm việc nào đang chạy"
    
    current_username = active_session["username"]
    line_user_id = active_session["line_user_id"]
    client_user_id = active_session["client_user_id"]
    
    print(f"📌 Đang kết thúc phiên: {current_username} (LINE: {line_user_id[:8] if line_user_id else 'N/A'}...) - Lý do: {reason}")
    
    # XÓA LỆNH PENDING CỦA CLIENT NÀY NẾU CÓ
    if client_user_id and client_user_id in pending_commands:
        del pending_commands[client_user_id]
        print(f"🧹 Đã xóa pending command của client: {client_user_id[:10]}...")
    
    # XÓA CLIENT REGISTRY NẾU CÓ
    if client_user_id and client_user_id in client_registry:
        del client_registry[client_user_id]
        print(f"🧹 Đã xóa client registry: {client_user_id[:10]}...")
    
    # RESET ACTIVE SESSION
    active_session.update({
        "is_active": False,
        "username": None,
        "line_user_id": None,
        "client_user_id": None,
        "start_time": None,
        "session_id": None,
        "end_reason": reason,
        "end_time": datetime.now().isoformat(),
        "last_activity": None
    })
    
    print(f"✅ ĐÃ KẾT THÚC PHIÊN: {current_username} - Reason: {reason}")
    
    # Gửi thông báo LINE nếu có
    if reason == "normal_exit" and message:
        send_to_group(message)
    
    return True, f"Đã kết thúc phiên làm việc của {current_username}"

def get_session_info():
    """Lấy thông tin phiên hiện tại"""
    if not active_session["is_active"]:
        return {
            "is_active": False,
            "message": "Không có phiên làm việc nào đang chạy",
            "status": "STANDBY",
            "is_ready_for_new_session": True
        }
    
    try:
        start_time = active_session["start_time"]
        if start_time:
            start_dt = datetime.fromisoformat(start_time)
            duration = datetime.now() - start_dt
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            duration_text = f"{hours}h{minutes}p"
        else:
            duration_text = "Unknown"
    except:
        duration_text = "Unknown"
    
    return {
        "is_active": True,
        "username": active_session["username"],
        "line_user_id": active_session["line_user_id"],
        "client_user_id": active_session["client_user_id"],
        "start_time": active_session["start_time"],
        "duration": duration_text,
        "session_id": active_session["session_id"],
        "last_activity": active_session["last_activity"],
        "status": "ACTIVE",
        "is_ready_for_new_session": False
    }

def create_command_for_client(client_user_id, command_type, username=None, password=None, reason=None):
    """Tạo command cho client"""
    command_id = f"cmd_{int(time.time())}"
    
    command_data = {
        "id": command_id,
        "type": command_type,
        "timestamp": datetime.now().isoformat(),
        "session_required": True
    }
    
    if username:
        command_data["username"] = username
    if password:
        command_data["password"] = password
    if reason:
        command_data["reason"] = reason
    
    # Lưu command với key là client_user_id
    pending_commands[client_user_id] = command_data
    
    return command_id, command_data

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
            line_user_id = source.get('userId')  # LINE User ID
            group_id = source.get('groupId')
            reply_token = event.get('replyToken')
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                
                # LỆNH LOGIN
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # KIỂM TRA PHIÊN ĐANG CHẠY
                        session_info = get_session_info()
                        if session_info["is_active"]:
                            current_user = session_info["username"]
                            send_line_reply(reply_token, 
                                f"⚠️ **{current_user} đang sử dụng tools.**\n\n"
                                f"📌 Vui lòng đợi {current_user} thoát web (.thoát web)\n"
                                f"💡 Trạng thái: CHỈ 1 PHIÊN tại thời điểm"
                            )
                            continue
                        
                        # Tạo thông báo chờ client đăng ký
                        send_line_reply(reply_token, 
                            f"✅ **Đã nhận lệnh đăng nhập cho {username}**\n"
                            f"⏳ Đang chờ local daemon kết nối...\n"
                            f"💡 Lệnh sẽ được giữ trong 30 phút"
                        )
                        
                        # Tạm thời lưu thông tin login để chờ client
                        temp_command_key = f"temp_{line_user_id}"
                        pending_commands[temp_command_key] = {
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "line_user_id": line_user_id,
                            "timestamp": datetime.now().isoformat(),
                            "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat()  # FIXED: đã có timedelta
                        }
                        
                        print(f"📨 Lệnh login cho {username} từ LINE user_id: {line_user_id[:8]}... (chờ client)")
                        
                    else:
                        send_line_reply(reply_token, "❌ Sai cú pháp! Dùng: .login username:password")
                
                # LỆNH THOÁT WEB
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    session_info = get_session_info()
                    
                    if session_info["is_active"]:
                        current_user = session_info["username"]
                        active_line_user_id = active_session["line_user_id"]
                        active_client_user_id = active_session["client_user_id"]
                        
                        # Nếu là người đang active hoặc trong group
                        if line_user_id == active_line_user_id or group_id:
                            # Tạo command stop cho client đang active
                            if active_client_user_id:
                                cmd_id, cmd_data = create_command_for_client(
                                    client_user_id=active_client_user_id,
                                    command_type="stop_automation",
                                    username=current_user,
                                    reason="normal_exit"
                                )
                                print(f"📤 Đã gửi lệnh stop đến client: {current_user} (client_id: {active_client_user_id[:10]}...)")
                            
                            send_line_reply(reply_token, f"🚪 **Đang yêu cầu {current_user} thoát web...**")
                            
                            # ĐỢI 5 GIÂY RỒI TỰ ĐỘNG KẾT THÚC PHIÊN
                            def delayed_end_session():
                                time.sleep(5)
                                session_info_check = get_session_info()
                                if session_info_check["is_active"] and session_info_check["username"] == current_user:
                                    print(f"⏰ Tự động kết thúc phiên sau timeout: {current_user}")
                                    end_current_session(
                                        username=current_user,
                                        reason="normal_exit",
                                        message=f"🚪 **{current_user} đã thoát web**\n📌 Hệ thống đã về STANDBY"
                                    )
                            
                            threading.Thread(target=delayed_end_session, daemon=True).start()
                        else:
                            send_line_reply(reply_token, f"❌ Bạn không có quyền dừng phiên của {current_user}")
                    else:
                        send_line_reply(reply_token, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai', 'status']:
                    session_info = get_session_info()
                    
                    if session_info["is_active"]:
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

👤 **User đang active:** {session_info['username']}
⏱️ **Thời gian chạy:** {session_info['duration']}
🆔 **Session ID:** {session_info['session_id'][:10]}...

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
• **KHÔNG** cho phép login mới khi có phiên đang chạy
• Phải **.thoát web** hoàn toàn trước khi bắt đầu phiên mới"""
                    
                    send_line_reply(reply_token, help_text)
                
                # LỆNH TEST (ẩn)
                elif message_text == '.test':
                    send_line_reply(reply_token, "✅ Bot đang hoạt động bình thường!")
                    print(f"🧪 Test command từ LINE user: {line_user_id[:8]}...")
        
        return jsonify({"status": "success", "message": "Webhook processed"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 🎯 API QUẢN LÝ PHIÊN ====================

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên làm việc mới"""
    try:
        data = request.get_json()
        username = data.get('username')
        line_user_id = data.get('user_id')  # LINE User ID từ client
        client_user_id = data.get('client_user_id')  # Client User ID
        
        print(f"📥 Yêu cầu start_session: {username} (LINE: {line_user_id[:8] if line_user_id else 'N/A'}..., Client: {client_user_id[:10] if client_user_id else 'N/A'}...)")
        
        # KIỂM TRA PHIÊN HIỆN TẠI
        session_info = get_session_info()
        if session_info["is_active"]:
            current_user = session_info["username"]
            return jsonify({
                "status": "conflict",
                "message": f"Phiên làm việc đang được sử dụng bởi {current_user}",
                "current_session": session_info
            })
        
        # BẮT ĐẦU PHIÊN MỚI
        success, message = start_new_session(username, line_user_id, client_user_id)
        
        if success:
            # Gửi thông báo đến LINE group
            send_to_group(f"🎯 **BẮT ĐẦU PHIÊN MỚI**\n👤 User: {username}")
            
            return jsonify({
                "status": "started",
                "message": message,
                "session_info": get_session_info()
            })
        else:
            return jsonify({"status": "error", "message": message})
        
    except Exception as e:
        logger.error(f"Start session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/end_session', methods=['POST'])
def api_end_session():
    """API để client thông báo kết thúc phiên"""
    try:
        data = request.get_json()
        username = data.get('username')
        reason = data.get('reason', 'unknown')
        message = data.get('message', '')
        client_user_id = data.get('client_user_id')
        
        print(f"📥 Nhận end_session từ client: username={username}, reason={reason}, client={client_user_id[:10] if client_user_id else 'unknown'}")
        
        success, result_message = end_current_session(username, reason, message)
        
        if success:
            return jsonify({
                "status": "ended",
                "message": result_message,
                "reason": reason,
                "session_ended": True,
                "note": "Phiên đã được reset trên server"
            })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để kết thúc",
            "session_ended": False
        })
        
    except Exception as e:
        logger.error(f"End session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_session_info', methods=['GET'])
def api_get_session_info():
    """API lấy thông tin phiên hiện tại"""
    try:
        update_session_activity()
        return jsonify(get_session_info())
    except Exception as e:
        return jsonify({"is_active": False, "error": str(e)})

@app.route('/api/force_end_session', methods=['POST'])
def api_force_end_session():
    """API buộc kết thúc phiên (khi có lỗi)"""
    try:
        data = request.get_json()
        reason = data.get('reason', 'force_end')
        message = data.get('message', '')
        client_user_id = data.get('client_user_id')
        
        print(f"📥 Nhận force_end_session: reason={reason}, client={client_user_id[:10] if client_user_id else 'unknown'}")
        
        success, result_message = end_current_session(reason=reason, message=message)
        
        if success:
            return jsonify({
                "status": "force_ended",
                "message": result_message,
                "reason": reason
            })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để force end"
        })
        
    except Exception as e:
        logger.error(f"Force end session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🔧 API LOCAL CLIENT - FIX QUAN TRỌNG ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API để local client đăng ký và nhận user_id"""
    try:
        data = request.get_json()
        client_ip = request.remote_addr
        
        print(f"📥 Nhận yêu cầu register_local từ IP: {client_ip}")
        
        # TẠO CLIENT USER ID MỚI
        client_user_id = generate_client_user_id()
        
        # KIỂM TRA CÓ LỆNH ĐANG CHỜ KHÔNG (tìm theo temp key)
        temp_command_key = None
        pending_command = None
        
        for key, cmd in pending_commands.items():
            if key.startswith("temp_") and cmd.get('type') == 'start_automation':
                temp_command_key = key
                pending_command = cmd
                break
        
        if pending_command:
            # CÓ LỆNH ĐANG CHỜ - LẤY THÔNG TIN
            username = pending_command.get('username')
            password = pending_command.get('password')
            line_user_id = pending_command.get('line_user_id')
            
            # XÓA TEMP COMMAND
            del pending_commands[temp_command_key]
            
            # TẠO COMMAND CHÍNH THỨC CHO CLIENT NÀY
            cmd_id, cmd_data = create_command_for_client(
                client_user_id=client_user_id,
                command_type="start_automation",
                username=username,
                password=password
            )
            
            # LƯU VÀO CLIENT REGISTRY
            client_registry[client_user_id] = {
                "line_user_id": line_user_id,
                "ip": client_ip,
                "registered_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "command_type": "start_automation"
            }
            
            print(f"🔗 Đăng ký client: {client_user_id[:10]}... cho LINE user: {line_user_id[:8] if line_user_id else 'N/A'}... (có lệnh đang chờ)")
            
            return jsonify({
                "status": "registered", 
                "user_id": line_user_id,      # 🔥 Trả về LINE User ID
                "client_user_id": client_user_id,  # 🔥 Client User ID mới
                "has_command": True,
                "command": cmd_data,
                "session_info": get_session_info()
            })
        else:
            # KHÔNG CÓ LỆNH ĐANG CHỜ - ĐĂNG KÝ THÔNG THƯỜNG
            client_registry[client_user_id] = {
                "ip": client_ip,
                "registered_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "command_type": None
            }
            
            print(f"🔗 Đăng ký client: {client_user_id[:10]}... (không có lệnh đang chờ)")
            
            return jsonify({
                "status": "registered", 
                "client_user_id": client_user_id,
                "has_command": False,
                "session_info": get_session_info()
            })
            
    except Exception as e:
        print(f"❌ Register error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_commands/<client_user_id>', methods=['GET'])
def api_get_commands(client_user_id):
    """API để local client lấy lệnh"""
    try:
        update_session_activity()
        
        # Cập nhật last seen
        if client_user_id in client_registry:
            client_registry[client_user_id]['last_seen'] = datetime.now().isoformat()
        
        if client_user_id in pending_commands:
            command = pending_commands[client_user_id]
            return jsonify({
                "has_command": True,
                "command": command
            })
        else:
            return jsonify({"has_command": False})
    except Exception as e:
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/complete_command', methods=['POST'])
def api_complete_command():
    """API đánh dấu lệnh đã hoàn thành"""
    try:
        data = request.get_json()
        client_user_id = data.get('client_user_id')
        command_id = data.get('command_id')
        
        if not client_user_id:
            return jsonify({"status": "error", "message": "Thiếu client_user_id"})
        
        print(f"📥 Nhận complete_command: client={client_user_id[:10] if client_user_id else 'unknown'}, cmd_id={command_id}")
        
        if client_user_id in pending_commands and pending_commands[client_user_id]["id"] == command_id:
            # Chỉ xóa command nếu đã xử lý xong
            command_type = pending_commands[client_user_id].get('type')
            
            if command_type in ['stop_automation', 'check_status', 'check_schedule']:
                # Xóa ngay các command không quan trọng
                del pending_commands[client_user_id]
                print(f"✅ Đã xóa lệnh {command_id} (type: {command_type})")
            else:
                # Giữ lại command start để retry nếu cần
                print(f"✅ Đã hoàn thành lệnh {command_id}, giữ lại để retry nếu cần")
        
        # Cập nhật last seen
        update_client_last_seen(client_user_id)
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📢 API GỬI TIN NHẮN ====================

@app.route('/api/send_to_group', methods=['POST'])
def api_send_to_group():
    """API để client gửi thông báo LINE"""
    try:
        data = request.get_json()
        message = data.get('message')
        
        if message:
            success = send_to_group(message)
            return jsonify({"status": "sent" if success else "error"})
        return jsonify({"status": "error", "message": "Thiếu nội dung tin nhắn"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    """API để client gửi tin nhắn LINE"""
    try:
        data = request.get_json()
        target_id = data.get('user_id') or data.get('target_id')
        message = data.get('message')
        
        if target_id and message:
            success = send_line_message(target_id, message, "group" if target_id == LINE_GROUP_ID else "user")
            return jsonify({"status": "sent" if success else "error"})
        return jsonify({"status": "error", "message": "Missing parameters"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📊 HEALTH & MONITORING ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    cleanup_old_data()
    
    session_info = get_session_info()
    
    return jsonify({
        "status": "healthy",
        "server": "LINE Ticket Automation Server",
        "version": "15.0 - FIX HOÀN CHỈNH CHO LOCAL",
        "timestamp": datetime.now().isoformat(),
        "session": session_info,
        "pending_commands": len(pending_commands),
        "registered_clients": len(client_registry),
        "line_bot_status": "✅ Webhook Active",
        "fixes": [
            "✅ Tạo Client User ID mới mỗi lần đăng ký",
            "✅ Lưu command với client_user_id (không dùng line_user_id)",
            "✅ Xóa temp command khi client đăng ký",
            "✅ Xóa client registry khi kết thúc phiên"
        ]
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    session_info = get_session_info()
    
    if session_info["is_active"]:
        status_message = f"🎯 **ACTIVE** - User: {session_info['username']} ({session_info['duration']})"
    else:
        status_message = "🟢 **STANDBY** - Sẵn sàng nhận phiên mới"
    
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "version": "15.0 - FIX HOÀN CHỈNH CHO LOCAL",
        "status": status_message,
        "active_session": {
            "username": active_session["username"],
            "line_user_id": active_session["line_user_id"][:8] + "..." if active_session["line_user_id"] else None,
            "client_user_id": active_session["client_user_id"][:10] + "..." if active_session["client_user_id"] else None,
            "is_active": active_session["is_active"]
        },
        "pending_commands": len(pending_commands),
        "registered_clients": len(client_registry)
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================================
🚀 SERVER START - FIX HOÀN CHỈNH CHO LOCAL DAEMON
🚀 ========================================================
🌐 Server URL: {SERVER_URL}
👥 LINE Group ID: {LINE_GROUP_ID}
🛡️ Keep-alive: ACTIVE
🧹 Auto-cleanup: ENABLED

🎯 CẤU TRÚC DỮ LIỆU FIXED:
• active_session: Quản lý phiên hiện tại
• pending_commands: Lưu theo client_user_id
• client_registry: Lưu thông tin client

🔴 FLOW HOẠT ĐỘNG ĐÚNG:
  1. User gửi .login → Server lưu temp command
  2. Client register_local → Nhận client_user_id mới + lệnh
  3. Client start_session → Server bắt đầu phiên
  4. Client xử lý automation
  5. .thoát web → Server tạo command stop → Client nhận → Kết thúc phiên
  6. Server reset hoàn toàn → Sẵn sàng phiên mới

📊 TRẠNG THÁI HIỆN TẠI:
• Session: {get_session_info()['status']}
• Active User: {get_session_info()['username'] if get_session_info()['is_active'] else 'None'}
• Pending Commands: {len(pending_commands)}
• Registered Clients: {len(client_registry)}
• Time: {datetime.now().strftime('%H:%M:%S')}
========================================================
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
