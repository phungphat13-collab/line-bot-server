# app.py (SERVER - PHIÊN LÀM VIỆC RIÊNG BIỆT)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import time
import threading
import gc

# ==================== 🔧 CẤU HÌNH TỐI ƯU ====================
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"

# ID nhóm LINE để nhận thông báo
LINE_GROUP_ID = "ZpXWbVLYaj"  # ID từ link group

# Các phiên làm việc
active_session = {
    "is_active": False,          # Có phiên đang chạy không
    "username": None,            # Username đang active
    "user_id": None,             # ID của user LINE
    "start_time": None,          # Thời gian bắt đầu phiên
    "session_id": None           # ID phiên làm việc
}

user_commands = {}               # Lệnh đang chờ xử lý
message_cooldown = {}            # Chống spam

# ==================== 🧹 MEMORY CLEANUP ====================
def cleanup_old_data():
    """Dọn dẹp dữ liệu cũ"""
    try:
        current_time = time.time()
        
        # Xóa cooldown cũ (5 phút)
        expired_cooldowns = [k for k, v in message_cooldown.items() 
                           if current_time - v > 300]
        for key in expired_cooldowns:
            del message_cooldown[key]
            
        # Xóa commands trống
        empty_commands = [k for k in user_commands if not user_commands[k]]
        for key in empty_commands:
            del user_commands[key]
            
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

# ==================== 🛠️ HÀM TIỆN ÍCH ====================
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
        "start_time": active_session["start_time"],
        "duration": duration_text,
        "session_id": active_session["session_id"]
    }

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
        "session_id": session_id
    })
    
    return True, f"Đã bắt đầu phiên làm việc cho {username}"

def end_current_session():
    """Kết thúc phiên làm việc hiện tại"""
    if not active_session["is_active"]:
        return False, "Không có phiên làm việc nào đang chạy"
    
    username = active_session["username"]
    
    # Reset về trạng thái standby
    active_session.update({
        "is_active": False,
        "username": None,
        "user_id": None,
        "start_time": None,
        "session_id": None
    })
    
    return True, f"Đã kết thúc phiên làm việc của {username}"

def force_end_session():
    """Buộc kết thúc phiên (khi có lỗi)"""
    if active_session["is_active"]:
        username = active_session["username"]
        end_current_session()
        return True, f"Đã buộc kết thúc phiên của {username}"
    return False, "Không có phiên nào để buộc kết thúc"

# ==================== 🌐 API ENDPOINTS ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE - LOGIC MỚI"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            user_id = source.get('userId')
            group_id = source.get('groupId')
            
            # Chỉ xử lý trong nhóm
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
                        
                        # 🔥 QUY TẮC MỚI: KHÔNG cho phép login mới trong cùng phiên
                        if active_session["is_active"]:
                            current_user = active_session["username"]
                            send_line_message(target_id, 
                                f"⚠️ {current_user} đang sử dụng tools.\n" +
                                f"📌 Vui lòng đợi {current_user} thoát web (.thoát web) " +
                                f"trước rồi mới bắt đầu phiên mới."
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
                            "session_required": True  # Yêu cầu bắt đầu phiên mới
                        }
                        
                        send_line_message(target_id, f"✅ Đã nhận lệnh đăng nhập cho {username}")
                        print(f"📨 Lệnh login cho {username} từ user_id: {user_id}")
                        
                    else:
                        send_line_message(target_id, "❌ Sai cú pháp! Dùng: .login username:password")
                
                # LỆNH THOÁT WEB
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    if active_session["is_active"]:
                        current_user = active_session["username"]
                        
                        # Gửi lệnh stop đến client
                        if current_user:
                            command_id = f"cmd_{int(time.time())}"
                            user_commands[user_id] = {
                                "id": command_id,
                                "type": "stop_automation", 
                                "timestamp": datetime.now().isoformat(),
                                "action": "end_session"  # Đánh dấu kết thúc phiên
                            }
                        
                        send_line_message(target_id, 
                            f"🚪 Đang yêu cầu {current_user} thoát web...\n" +
                            f"📌 Sau khi thoát, hệ thống sẽ về trạng thái standby."
                        )
                    else:
                        send_line_message(target_id, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai', 'status']:
                    session_info = get_session_info()
                    
                    if session_info["is_active"]:
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

👤 **User đang active:** {session_info['username']}
⏱️ **Thời gian chạy:** {session_info['duration']}
🆔 **Session ID:** {session_info['session_id'][:10]}...
📅 **Bắt đầu lúc:** {session_info['start_time'][11:16] if session_info['start_time'] else 'Unknown'}

💡 *Gõ '.thoát web' để kết thúc phiên này*"""
                    else:
                        status_text = """📊 **TRẠNG THÁI HỆ THỐNG**

🟢 **Trạng thái:** STANDBY - Sẵn sàng nhận phiên mới
🎯 **Tình trạng:** Không có phiên làm việc nào đang chạy

💡 *Gõ '.login username:password' để bắt đầu phiên làm việc mới*"""
                    
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
• Mỗi phiên độc lập từ login đến thoát

⚠️ **LƯU Ý QUAN TRỌNG:**
• Không thể login khi có phiên khác đang chạy
• Hệ thống tự động gửi thông báo khi phiên bắt đầu/kết thúc
• Thông báo sẽ hiển thị user đang sử dụng"""
                    
                    send_line_message(target_id, help_text)
            
            # KHI BOT THAM GIA NHÓM
            elif event_type == 'join':
                welcome_text = """🎉 **Bot Ticket Automation** đã tham gia nhóm!

📋 **Quy trình làm việc:**
1️⃣ .login username:password → Bắt đầu phiên mới
2️⃣ Hệ thống làm việc → Chỉ 1 user active
3️⃣ .thoát web → Kết thúc phiên hiện tại
4️⃣ STANDBY → Chờ phiên tiếp theo

💡 **Lưu ý:** Không cho phép login mới khi có phiên đang chạy!"""
                send_line_message(target_id, welcome_text)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🎯 API QUẢN LÝ SESSION ====================

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên làm việc mới"""
    try:
        data = request.get_json()
        username = data.get('username')
        user_id = data.get('user_id')
        
        if not username or not user_id:
            return jsonify({"status": "error", "message": "Thiếu tham số"})
        
        # Kiểm tra xem đã có phiên nào đang chạy chưa
        if active_session["is_active"]:
            return jsonify({
                "status": "conflict",
                "message": f"Phiên làm việc đang được sử dụng bởi {active_session['username']}",
                "current_session": get_session_info()
            })
        
        # Bắt đầu phiên mới
        success, message = start_new_session(username, user_id)
        if success:
            # Gửi thông báo đến nhóm
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
    """API kết thúc phiên làm việc"""
    try:
        data = request.get_json()
        username = data.get('username')
        user_id = data.get('user_id')
        
        # Kiểm tra quyền (chỉ user đang active hoặc bất kỳ ai khi force)
        if active_session["is_active"]:
            # Có thể là user đang active hoặc LINE user yêu cầu thoát
            session_user = active_session["username"]
            
            if username and username != session_user:
                return jsonify({
                    "status": "unauthorized",
                    "message": f"Không thể kết thúc phiên của user khác. {session_user} đang active."
                })
            
            # Kết thúc phiên
            success, message = end_current_session()
            if success:
                # Gửi thông báo đến nhóm
                send_to_group(f"🏁 **KẾT THÚC PHIÊN**\n👤 User: {session_user}")
                
                return jsonify({
                    "status": "ended",
                    "message": message,
                    "session_ended": True
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
        return jsonify(get_session_info())
    except Exception as e:
        return jsonify({"is_active": False, "error": str(e)})

@app.route('/api/force_end_session', methods=['POST'])
def api_force_end_session():
    """API buộc kết thúc phiên (khi browser đóng đột ngột)"""
    try:
        if active_session["is_active"]:
            username = active_session["username"]
            success, message = force_end_session()
            
            if success:
                # Gửi thông báo đến nhóm
                send_to_group(f"🚨 **PHIÊN BỊ ĐÓNG ĐỘT NGỘT**\n👤 User: {username}\n📌 Hệ thống đã về STANDBY")
                
                return jsonify({
                    "status": "force_ended",
                    "message": message,
                    "session_ended": True
                })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để buộc kết thúc"
        })
        
    except Exception as e:
        logger.error(f"Force end session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📢 API GỬI TIN NHẮN ====================

@app.route('/api/send_to_group', methods=['POST'])
def api_send_to_group():
    """API gửi tin nhắn đến nhóm LINE"""
    try:
        data = request.get_json()
        message = data.get('message')
        
        if message:
            success = send_to_group(message)
            return jsonify({"status": "sent" if success else "error"})
        return jsonify({"status": "error", "message": "Thiếu nội dung"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🔧 API LOCAL CLIENT ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API local client đăng ký"""
    try:
        data = request.get_json()
        client_ip = request.remote_addr
        
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
    """API lấy lệnh cho user"""
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
        
        if user_id in user_commands and user_commands[user_id]["id"] == command_id:
            # Giữ lại lệnh nếu là start để tránh bị mất
            # Chỉ xóa khi thực sự hoàn thành phiên
            if command_type == "session_ended":
                del user_commands[user_id]
                print(f"✅ Đã hoàn thành và xóa lệnh {command_id}")
            else:
                print(f"✅ Đã xử lý lệnh {command_id} (vẫn giữ để backup)")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📊 HEALTH & MONITORING ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    cleanup_old_data()
    
    return jsonify({
        "status": "healthy",
        "server_mode": "PHIÊN LÀM VIỆC RIÊNG BIỆT",
        "session": get_session_info(),
        "pending_commands": len(user_commands),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/admin_status', methods=['GET'])
def admin_status():
    """Trạng thái admin"""
    return jsonify({
        "server": "LINE Ticket Automation - PHIÊN LÀM VIỆC RIÊNG BIỆT",
        "timestamp": datetime.now().isoformat(),
        "active_session": get_session_info(),
        "user_commands_count": len(user_commands),
        "rules": [
            "Mỗi phiên độc lập từ .login đến .thoát web",
            "KHÔNG cho phép login mới khi có phiên đang chạy",
            "Chỉ 1 phiên làm việc tại thời điểm",
            "Phải thoát web hoàn toàn trước khi bắt đầu phiên mới"
        ]
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    session_info = get_session_info()
    
    if session_info["is_active"]:
        status_message = f"ACTIVE - User: {session_info['username']} ({session_info['duration']})"
    else:
        status_message = "STANDBY - Chờ phiên mới"
    
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "version": "5.0 - PHIÊN LÀM VIỆC RIÊNG BIỆT", 
        "status": status_message,
        "mode": "1-PHIÊN-TẠI-1-THỜI-ĐIỂM",
        "features": [
            "Chỉ 1 phiên làm việc tại thời điểm",
            "Không cho login mới khi có phiên đang chạy",
            "Thông báo user đang sử dụng khi có login mới",
            "Tự động reset về STANDBY khi phiên kết thúc"
        ],
        "commands_in_group": [
            ".login username:password - BẮT ĐẦU PHIÊN MỚI (chỉ khi STANDBY)",
            ".thoát web - KẾT THÚC PHIÊN HIỆN TẠI", 
            ".status - Trạng thái hệ thống",
            ".help - Hướng dẫn"
        ],
        "current_session": session_info
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    print(f"""
🚀 ========================================
🚀 SERVER START - PHIÊN LÀM VIỆC RIÊNG BIỆT
🚀 ========================================
🌐 Server: {SERVER_URL}
👥 LINE Group: {LINE_GROUP_ID}
🛡️ Keep-alive: ACTIVE

🎯 QUY TẮC HOẠT ĐỘNG:
• CHỈ 1 PHIÊN tại thời điểm
• KHÔNG cho login mới khi đang có phiên
• Phải .thoát web hoàn toàn trước phiên mới
• Tự động về STANDBY sau mỗi phiên

📊 Hiện tại: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
