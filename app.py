# app.py (SERVER - đã thêm session management)
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

# Giảm thời gian lưu session
SESSION_TIMEOUT = 3600  # 1 giờ

LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"

# Dùng dict đơn giản, tự động dọn dẹp
user_sessions = {}
user_commands = {}
message_cooldown = {}
pending_confirmations = {}  # Lưu trạng thái chờ xác nhận từ admin
admin_responses = {}        # Lưu phản hồi từ admin
active_sessions = {}        # Lưu session đang active

# ==================== 🧹 MEMORY CLEANUP ====================
def cleanup_old_sessions():
    """Dọn dẹp session cũ để tiết kiệm memory"""
    try:
        current_time = time.time()
        expired_users = []
        
        for user_id, session in user_sessions.items():
            last_activity = session.get('last_activity', 0)
            if current_time - last_activity > SESSION_TIMEOUT:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            if user_id in user_sessions:
                del user_sessions[user_id]
            if user_id in user_commands:
                del user_commands[user_id]
            if user_id in pending_confirmations:
                del pending_confirmations[user_id]
            if user_id in admin_responses:
                del admin_responses[user_id]
            if user_id in active_sessions:
                del active_sessions[user_id]
                
        # Dọn cooldown cũ
        current_time = time.time()
        expired_cooldowns = [k for k, v in message_cooldown.items() if current_time - v > 300]
        for key in expired_cooldowns:
            del message_cooldown[key]
            
        # Dọn confirmations cũ (quá 30 phút)
        expired_confirmations = [k for k, v in pending_confirmations.items() 
                               if current_time - v.get('timestamp', 0) > 1800]
        for user_id in expired_confirmations:
            del pending_confirmations[user_id]
            
        # Dọn active sessions cũ (quá 2 giờ)
        expired_active = [k for k, v in active_sessions.items() 
                         if current_time - v.get('last_activity', 0) > 7200]
        for user_id in expired_active:
            del active_sessions[user_id]
            
        if expired_users:
            print(f"🧹 Cleaned up {len(expired_users)} expired sessions")
            
    except Exception as e:
        print(f"Cleanup error: {e}")

# ==================== 🛡️ CHỐNG SLEEP TỐI ƯU ====================
def optimized_keep_alive():
    """Keep-alive tối ưu memory"""
    time.sleep(15)  # Chờ server ổn định
    
    while True:
        try:
            # Gọi health với timeout ngắn
            requests.get(f"{SERVER_URL}/health", timeout=2)
            print(f"✅ Keep-alive at {datetime.now().strftime('%H:%M')}")
            
            # Dọn dẹp memory sau mỗi lần ping
            cleanup_old_sessions()
            gc.collect()
            
        except Exception as e:
            print(f"⚠️ Keep-alive: {e}")
        
        time.sleep(300)  # 5 phút

# Khởi chạy keep-alive
keep_alive_thread = threading.Thread(target=optimized_keep_alive, daemon=True)
keep_alive_thread.start()
print("🛡️ Optimized keep-alive started")

# ==================== 🛠️ HÀM TIỆN ÍCH TỐI ƯU ====================
def send_line_message(chat_id, text, chat_type="user"):
    """Gửi tin nhắn LINE - TỐI ƯU MEMORY"""
    try:
        # Cập nhật last activity
        if chat_id in user_sessions:
            user_sessions[chat_id]['last_activity'] = time.time()
        
        # Kiểm tra cooldown
        key = f"{chat_id}_{hash(text) % 10000}"  # Dùng hash để tiết kiệm memory
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

def send_confirmation_message(admin_id, shift_name, message, options):
    """Gửi tin nhắn xác nhận thoát cho admin"""
    try:
        option_text = "\n".join([f"• {opt}" for opt in options])
        full_message = f"🔔 [XÁC NHẬN THOÁT]\n\n{message}\n\nLựa chọn:\n{option_text}"
        
        if send_line_message(admin_id, full_message):
            # Lưu trạng thái đang chờ xác nhận
            pending_confirmations[admin_id] = {
                'shift_name': shift_name,
                'message': message,
                'timestamp': time.time(),
                'options': options
            }
            return True
        return False
    except Exception as e:
        logger.error(f"Send confirmation error: {e}")
        return False

def get_active_session_info():
    """Lấy thông tin session đang active"""
    if active_sessions:
        # Lấy session đầu tiên (chỉ cho phép 1 session active)
        user_id = next(iter(active_sessions))
        session = active_sessions[user_id]
        return {
            'has_active_session': True,
            'active_user': session.get('username', 'Unknown'),
            'user_type': session.get('user_type', 'user'),
            'start_time': session.get('start_time'),
            'user_id': user_id
        }
    else:
        return {'has_active_session': False}

# ==================== 🌐 API ENDPOINTS TỐI ƯU ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE - TỐI ƯU"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            user_id = source.get('userId')
            
            if not user_id:
                continue
                
            # Cập nhật thời gian hoạt động
            if user_id in user_sessions:
                user_sessions[user_id]['last_activity'] = time.time()
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip().lower()
                
                # XỬ LÝ PHẢN HỒI XÁC NHẬN TỪ ADMIN
                if user_id in pending_confirmations:
                    if message_text in ['.ok', '.khong']:
                        # Lưu phản hồi từ admin
                        admin_responses[user_id] = message_text
                        del pending_confirmations[user_id]
                        
                        if message_text == '.ok':
                            send_line_message(user_id, "✅ Đã xác nhận thoát. Hệ thống sẽ tự động đóng web.")
                        else:
                            send_line_message(user_id, "🔄 Tiếp tục sử dụng. Hệ thống sẽ hỏi lại sau 1 giờ.")
                        
                        continue  # Không xử lý tiếp
                
                # XỬ LÝ LỆNH THÔNG THƯỜNG
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # KIỂM TRA SESSION CONFLICT
                        active_session = get_active_session_info()
                        if active_session['has_active_session']:
                            active_user = active_session['active_user']
                            active_user_type = active_session['user_type']
                            current_user_type = "admin" if username in ["27838", "167802"] else "user"
                            
                            # Rule 1: User thường đang dùng -> báo "username đang sử dụng tools"
                            if active_user_type == "user":
                                send_line_message(user_id, f"⚠️ {active_user} đang sử dụng tools")
                                continue
                            
                            # Rule 2: Admin đang dùng, user thường muốn dùng -> báo "username muốn xài tool"
                            elif active_user_type == "admin" and current_user_type == "user":
                                send_line_message(user_id, f"⚠️ {username} muốn xài tool")
                                # Gửi thông báo cho admin đang dùng
                                for admin_id, session in active_sessions.items():
                                    if session.get('user_type') == 'admin':
                                        send_line_message(admin_id, f"⚠️ {username} muốn xài tool")
                                continue
                            
                            # Rule 3: Admin đang dùng, admin khác muốn dùng -> báo "admin username đang sử dụng tool"
                            elif active_user_type == "admin" and current_user_type == "admin":
                                send_line_message(user_id, f"⚠️ Admin {active_user} đang sử dụng tool")
                                continue
                        
                        user_sessions[user_id] = {
                            'username': username,
                            'password': password,
                            'status': 'waiting_command',
                            'last_activity': time.time(),
                            'user_type': "admin" if username in ["27838", "167802"] else "user"
                        }
                        
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id] = {
                            "id": command_id,
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        send_line_message(user_id, f"✅ Đã nhận lệnh cho {username}")
                        logger.info(f"📨 Sent command to {user_id}")
                        
                    else:
                        send_line_message(user_id, "❌ Sai cú pháp! Dùng: .login username:password")
                
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    if user_id in user_sessions:
                        username = user_sessions[user_id].get('username', 'user')
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id] = {
                            "id": command_id,
                            "type": "stop_automation", 
                            "timestamp": datetime.now().isoformat()
                        }
                        # Xóa active session khi thoát
                        if user_id in active_sessions:
                            del active_sessions[user_id]
                        send_line_message(user_id, f"🚪 {username} đã thoát web")
                    else:
                        send_line_message(user_id, "❌ Không có automation nào đang chạy")
                
                elif message_text in ['.status', '.trangthai', 'status']:
                    if user_id in user_sessions:
                        username = user_sessions[user_id].get('username', 'N/A')
                        status = user_sessions[user_id].get('status', 'unknown')
                        
                        # Kiểm tra active session
                        active_session = get_active_session_info()
                        if active_session['has_active_session']:
                            session_info = f"\n🎯 Active: {active_session['active_user']} ({active_session['user_type']})"
                        else:
                            session_info = "\n🎯 No active session"
                        
                        # Kiểm tra nếu có pending confirmation
                        confirmation_status = ""
                        if user_id in pending_confirmations:
                            confirmation_status = " ⏳ Đang chờ xác nhận thoát"
                        elif user_id in admin_responses:
                            response = admin_responses[user_id]
                            confirmation_status = f" ✅ Đã phản hồi: {response}"
                        
                        send_line_message(user_id, f"📊 {username}: {status}{confirmation_status}{session_info}")
                    else:
                        send_line_message(user_id, "📊 Chưa đăng nhập")
                
                elif message_text in ['.help', 'help', 'hướng dẫn', '.huongdan']:
                    help_text = """🤖 TICKET AUTOMATION

📋 LỆNH:
.login username:password - Đăng nhập
.thoát web - Dừng automation  
.status - Trạng thái
.help - Hướng dẫn

🔔 XÁC NHẬN ADMIN:
.ok - Đồng ý thoát
.khong - Tiếp tục sử dụng

🎯 SESSION RULES:
• Chỉ 1 user được active
• User thường: báo "đang sử dụng tools"
• User muốn dùng khi admin active: báo "muốn xài tool"
• Admin khác: báo "admin đang sử dụng tool""""
                    send_line_message(user_id, help_text)
                
                elif message_text in ['.ok', '.khong']:
                    # Nếu không có pending confirmation, thông báo lỗi
                    if user_id not in pending_confirmations:
                        send_line_message(user_id, "❌ Không có yêu cầu xác nhận nào đang chờ")
            
            elif event_type == 'join':
                send_line_message(user_id, "🎉 Bot Ticket Automation - .help để xem lệnh")
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🔔 API XÁC NHẬN ADMIN ====================

@app.route('/api/send_confirmation', methods=['POST'])
def api_send_confirmation():
    """API gửi tin nhắn xác nhận thoát cho admin"""
    try:
        data = request.get_json()
        admin_id = data.get('admin_id')
        shift_name = data.get('shift_name')
        message = data.get('message')
        options = data.get('options', ['.ok', '.khong'])
        
        if not all([admin_id, shift_name, message]):
            return jsonify({"status": "error", "message": "Thiếu tham số"})
        
        if send_confirmation_message(admin_id, shift_name, message, options):
            return jsonify({
                "status": "success", 
                "message": "Đã gửi xác nhận"
            })
        else:
            return jsonify({
                "status": "error", 
                "message": "Không thể gửi tin nhắn"
            })
            
    except Exception as e:
        logger.error(f"Send confirmation API error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_admin_response/<admin_id>', methods=['GET'])
def api_get_admin_response(admin_id):
    """API kiểm tra phản hồi từ admin"""
    try:
        if admin_id in admin_responses:
            response = admin_responses[admin_id]
            # Xóa phản hồi sau khi lấy
            del admin_responses[admin_id]
            
            return jsonify({
                "has_response": True,
                "response": response
            })
        else:
            return jsonify({"has_response": False})
            
    except Exception as e:
        logger.error(f"Get admin response error: {e}")
        return jsonify({"has_response": False, "error": str(e)})

# ==================== 🎯 API QUẢN LÝ SESSION ====================

@app.route('/api/register_session', methods=['POST'])
def api_register_session():
    """API đăng ký session mới"""
    try:
        data = request.get_json()
        username = data.get('username')
        is_admin = data.get('is_admin', False)
        user_id = data.get('user_id')
        
        if not username or not user_id:
            return jsonify({"status": "error", "message": "Thiếu tham số"})
        
        # Kiểm tra nếu đã có session active
        if active_sessions:
            active_session = get_active_session_info()
            return jsonify({
                "status": "conflict",
                "message": "Đã có session active",
                "active_session": active_session
            })
        
        # Đăng ký session mới
        active_sessions[user_id] = {
            'username': username,
            'user_type': 'admin' if is_admin else 'user',
            'start_time': datetime.now().isoformat(),
            'last_activity': time.time()
        }
        
        logger.info(f"🎯 Registered session for {username} ({'admin' if is_admin else 'user'})")
        
        return jsonify({
            "status": "registered",
            "message": "Đăng ký session thành công"
        })
        
    except Exception as e:
        logger.error(f"Register session error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_session_status', methods=['GET'])
def api_get_session_status():
    """API lấy trạng thái session"""
    try:
        return jsonify(get_active_session_info())
    except Exception as e:
        return jsonify({"has_active_session": False, "error": str(e)})

@app.route('/api/clear_session/<user_id>', methods=['POST'])
def api_clear_session(user_id):
    """API xóa session"""
    try:
        if user_id in active_sessions:
            username = active_sessions[user_id].get('username', 'Unknown')
            del active_sessions[user_id]
            logger.info(f"🗑️ Cleared session for {username}")
            return jsonify({"status": "cleared", "message": f"Đã xóa session của {username}"})
        else:
            return jsonify({"status": "not_found", "message": "Không tìm thấy session"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🔧 API LOCAL CLIENT ====================

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
                user_sessions[user_id]['last_activity'] = time.time()
            
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
        
        if user_id in user_commands and user_commands[user_id]["id"] == command_id:
            del user_commands[user_id]
            logger.info(f"✅ Completed command {command_id} for {user_id}")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

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
            user_sessions[user_id]['last_activity'] = time.time()
            
            return jsonify({"status": "connected", "message": "Kết nối thành công"})
        else:
            return jsonify({"status": "error", "message": "User không tồn tại"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

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

# ==================== 📊 HEALTH & MONITORING ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint tối ưu"""
    cleanup_old_sessions()  # Dọn dẹp khi có request
    
    active_users = len([u for u in user_sessions.values() if u.get('status') == 'connected'])
    pending_commands = len(user_commands)
    pending_confirmations_count = len(pending_confirmations)
    active_sessions_count = len(active_sessions)
    
    return jsonify({
        "status": "healthy",
        "memory_optimized": True,
        "active_users": active_users,
        "pending_commands": pending_commands,
        "pending_confirmations": pending_confirmations_count,
        "active_sessions": active_sessions_count,
        "total_sessions": len(user_sessions),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/admin_status', methods=['GET'])
def admin_status():
    """Trang trạng thái admin"""
    cleanup_old_sessions()
    
    status_info = {
        "server": "LINE Ticket Automation Server",
        "version": "2.2 - Session Management",
        "admin_features": "ENABLED",
        "session_management": "ENABLED",
        "timestamp": datetime.now().isoformat(),
        "statistics": {
            "total_sessions": len(user_sessions),
            "active_commands": len(user_commands),
            "pending_confirmations": len(pending_confirmations),
            "waiting_responses": len(admin_responses),
            "active_sessions": len(active_sessions)
        },
        "active_users": [],
        "active_sessions_list": [],
        "pending_confirmations_list": []
    }
    
    # Thông tin user đang hoạt động
    for user_id, session in user_sessions.items():
        if session.get('status') == 'connected':
            status_info["active_users"].append({
                "user_id": user_id[:8] + "...",
                "username": session.get('username', 'N/A'),
                "user_type": session.get('user_type', 'user'),
                "last_activity": session.get('last_activity', 0),
                "client_ip": session.get('client_ip', 'N/A')
            })
    
    # Thông tin session đang active
    for user_id, session in active_sessions.items():
        status_info["active_sessions_list"].append({
            "user_id": user_id[:8] + "...",
            "username": session.get('username', 'N/A'),
            "user_type": session.get('user_type', 'user'),
            "start_time": session.get('start_time'),
            "last_activity": session.get('last_activity', 0)
        })
    
    # Thông tin xác nhận đang chờ
    for admin_id, confirmation in pending_confirmations.items():
        status_info["pending_confirmations_list"].append({
            "admin_id": admin_id[:8] + "...",
            "shift_name": confirmation.get('shift_name', 'N/A'),
            "timestamp": confirmation.get('timestamp', 0),
            "message_preview": confirmation.get('message', '')[:50] + "..."
        })
    
    return jsonify(status_info)

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "version": "2.2 - Session Management", 
        "status": "running",
        "features": [
            "Auto ticket processing",
            "Shift management", 
            "Admin confirmation system",
            "Session management",
            "Memory optimized",
            "Never sleep on Render"
        ],
        "session_rules": [
            "Chỉ 1 user được active tại thời điểm",
            "User thường -> báo 'đang sử dụng tools'", 
            "User muốn dùng khi admin active -> báo 'muốn xài tool'",
            "Admin khác -> báo 'admin đang sử dụng tool'"
        ],
        "endpoints": {
            "webhook": "/webhook",
            "health": "/health", 
            "admin_status": "/admin_status",
            "session_status": "/api/get_session_status",
            "register_session": "/api/register_session"
        }
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    print(f"🚀 Starting Optimized Server on port {port}")
    print(f"🌐 Server URL: {SERVER_URL}")
    print(f"🛡️ Memory-optimized keep-alive: ACTIVE")
    print(f"🔔 Admin Confirmation System: ENABLED")
    print(f"🎯 Session Management: ENABLED")
    print(f"🧹 Auto-cleanup: ENABLED")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
