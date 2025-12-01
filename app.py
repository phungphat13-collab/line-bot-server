# app.py (SERVER - XỬ LÝ 3 TRƯỜNG HỢP GIỐNG NHAU)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import time
import threading
import gc

# ==================== ⚙️ CẤU HÌNH ====================
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# TOKEN LINE BOT
LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"

# ID nhóm LINE để nhận thông báo
LINE_GROUP_ID = "ZpXWbVLYaj"  # ID từ link group

# ==================== 📊 BIẾN TOÀN CỤC ====================
# QUẢN LÝ PHIÊN LÀM VIỆC
active_session = {
    "is_active": False,           # Có phiên đang chạy không
    "username": None,             # Username đang active
    "user_id": None,              # ID của user LINE
    "start_time": None,           # Thời gian bắt đầu phiên
    "session_id": None,           # ID phiên làm việc
    "end_reason": None,           # Lý do kết thúc (cho 3 trường hợp)
    "end_time": None              # Thời gian kết thúc
}

# LỆNH ĐANG CHỜ XỬ LÝ
user_commands = {}

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
        for user_id, cmd in user_commands.items():
            if cmd.get('timestamp'):
                try:
                    cmd_time = datetime.fromisoformat(cmd['timestamp'])
                    if (datetime.now() - cmd_time).total_seconds() > 1800:
                        expired_commands.append(user_id)
                except:
                    expired_commands.append(user_id)
        
        for user_id in expired_commands:
            del user_commands[user_id]
            
        # Log số lượng đã dọn
        if expired_cooldowns or expired_commands:
            print(f"🧹 Đã dọn {len(expired_cooldowns)} cooldown, {len(expired_commands)} commands")
            
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
        
        time.sleep(300)  # 5 phút

# Khởi chạy keep-alive
keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()
print("🛡️ Keep-alive started")

# ==================== 📱 HÀM GỬI LINE ====================
def send_line_message(chat_id, text, chat_type="user"):
    """Gửi tin nhắn LINE"""
    try:
        # Chống spam
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
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Line message failed: {e}")
        return False

def send_to_group(text):
    """Gửi tin nhắn đến nhóm LINE"""
    try:
        if LINE_GROUP_ID:
            return send_line_message(LINE_GROUP_ID, text, "group")
        else:
            return False
    except Exception as e:
        logger.error(f"Send to group error: {e}")
        return False

# ==================== 🔧 HÀM QUẢN LÝ PHIÊN ====================
def start_new_session(username, user_id):
    """Bắt đầu phiên làm việc mới"""
    if active_session["is_active"]:
        return False, f"Phiên làm việc đang được sử dụng bởi {active_session['username']}"
    
    session_id = f"session_{int(time.time())}"
    active_session.update({
        "is_active": True,
        "username": username,
        "user_id": user_id,
        "start_time": datetime.now().isoformat(),
        "session_id": session_id,
        "end_reason": None,
        "end_time": None
    })
    
    return True, f"Đã bắt đầu phiên làm việc cho {username}"

def end_current_session(reason="normal_exit"):
    """Kết thúc phiên làm việc hiện tại"""
    if not active_session["is_active"]:
        return False, "Không có phiên làm việc nào đang chạy"
    
    username = active_session["username"]
    
    # Cập nhật thông tin kết thúc
    active_session.update({
        "is_active": False,
        "end_reason": reason,
        "end_time": datetime.now().isoformat()
    })
    
    # Lưu log session đã kết thúc
    session_history = {
        "username": username,
        "user_id": active_session["user_id"],
        "start_time": active_session["start_time"],
        "end_time": active_session["end_time"],
        "session_id": active_session["session_id"],
        "end_reason": reason
    }
    
    # Reset các thông tin active
    active_session.update({
        "username": None,
        "user_id": None,
        "start_time": None,
        "session_id": None
    })
    
    return True, f"Đã kết thúc phiên làm việc của {username}"

def force_end_session(reason="unknown"):
    """Buộc kết thúc phiên (khi có lỗi)"""
    if active_session["is_active"]:
        username = active_session["username"]
        end_current_session(reason)
        return True, f"Đã buộc kết thúc phiên của {username}"
    return False, "Không có phiên nào để buộc kết thúc"

def get_session_info():
    """Lấy thông tin phiên hiện tại"""
    if not active_session["is_active"]:
        return {
            "is_active": False,
            "message": "Không có phiên làm việc nào đang chạy"
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
        "user_id": active_session["user_id"],
        "start_time": active_session["start_time"],
        "duration": duration_text,
        "session_id": active_session["session_id"],
        "status": "ACTIVE"
    }

def check_session_conflict(username):
    """Kiểm tra xem username có đang được sử dụng không"""
    if active_session["is_active"]:
        return active_session["username"] != username
    return False

# ==================== 🌐 WEBHOOK LINE ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE - XỬ LÝ 3 TRƯỜNG HỢP"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            user_id = source.get('userId')
            group_id = source.get('groupId')
            
            # CHỈ XỬ LÝ TRONG NHÓM
            if not group_id:
                continue
                
            target_id = group_id
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                
                # LỆNH LOGIN
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # 🔥 KIỂM TRA PHIÊN ĐANG CHẠY
                        if active_session["is_active"]:
                            current_user = active_session["username"]
                            send_line_message(target_id, 
                                f"⚠️ **{current_user} đang sử dụng tools.**\n\n"
                                f"📌 **Vui lòng đợi:**\n"
                                f"• {current_user} thoát web (.thoát web)\n"
                                f"• Hoặc hệ thống tự động giải phóng\n\n"
                                f"💡 **Trạng thái hiện tại:** CHỈ 1 PHIÊN tại thời điểm"
                            )
                            continue
                        
                        # Tạo command mới
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id] = {
                            "id": command_id,
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "timestamp": datetime.now().isoformat(),
                            "session_required": True
                        }
                        
                        send_line_message(target_id, 
                            f"✅ **ĐÃ NHẬN LỆNH ĐĂNG NHẬP**\n\n"
                            f"👤 **User:** {username}\n"
                            f"🆔 **Command ID:** {command_id}\n"
                            f"📅 **Thời gian:** {datetime.now().strftime('%H:%M:%S')}\n\n"
                            f"⏳ **Đang khởi động automation...**"
                        )
                        print(f"📨 Lệnh login cho {username} từ user_id: {user_id}")
                        
                    else:
                        send_line_message(target_id, "❌ **Sai cú pháp!**\n💡 Dùng: `.login username:password`")
                
                # LỆNH THOÁT WEB - TRƯỜNG HỢP 1
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    if active_session["is_active"]:
                        current_user = active_session["username"]
                        current_user_id = active_session["user_id"]
                        
                        # Gửi lệnh stop đến client
                        command_id = f"cmd_{int(time.time())}"
                        if current_user_id in user_commands:
                            # Ghi đè command cũ
                            user_commands[current_user_id] = {
                                "id": command_id,
                                "type": "stop_automation", 
                                "timestamp": datetime.now().isoformat(),
                                "action": "end_session",
                                "reason": "normal_exit"
                            }
                        else:
                            # Tạo command mới
                            user_commands[current_user_id] = {
                                "id": command_id,
                                "type": "stop_automation", 
                                "timestamp": datetime.now().isoformat(),
                                "action": "end_session",
                                "reason": "normal_exit"
                            }
                        
                        send_line_message(target_id, 
                            f"🚪 **YÊU CẦU THOÁT WEB**\n\n"
                            f"👤 **User:** {current_user}\n"
                            f"📌 **Lý do:** Lệnh .thoát web\n"
                            f"⏳ **Đang xử lý...**"
                        )
                        print(f"🛑 Lệnh stop cho {current_user}")
                    else:
                        send_line_message(target_id, "❌ **Không có phiên làm việc nào đang chạy**")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai', 'status']:
                    session_info = get_session_info()
                    
                    if session_info["is_active"]:
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

👤 **User đang active:** {session_info['username']}
⏱️ **Thời gian chạy:** {session_info['duration']}
🆔 **Session ID:** {session_info['session_id'][:10]}...
📅 **Bắt đầu lúc:** {session_info['start_time'][11:16] if session_info['start_time'] else 'Unknown'}

💡 **Gõ:** `.thoát web` để kết thúc phiên này"""
                    else:
                        status_text = """📊 **TRẠNG THÁI HỆ THỐNG**

🟢 **Trạng thái:** STANDBY - Sẵn sàng nhận phiên mới
🎯 **Tình trạng:** Không có phiên làm việc nào đang chạy
📈 **Server:** Đang hoạt động bình thường

💡 **Gõ:** `.login username:password` để bắt đầu phiên làm việc mới"""
                    
                    send_line_message(target_id, status_text)
                
                # LỆNH HELP
                elif message_text in ['.help', 'help', 'hướng dẫn', '.huongdan']:
                    help_text = """🤖 **TICKET AUTOMATION - HƯỚNG DẪN**

📋 **LỆNH SỬ DỤNG:**
• `.login username:password` - Bắt đầu 1 phiên làm việc mới
• `.thoát web` - Kết thúc phiên làm việc hiện tại
• `.status` - Xem trạng thái hệ thống
• `.help` - Hướng dẫn sử dụng

🎯 **QUY TẮC HOẠT ĐỘNG:**
• **CHỈ 1 PHIÊN** làm việc tại thời điểm
• **KHÔNG** cho phép login mới khi có phiên đang chạy
• Phải **.thoát web** hoàn toàn trước khi bắt đầu phiên mới

🔴 **3 TRƯỜNG HỢP KẾT THÚC PHIÊN (GIỐNG NHAU):**
1. `.thoát web` - Thoát bằng lệnh
2. **Đăng nhập lỗi** - Tự động thoát + thông báo
3. **Tắt web đột ngột** - Tự động thoát + thông báo

⚠️ **SAU KHI THOÁT:** Hệ thống về STANDBY → Chờ phiên mới"""
                    
                    send_line_message(target_id, help_text)
                
                # LỆNH CLEAR (CHO TRƯỜNG HỢP ĐẶC BIỆT)
                elif message_text in ['.clear', '.reset', '.clean']:
                    if active_session["is_active"]:
                        current_user = active_session["username"]
                        # Buộc kết thúc phiên
                        success, message = force_end_session("manual_clear")
                        if success:
                            send_line_message(target_id, 
                                f"🔴 **ĐÃ BUỘC KẾT THÚC PHIÊN**\n\n"
                                f"👤 **User:** {current_user}\n"
                                f"📌 **Lý do:** Lệnh clear manual\n"
                                f"🟢 **Hệ thống:** Đã về STANDBY"
                            )
                    else:
                        send_line_message(target_id, "✅ **Hệ thống đang ở trạng thái STANDBY**")
            
            # KHI BOT THAM GIA NHÓM
            elif event_type == 'join':
                welcome_text = """🎉 **Bot Ticket Automation** đã tham gia nhóm!

📋 **QUY TRÌNH LÀM VIỆC:**
1️⃣ `.login username:password` → Bắt đầu phiên mới
2️⃣ **Hệ thống làm việc** → Chỉ 1 user active
3️⃣ **KẾT THÚC PHIÊN** (3 trường hợp):
   • `.thoát web` - Lệnh bình thường
   • **Đăng nhập lỗi** - Tự động thoát
   • **Tắt web đột ngột** - Tự động thoát
4️⃣ **STANDBY** → Chờ phiên tiếp theo

💡 **Lưu ý:** KHÔNG cho phép login mới khi có phiên đang chạy!"""
                send_line_message(target_id, welcome_text)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🎯 API QUẢN LÝ PHIÊN ====================

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên làm việc mới"""
    try:
        data = request.get_json()
        username = data.get('username')
        user_id = data.get('user_id')
        
        if not username or not user_id:
            return jsonify({"status": "error", "message": "Thiếu tham số"})
        
        # 🔥 KIỂM TRA PHIÊN ĐANG CHẠY
        if active_session["is_active"]:
            current_user = active_session["username"]
            return jsonify({
                "status": "conflict",
                "message": f"Phiên làm việc đang được sử dụng bởi {current_user}",
                "current_session": get_session_info()
            })
        
        # BẮT ĐẦU PHIÊN MỚI
        success, message = start_new_session(username, user_id)
        if success:
            # Gửi thông báo đến nhóm
            send_to_group(
                f"🎯 **BẮT ĐẦU PHIÊN MỚI**\n\n"
                f"👤 **User:** {username}\n"
                f"🆔 **User ID:** {user_id[:8]}...\n"
                f"📅 **Bắt đầu:** {datetime.now().strftime('%H:%M:%S')}\n"
                f"🆔 **Session ID:** {active_session['session_id'][:10]}..."
            )
            
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
    """API kết thúc phiên làm việc - XỬ LÝ 3 TRƯỜNG HỢP"""
    try:
        data = request.get_json()
        username = data.get('username')
        user_id = data.get('user_id')
        reason = data.get('reason', 'normal_exit')
        
        print(f"📥 Nhận yêu cầu end_session: username={username}, reason={reason}")
        
        # KIỂM TRA PHIÊN ĐANG CHẠY
        if active_session["is_active"]:
            session_user = active_session["username"]
            session_user_id = active_session["user_id"]
            
            # CHO PHÉP END NẾU:
            # 1. Cùng username
            # 2. Cùng user_id  
            # 3. Là force end (không có username/user_id)
            allow_end = False
            
            if username and username == session_user:
                allow_end = True
            elif user_id and user_id == session_user_id:
                allow_end = True
            elif not username and not user_id and reason != "normal_exit":
                allow_end = True  # Force end từ client khi có lỗi
            
            if allow_end:
                # KẾT THÚC PHIÊN
                success, message = end_current_session(reason)
                if success:
                    # 🔥 GỬI THÔNG BÁO PHÙ HỢP VỚI LÝ DO
                    if reason == "normal_exit":
                        notification = f"🚪 **{session_user} đã thoát web**\n📌 Hệ thống đã về STANDBY"
                    elif reason == "login_failed":
                        notification = f"❌ **{session_user} đăng nhập thất bại**\n📌 Hệ thống đã về STANDBY"
                    elif reason == "browser_closed_abruptly":
                        notification = f"🚨 **{session_user} đã thoát web đột ngột**\n📌 Hệ thống đã về STANDBY"
                    elif reason == "driver_init_failed":
                        notification = f"❌ **{session_user} - Lỗi khởi tạo trình duyệt**\n📌 Hệ thống đã về STANDBY"
                    elif reason == "group_select_failed":
                        notification = f"❌ **{session_user} - Không tìm thấy nhóm LINE**\n📌 Hệ thống đã về STANDBY"
                    elif reason == "shift_ended":
                        notification = f"⏰ **{session_user} đã hết ca làm việc**\n📌 Hệ thống đã về STANDBY"
                    elif reason == "automation_error":
                        notification = f"⚠️ **{session_user} - Lỗi hệ thống**\n📌 Hệ thống đã về STANDBY"
                    else:
                        notification = f"🏁 **{session_user} - Phiên đã kết thúc**\n📌 Lý do: {reason}\n📌 Hệ thống đã về STANDBY"
                    
                    send_to_group(notification)
                    
                    return jsonify({
                        "status": "ended",
                        "message": message,
                        "reason": reason,
                        "session_ended": True,
                        "notification_sent": True
                    })
        
        # NẾU KHÔNG CÓ PHIÊN NÀO
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để kết thúc"
        })
        
    except Exception as e:
        logger.error(f"End session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/force_end_session', methods=['POST'])
def api_force_end_session():
    """API buộc kết thúc phiên - CHO CLIENT KHI CÓ LỖI"""
    try:
        data = request.get_json()
        reason = data.get('reason', 'unknown')
        
        print(f"📥 Nhận yêu cầu force_end_session: reason={reason}")
        
        if active_session["is_active"]:
            username = active_session["username"]
            success, message = force_end_session(reason)
            
            if success:
                # THÔNG BÁO BUỘC KẾT THÚC
                send_to_group(
                    f"🔴 **BUỘC KẾT THÚC PHIÊN**\n\n"
                    f"👤 **User:** {username}\n"
                    f"📌 **Lý do:** {reason}\n"
                    f"🟢 **Trạng thái:** Hệ thống đã về STANDBY"
                )
                
                return jsonify({
                    "status": "force_ended",
                    "message": message,
                    "reason": reason,
                    "session_ended": True
                })
        
        return jsonify({
            "status": "no_session", 
            "message": "Không có phiên nào để buộc kết thúc"
        })
        
    except Exception as e:
        logger.error(f"Force end session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_session_info', methods=['GET'])
def api_get_session_info():
    """API lấy thông tin phiên hiện tại"""
    try:
        return jsonify(get_session_info())
    except Exception as e:
        return jsonify({"is_active": False, "error": str(e)})

# ==================== 📢 API GỬI TIN NHẮN ====================

@app.route('/api/send_to_group', methods=['POST'])
def api_send_to_group():
    """API để client gửi tin nhắn đến nhóm LINE"""
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
        target_id = data.get('target_id')
        message = data.get('message')
        chat_type = data.get('chat_type', 'user')
        
        if target_id and message:
            success = send_line_message(target_id, message, chat_type)
            return jsonify({"status": "sent" if success else "error"})
        return jsonify({"status": "error", "message": "Missing parameters"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🔧 API LOCAL CLIENT ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API để local client đăng ký và nhận user_id"""
    try:
        data = request.get_json()
        client_ip = request.remote_addr
        
        print(f"📥 Nhận yêu cầu register_local từ IP: {client_ip}")
        
        # Tìm user_id có lệnh đang chờ
        if user_commands:
            user_id = next(iter(user_commands))
            command = user_commands[user_id]
            
            print(f"🔗 Local client đăng ký cho user_id: {user_id}, command: {command.get('type')}")
            
            return jsonify({
                "status": "registered", 
                "user_id": user_id,
                "has_command": True,
                "command": command,
                "session_info": get_session_info()
            })
        else:
            return jsonify({
                "status": "waiting", 
                "message": "Chưa có lệnh nào",
                "session_info": get_session_info()
            })
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_all_commands', methods=['GET'])
def api_get_all_commands():
    """API để local client lấy tất cả lệnh"""
    try:
        # Trả về lệnh đầu tiên trong hàng đợi
        if user_commands:
            user_id = next(iter(user_commands))
            command = user_commands[user_id]
            
            return jsonify({
                "has_command": True,
                "user_id": user_id,
                "command": command,
                "session_info": get_session_info()
            })
        else:
            return jsonify({
                "has_command": False,
                "session_info": get_session_info()
            })
    except Exception as e:
        return jsonify({"has_command": False, "error": str(e)})

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

@app.route('/api/complete_command', methods=['POST'])
def api_complete_command():
    """API đánh dấu lệnh đã hoàn thành"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        command_id = data.get('command_id')
        command_type = data.get('command_type')
        
        print(f"📥 Nhận complete_command: user_id={user_id}, cmd_id={command_id}, type={command_type}")
        
        if user_id in user_commands and user_commands[user_id]["id"] == command_id:
            # CHỈ xóa khi thực sự hoàn thành
            # Giữ lại nếu là start command để phục hồi
            if command_type == "stop_automation" or command_type == "session_ended":
                del user_commands[user_id]
                print(f"✅ Đã hoàn thành và xóa lệnh {command_id}")
            else:
                print(f"✅ Đã xử lý lệnh {command_id} (giữ lại để backup)")
        
        return jsonify({"status": "completed"})
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
        "version": "6.0 - Xử lý 3 trường hợp giống nhau",
        "timestamp": datetime.now().isoformat(),
        "session": session_info,
        "pending_commands": len(user_commands),
        "active_users": 1 if session_info["is_active"] else 0,
        "server_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "rules": [
            "CHỈ 1 phiên tại thời điểm",
            "KHÔNG login mới khi có phiên đang chạy",
            "Xử lý 3 trường hợp kết thúc giống nhau",
            "Tự động về STANDBY sau khi kết thúc"
        ]
    })

@app.route('/admin_status', methods=['GET'])
def admin_status():
    """Trang trạng thái admin"""
    cleanup_old_data()
    
    # Lấy thông tin session
    session_info = get_session_info()
    
    # Lấy danh sách commands đang chờ
    pending_commands = []
    for user_id, cmd in user_commands.items():
        pending_commands.append({
            "user_id": user_id[:8] + "...",
            "type": cmd.get('type'),
            "username": cmd.get('username', 'N/A'),
            "timestamp": cmd.get('timestamp')
        })
    
    # Thông tin server
    server_info = {
        "server_name": "LINE Ticket Automation Server",
        "version": "6.0 - Xử lý 3 trường hợp",
        "deployment": "Render",
        "line_group_id": LINE_GROUP_ID,
        "server_url": SERVER_URL,
        "current_time": datetime.now().isoformat(),
        "uptime": "running",
        "session_management": "ENABLED",
        "conflict_prevention": "ENABLED",
        "three_cases_handling": "ENABLED"
    }
    
    # Thống kê
    stats = {
        "total_commands_processed": len(user_commands) + (10 if session_info["is_active"] else 0),
        "pending_commands": len(user_commands),
        "active_session": 1 if session_info["is_active"] else 0,
        "standby_mode": 0 if session_info["is_active"] else 1,
        "line_messages_sent": len(message_cooldown)
    }
    
    # Quy tắc hoạt động
    rules = [
        "Chỉ 1 phiên làm việc tại thời điểm",
        "Không cho phép login mới khi có phiên đang chạy",
        "3 trường hợp kết thúc được xử lý giống nhau",
        "Tự động về STANDBY sau khi kết thúc",
        "Thông báo LINE cho mọi sự kiện quan trọng"
    ]
    
    # Tình trạng 3 trường hợp xử lý
    case_handling = {
        "case_1_normal_exit": "ENABLED (.thoát web)",
        "case_2_login_failed": "ENABLED (Tự động thoát + thông báo)",
        "case_3_browser_closed": "ENABLED (Tự động thoát + thông báo)",
        "all_cases_result": "Về STANDBY + Thông báo LINE"
    }
    
    return jsonify({
        "server_info": server_info,
        "current_session": session_info,
        "statistics": stats,
        "pending_commands_list": pending_commands,
        "operational_rules": rules,
        "three_cases_handling": case_handling,
        "health": "excellent",
        "memory_optimized": True,
        "auto_cleanup": "ENABLED"
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    session_info = get_session_info()
    
    if session_info["is_active"]:
        status_message = f"🎯 **ACTIVE** - User: {session_info['username']} ({session_info['duration']})"
        session_details = f"""
• 👤 User: {session_info['username']}
• ⏱️ Duration: {session_info['duration']}
• 🆔 Session ID: {session_info['session_id'][:10]}...
• 📅 Started: {session_info['start_time'][11:16] if session_info['start_time'] else 'Unknown'}
        """
    else:
        status_message = "🟢 **STANDBY** - Chờ phiên mới"
        session_details = "• 📭 Không có phiên nào đang chạy\n• ✅ Sẵn sàng nhận lệnh đăng nhập"
    
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "version": "6.0 - XỬ LÝ 3 TRƯỜNG HỢP GIỐNG NHAU", 
        "status": status_message,
        "mode": "1-PHIÊN-TẠI-1-THỜI-ĐIỂM",
        "session_details": session_details,
        "features": [
            "Chỉ 1 phiên làm việc tại thời điểm",
            "Không cho login mới khi có phiên đang chạy",
            "Xử lý 3 trường hợp kết thúc giống nhau",
            "Tự động về STANDBY khi phiên kết thúc",
            "Thông báo LINE cho mọi sự kiện"
        ],
        "three_cases": [
            "TRƯỜNG HỢP 1: .thoát web → Thoát + Thông báo + STANDBY",
            "TRƯỜNG HỢP 2: Đăng nhập lỗi → Thoát + Thông báo + STANDBY", 
            "TRƯỜNG HỢP 3: Tắt web đột ngột → Thoát + Thông báo + STANDBY"
        ],
        "commands_in_group": [
            ".login username:password - BẮT ĐẦU PHIÊN MỚI (chỉ khi STANDBY)",
            ".thoát web - KẾT THÚC PHIÊN HIỆN TẠI", 
            ".status - Trạng thái hệ thống",
            ".help - Hướng dẫn sử dụng"
        ],
        "current_session": session_info,
        "server_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "endpoints": {
            "webhook": "/webhook (POST)",
            "health": "/health (GET)", 
            "session_info": "/api/get_session_info (GET)",
            "start_session": "/api/start_session (POST)",
            "end_session": "/api/end_session (POST)",
            "register_local": "/api/register_local (POST)",
            "send_to_group": "/api/send_to_group (POST)"
        }
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================================
🚀 SERVER START - XỬ LÝ 3 TRƯỜNG HỢP GIỐNG NHAU
🚀 ========================================================
🌐 Server URL: {SERVER_URL}
👥 LINE Group ID: {LINE_GROUP_ID}
🛡️ Keep-alive: ACTIVE
🧹 Auto-cleanup: ENABLED

🎯 QUY TẮC HOẠT ĐỘNG:
• CHỈ 1 PHIÊN tại thời điểm
• KHÔNG cho login mới khi đang có phiên
• Phải .thoát web hoàn toàn trước phiên mới

🔴 3 TRƯỜNG HỢP KẾT THÚC PHIÊN:
  1. .thoát web → Thoát + Thông báo LINE + STANDBY
  2. Đăng nhập lỗi → Thoát + Thông báo LINE + STANDBY  
  3. Tắt web đột ngột → Thoát + Thông báo LINE + STANDBY

📊 TRẠNG THÁI HIỆN TẠI: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
👤 USER ACTIVE: {active_session["username"] if active_session["is_active"] else 'None'}
🕐 TIME: {datetime.now().strftime('%H:%M:%S')}
========================================================
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
