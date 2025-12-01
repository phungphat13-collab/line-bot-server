# app.py (SERVER - TÁCH BIỆT 3 TRƯỜNG HỢP)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime, time as dt_time
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

# CẤU HÌNH THỜI GIAN LÀM VIỆC
WORK_START_TIME = dt_time(6, 45)    # 6h45
WORK_END_TIME = dt_time(21, 45)     # 21h45

# CÁC CA LÀM VIỆC
WORK_SHIFTS = [
    {"name": "Ca 1", "start": dt_time(7, 0), "end": dt_time(11, 0)},
    {"name": "Ca 2", "start": dt_time(11, 0), "end": dt_time(15, 0)},
    {"name": "Ca 3", "start": dt_time(15, 0), "end": dt_time(18, 30)},
    {"name": "Ca 4", "start": dt_time(18, 30), "end": dt_time(21, 30)}
]

# ==================== 📊 BIẾN TOÀN CỤC ====================
# QUẢN LÝ PHIÊN LÀM VIỆC
active_session = {
    "is_active": False,           # Có phiên đang chạy không
    "username": None,             # Username đang active
    "user_id": None,              # ID của user LINE
    "start_time": None,           # Thời gian bắt đầu phiên
    "session_id": None,           # ID phiên làm việc
    "end_reason": None,           # Lý do kết thúc
    "end_time": None,             # Thời gian kết thúc
    "last_activity": None         # Thời gian hoạt động cuối
}

# LỆNH ĐANG CHỜ XỬ LÝ
user_commands = {}

# CHỐNG SPAM MESSAGE
message_cooldown = {}

# 🔥 BIẾN MỚI: LƯU THÔNG BÁO ĐÃ GỬI
sent_notifications = set()

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
            
        # Dọn sent_notifications cũ (quá 1 giờ)
        if len(sent_notifications) > 100:
            sent_notifications.clear()
            
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
def update_session_activity():
    """Cập nhật thời gian hoạt động cuối của phiên"""
    if active_session["is_active"]:
        active_session["last_activity"] = datetime.now().isoformat()

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
        "end_time": None,
        "last_activity": datetime.now().isoformat()
    })
    
    print(f"✅ ĐÃ BẮT ĐẦU PHIÊN: {username} (ID: {session_id})")
    
    return True, f"Đã bắt đầu phiên làm việc cho {username}"

def end_current_session_with_notification(reason="normal_exit", details=""):
    """🔥 CHỈ DÙNG CHO .thoát web - Kết thúc phiên VÀ gửi thông báo LINE"""
    if not active_session["is_active"]:
        return False, "Không có phiên làm việc nào đang chạy"
    
    username = active_session["username"]
    
    print(f"📌 [WEBHOOK] Đang kết thúc phiên: {username} - Lý do: {reason}")
    
    # THÔNG BÁO LINE
    if reason == "normal_exit":
        notification = f"🚪 **{username} đã thoát web**\n📌 Hệ thống đã về STANDBY"
        send_to_group(notification)
    
    # RESET PHIÊN
    active_session.update({
        "is_active": False,
        "username": None,
        "user_id": None,
        "start_time": None,
        "session_id": None,
        "end_reason": reason,
        "end_time": datetime.now().isoformat(),
        "last_activity": None
    })
    
    # Xóa lệnh của user này nếu có
    user_id_to_delete = None
    for uid, cmd in user_commands.items():
        if cmd.get('username') == username:
            user_id_to_delete = uid
            break
    
    if user_id_to_delete:
        del user_commands[user_id_to_delete]
        print(f"🧹 Đã xóa lệnh của user: {username}")
    
    print(f"✅ [WEBHOOK] ĐÃ KẾT THÚC PHIÊN: {username}")
    
    return True, f"Đã kết thúc phiên làm việc của {username}"

def end_current_session_without_notification(reason="client_side", details=""):
    """🔥 DÙNG CHO 3 TRƯỜNG HỢP KHÁC - Chỉ reset phiên, KHÔNG gửi LINE"""
    if not active_session["is_active"]:
        return False, "Không có phiên làm việc nào đang chạy"
    
    username = active_session["username"]
    
    print(f"📌 [CLIENT] Đang kết thúc phiên: {username} - Lý do: {reason}")
    
    # 🔥 KHÔNG GỬI THÔNG BÁO LINE Ở ĐÂY
    # Client sẽ tự gửi thông báo LINE riêng
    
    # RESET PHIÊN
    active_session.update({
        "is_active": False,
        "username": None,
        "user_id": None,
        "start_time": None,
        "session_id": None,
        "end_reason": reason,
        "end_time": datetime.now().isoformat(),
        "last_activity": None
    })
    
    # Xóa lệnh của user này nếu có
    user_id_to_delete = None
    for uid, cmd in user_commands.items():
        if cmd.get('username') == username:
            user_id_to_delete = uid
            break
    
    if user_id_to_delete:
        del user_commands[user_id_to_delete]
        print(f"🧹 Đã xóa lệnh của user: {username}")
    
    print(f"✅ [CLIENT] ĐÃ KẾT THÚC PHIÊN: {username} - Client sẽ tự gửi LINE")
    
    return True, f"Đã kết thúc phiên làm việc của {username}"

def check_shift_ended():
    """Kiểm tra nếu đã hết ca làm việc - TRƯỜNG HỢP 4"""
    try:
        if not active_session["is_active"]:
            return
            
        current_time = datetime.now().time()
        
        # Kiểm tra ngoài giờ làm việc (6h45 - 21h45)
        if current_time < WORK_START_TIME or current_time > WORK_END_TIME:
            # Đã hết giờ làm việc
            print(f"⏰ Đã hết giờ làm việc, tự động kết thúc phiên")
            end_current_session_without_notification("shift_ended", "Đã hết giờ làm việc hôm nay")
            return
            
        # Kiểm tra không trong ca nào
        in_shift = False
        for shift in WORK_SHIFTS:
            if shift["start"] <= current_time <= shift["end"]:
                in_shift = True
                break
                
        if not in_shift:
            # Đã hết ca làm việc
            print(f"⏰ Đã hết ca làm việc, tự động kết thúc phiên")
            end_current_session_without_notification("shift_ended", "Đã hết ca làm việc")
            
    except Exception as e:
        print(f"Check shift error: {e}")

def get_session_info():
    """Lấy thông tin phiên hiện tại"""
    # Tự động kiểm tra hết ca
    check_shift_ended()
    
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
        "user_id": active_session["user_id"],
        "start_time": active_session["start_time"],
        "duration": duration_text,
        "session_id": active_session["session_id"],
        "last_activity": active_session["last_activity"],
        "status": "ACTIVE",
        "is_ready_for_new_session": False
    }

def get_current_shift():
    """Lấy thông tin ca làm việc hiện tại"""
    now = datetime.now().time()
    for shift in WORK_SHIFTS:
        if shift["start"] <= now <= shift["end"]:
            return shift
    return None

# ==================== 🌐 WEBHOOK LINE ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE - CHỈ XỬ LÝ .thoát web Ở ĐÂY"""
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
                
                # LỆNH LOGIN - DÙNG get_session_info() ĐỂ KIỂM TRA
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # 🔥 KIỂM TRA BẰNG get_session_info()
                        session_info = get_session_info()
                        if session_info["is_active"]:
                            current_user = session_info["username"]
                            send_line_message(target_id, 
                                f"⚠️ **{current_user} đang sử dụng tools.**\n\n"
                                f"📌 Vui lòng đợi {current_user} thoát web (.thoát web)\n"
                                f"💡 Trạng thái: CHỈ 1 PHIÊN tại thời điểm"
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
                        
                        send_line_message(target_id, f"✅ Đã nhận lệnh đăng nhập cho {username}")
                        print(f"📨 Lệnh login cho {username} từ user_id: {user_id}")
                        
                    else:
                        send_line_message(target_id, "❌ Sai cú pháp! Dùng: .login username:password")
                
                # 🔥 LỆNH THOÁT WEB - CHỈ CÓ Ở ĐÂY GỬI THÔNG BÁO LINE
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    session_info = get_session_info()
                    
                    if session_info["is_active"]:
                        current_user = session_info["username"]
                        
                        # 🔥 GỬI LỆNH STOP ĐẾN CLIENT TRƯỚC
                        active_user_id = active_session["user_id"]
                        if active_user_id:
                            command_id = f"cmd_stop_{int(time.time())}"
                            user_commands[active_user_id] = {
                                "id": command_id,
                                "type": "stop_automation", 
                                "timestamp": datetime.now().isoformat(),
                                "action": "end_session",
                                "reason": "normal_exit"
                            }
                            print(f"📤 Đã gửi lệnh stop đến client: {current_user}")
                        
                        send_line_message(target_id, f"🚪 **Đang yêu cầu {current_user} thoát web...**")
                        
                        # 🔥 ĐỢI 2 GIÂY RỒI TỰ ĐỘNG KẾT THÚC PHIÊN VÀ GỬI LINE
                        def delayed_end_session():
                            time.sleep(2)
                            # Kiểm tra lại
                            session_info_check = get_session_info()
                            if session_info_check["is_active"] and session_info_check["username"] == current_user:
                                print(f"⏰ Tự động kết thúc phiên sau timeout: {current_user}")
                                end_current_session_with_notification("normal_exit")
                        
                        threading.Thread(target=delayed_end_session, daemon=True).start()
                        
                    else:
                        send_line_message(target_id, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai', 'status']:
                    session_info = get_session_info()
                    current_shift = get_current_shift()
                    
                    if session_info["is_active"]:
                        shift_info = f"📅 **Ca hiện tại:** {current_shift['name']}" if current_shift else "📅 **Ngoài giờ làm việc**"
                        
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

👤 **User đang active:** {session_info['username']}
⏱️ **Thời gian chạy:** {session_info['duration']}
{shift_info}
🆔 **Session ID:** {session_info['session_id'][:10]}...

💡 Gõ '.thoát web' để kết thúc phiên này"""
                    else:
                        # Tìm ca tiếp theo
                        next_shift = None
                        now_time = datetime.now().time()
                        for shift in WORK_SHIFTS:
                            if now_time < shift["start"]:
                                next_shift = shift
                                break
                        
                        shift_info = f"⏳ **Ca tiếp theo:** {next_shift['name']} ({next_shift['start'].strftime('%H:%M')})" if next_shift else "🏁 **Hết ca làm việc hôm nay**"
                        
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

🟢 **Trạng thái:** STANDBY - Sẵn sàng nhận phiên mới
🎯 **Tình trạng:** Không có phiên làm việc nào đang chạy
{shift_info}

💡 Gõ '.login username:password' để bắt đầu phiên làm việc mới"""
                    
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

🔴 **4 TRƯỜNG HỢP KẾT THÚC PHIÊN:**
1. `.thoát web` → Server tự kết thúc + Thông báo LINE → STANDBY
2. **Đăng nhập lỗi** → Client tự gửi LINE + Kết thúc phiên → STANDBY
3. **Tắt web đột ngột** → Client tự gửi LINE + Kết thúc phiên → STANDBY
4. **Hết ca làm việc** → Server tự kết thúc → STANDBY (client gửi LINE)

⚠️ **TẤT CẢ ĐỀU:** Kết thúc phiên + Về STANDBY"""
                    
                    send_line_message(target_id, help_text)
            
            elif event_type == 'join':
                welcome_text = """🎉 **Bot Ticket Automation** đã tham gia nhóm!

📋 **QUY TRÌNH LÀM VIỆC:**
1️⃣ .login username:password → Bắt đầu phiên mới
2️⃣ Hệ thống làm việc → Chỉ 1 user active
3️⃣ KẾT THÚC (4 trường hợp) → Về STANDBY
4️⃣ Chờ phiên tiếp theo

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
        
        print(f"📥 Yêu cầu start_session: {username} ({user_id})")
        
        # KIỂM TRA PHIÊN ĐANG CHẠY
        session_info = get_session_info()
        if session_info["is_active"]:
            current_user = session_info["username"]
            return jsonify({
                "status": "conflict",
                "message": f"Phiên làm việc đang được sử dụng bởi {current_user}",
                "current_session": session_info
            })
        
        # BẮT ĐẦU PHIÊN MỚI
        success, message = start_new_session(username, user_id)
        if success:
            # 🔥 GỬI THÔNG BÁO LINE TỪ SERVER
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
    """🔥 API để client thông báo kết thúc phiên - KHÔNG gửi LINE"""
    try:
        data = request.get_json()
        reason = data.get('reason', 'unknown')
        error_details = data.get('error_details', '')
        
        print(f"📥 Nhận thông báo end_session từ client: reason={reason}, details={error_details}")
        
        # 🔥 CHỈ RESET PHIÊN, KHÔNG GỬI LINE
        session_info = get_session_info()
        
        if session_info["is_active"]:
            username = session_info["username"]
            print(f"📌 Client yêu cầu kết thúc phiên: {username} - Lý do: {reason}")
            
            # 🔥 SỬ DỤNG HÀM KHÔNG GỬI NOTIFICATION
            success, message = end_current_session_without_notification(reason, error_details)
            
            if success:
                return jsonify({
                    "status": "ended",
                    "message": message,
                    "reason": reason,
                    "session_ended": True,
                    "note": "Server đã reset phiên. Client tự gửi thông báo LINE."
                })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để kết thúc"
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

# ==================== 📢 API GỬI TIN NHẮN ====================

@app.route('/api/send_to_group', methods=['POST'])
def api_send_to_group():
    """🔥 API QUAN TRỌNG: Client gửi thông báo LINE sau khi kết thúc phiên"""
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

@app.route('/api/get_commands/<user_id>', methods=['GET'])
def api_get_commands(user_id):
    """API để local client lấy lệnh"""
    try:
        update_session_activity()
        
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
        
        print(f"📥 Nhận complete_command: user_id={user_id}, cmd_id={command_id}")
        
        if user_id in user_commands and user_commands[user_id]["id"] == command_id:
            del user_commands[user_id]
            print(f"✅ Đã hoàn thành và xóa lệnh {command_id}")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📊 HEALTH & MONITORING ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    cleanup_old_data()
    
    session_info = get_session_info()
    current_shift = get_current_shift()
    
    return jsonify({
        "status": "healthy",
        "server": "LINE Ticket Automation Server",
        "version": "11.0 - Tách biệt 3 trường hợp",
        "timestamp": datetime.now().isoformat(),
        "session": session_info,
        "current_shift": current_shift['name'] if current_shift else "Ngoài giờ làm",
        "pending_commands": len(user_commands),
        "handling_mode": "SEPARATED",
        "notification_flow": [
            "🔥 .thoát web → Server gửi LINE",
            "🔥 3 trường hợp khác → Client tự gửi LINE",
            "✅ Tất cả đều → Reset phiên → STANDBY"
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
        "version": "11.0 - TÁCH BIỆT THÔNG BÁO LINE", 
        "status": status_message,
        "handling_strategy": [
            "🎯 .thoát web: Server xử lý toàn bộ",
            "🎯 3 trường hợp khác: Client tự gửi LINE → Server reset",
            "✅ Đảm bảo status luôn đúng sau khi kết thúc"
        ],
        "api_for_client": [
            "📤 /api/end_session - Reset phiên (không gửi LINE)",
            "📨 /api/send_to_group - Client gửi thông báo LINE",
            "📊 /api/get_session_info - Kiểm tra trạng thái"
        ]
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================================
🚀 SERVER START - TÁCH BIỆT 3 TRƯỜNG HỢP
🚀 ========================================================
🌐 Server URL: {SERVER_URL}
👥 LINE Group ID: {LINE_GROUP_ID}
🛡️ Keep-alive: ACTIVE
🧹 Auto-cleanup: ENABLED
🔄 Auto-shift-check: ENABLED

🎯 QUY TẮC HOẠT ĐỘNG:
• CHỈ 1 PHIÊN tại thời điểm
• KHÔNG cho login mới khi có phiên đang chạy

🔴 4 TRƯỜNG HỢP KẾT THÚC (TÁCH BIỆT):
  1. .thoát web → Server tự kết thúc + Gửi LINE → STANDBY
  2. Đăng nhập lỗi → Client gửi LINE → Server reset → STANDBY  
  3. Tắt web đột ngột → Client gửi LINE → Server reset → STANDBY
  4. Hết ca làm việc → Server tự reset → Client gửi LINE → STANDBY

📊 TRẠNG THÁI HIỆN TẠI: {get_session_info()['status']}
👤 USER ACTIVE: {get_session_info()['username'] if get_session_info()['is_active'] else 'None'}
🕐 TIME: {datetime.now().strftime('%H:%M:%S')}
========================================================
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
