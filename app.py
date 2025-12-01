# app.py (SERVER - CHỈ HOẠT ĐỘNG TRONG NHÓM - ĐÃ LOẠI BỎ PHÂN QUYỀN)
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

# ID nhóm LINE để nhận thông báo
LINE_GROUP_ID = "ZpXWbVLYaj"  # ID từ link group

# Dùng dict đơn giản, tự động dọn dẹp
user_sessions = {}
user_commands = {}
message_cooldown = {}
active_sessions = {}        # Lưu session đang active - CHỈ 1 SESSION TẠI THỜI ĐIỂM
session_cleanup_times = {}  # Thời gian cleanup session

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
                username = user_sessions[user_id].get('username', 'Unknown')
                del user_sessions[user_id]
                # THÔNG BÁO KHI SESSION HẾT HẠN
                send_to_group(f"⏰ Session của {username} đã hết hạn (quá 1 giờ không hoạt động)")
                
            if user_id in user_commands:
                del user_commands[user_id]
            if user_id in active_sessions:
                del active_sessions[user_id]
                
        # Dọn cooldown cũ
        expired_cooldowns = [k for k, v in message_cooldown.items() if current_time - v > 300]
        for key in expired_cooldowns:
            del message_cooldown[key]
            
        # Dọn active sessions cũ (quá 2 giờ)
        expired_active = [k for k, v in active_sessions.items() 
                         if current_time - v.get('last_activity', 0) > 7200]
        for user_id in expired_active:
            username = active_sessions[user_id].get('username', 'Unknown')
            del active_sessions[user_id]
            send_to_group(f"🕒 Session của {username} đã bị xóa do quá 2 giờ không hoạt động")
            
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
    """Gửi tin nhắn LINE - HỖ TRỢ CẢ USER VÀ NHÓM"""
    try:
        # Cập nhật last activity nếu là user
        if chat_type == "user" and chat_id in user_sessions:
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

def send_to_group(text):
    """Gửi tin nhắn đến nhóm LINE"""
    try:
        if LINE_GROUP_ID:
            return send_line_message(LINE_GROUP_ID, text, "group")
        else:
            print("⚠️ Chưa cấu hình LINE_GROUP_ID - Chỉ gửi tin nhắn cá nhân")
            return False
    except Exception as e:
        logger.error(f"Send to group error: {e}")
        return False

def get_active_session_info():
    """Lấy thông tin session đang active"""
    try:
        if active_sessions:
            # Lấy session đầu tiên (chỉ cho phép 1 session active)
            user_id = next(iter(active_sessions))
            session = active_sessions[user_id]
            start_time = session.get('start_time')
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
                
            return {
                'has_active_session': True,
                'active_user': session.get('username', 'Unknown'),
                'user_id': user_id,
                'start_time': start_time,
                'duration': duration_text,
                'last_activity': session.get('last_activity', time.time())
            }
        else:
            return {'has_active_session': False}
    except Exception as e:
        logger.error(f"Get active session error: {e}")
        return {'has_active_session': False}

def check_session_conflict(username):
    """Kiểm tra xem username có đang được sử dụng không"""
    active_session = get_active_session_info()
    if active_session['has_active_session']:
        return active_session['active_user'] != username
    return False

def force_end_session(user_id):
    """Buộc kết thúc session (khi browser đóng đột ngột)"""
    try:
        if user_id in active_sessions:
            username = active_sessions[user_id].get('username', 'Unknown')
            del active_sessions[user_id]
            
            # Xóa cả user_commands nếu có
            if user_id in user_commands:
                del user_commands[user_id]
                
            send_to_group(f"🚨 Session của {username} đã bị đóng đột ngột. Hệ thống sẵn sàng cho phiên mới.")
            logger.info(f"🚨 Force ended session for {username}")
            return True
        return False
    except Exception as e:
        logger.error(f"Force end session error: {e}")
        return False

# ==================== 🌐 API ENDPOINTS TỐI ƯU ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE - CHỈ HOẠT ĐỘNG TRONG NHÓM - ĐÃ SỬA ĐỂ KIỂM TRA CONFLICT"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            user_id = source.get('userId')
            group_id = source.get('groupId')
            
            # Xác định đây là tin nhắn từ nhóm hay cá nhân
            is_group_message = group_id is not None
            
            # CHỈ XỬ LÝ TIN NHẮN TRONG NHÓM
            if not is_group_message:
                continue
                
            target_id = group_id  # Luôn gửi về nhóm
            
            if not target_id:
                continue
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                
                # XỬ LÝ LỆNH TRONG NHÓM - TẤT CẢ LỆNH ĐỀU HOẠT ĐỘNG
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        # 🔥 **KIỂM TRA SESSION CONFLICT - CHỈ 1 USER ĐƯỢC ACTIVE**
                        active_session = get_active_session_info()
                        if active_session['has_active_session']:
                            active_user = active_session['active_user']
                            
                            # RULE: Chỉ chặn khi có user KHÁC đang active
                            if active_user != username:
                                send_line_message(target_id, f"⚠️ {active_user} đang sử dụng tools. Vui lòng chờ user này thoát web (.thoát web) hoặc đợi hệ thống tự động giải phóng sau 2 giờ không hoạt động.")
                                continue
                        
                        # CHO PHÉP LOGIN (có thể là relogin cùng user hoặc user mới sau khi thoát)
                        user_sessions[user_id] = {
                            'username': username,
                            'password': password,
                            'status': 'waiting_command',
                            'last_activity': time.time(),
                            'created_at': datetime.now().isoformat()
                        }
                        
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id] = {
                            "id": command_id,
                            "type": "start_automation",
                            "username": username,
                            "password": password,
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        # Gửi thông báo khác nhau tùy trường hợp
                        active_session = get_active_session_info()
                        if active_session['has_active_session'] and active_session['active_user'] == username:
                            send_line_message(target_id, f"🔄 Đang khởi động lại automation cho {username}")
                        else:
                            send_line_message(target_id, f"✅ Đã nhận lệnh đăng nhập cho {username}. Hệ thống đang khởi động...")
                        
                        logger.info(f"📨 Sent command to {user_id} for {username}")
                        
                    else:
                        send_line_message(target_id, "❌ Sai cú pháp! Dùng: .login username:password")
                
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:
                    # LỆNH THOÁT WEB - GIẢI PHÓNG SESSION
                    active_session = get_active_session_info()
                    if active_session['has_active_session']:
                        username = active_session['active_user']
                        user_id_to_stop = active_session['user_id']
                        
                        # Gửi lệnh stop đến client
                        command_id = f"cmd_{int(time.time())}"
                        user_commands[user_id_to_stop] = {
                            "id": command_id,
                            "type": "stop_automation", 
                            "timestamp": datetime.now().isoformat(),
                            "requested_by": user_id  # User nào yêu cầu thoát
                        }
                        
                        send_line_message(target_id, f"🚪 Đang yêu cầu {username} thoát web...")
                        logger.info(f"🛑 Stop command sent for {username}")
                    else:
                        send_line_message(target_id, "❌ Không có automation nào đang chạy")
                
                elif message_text in ['.status', '.trangthai', 'status']:
                    # LỆNH .status - HIỂN THỊ CHI TIẾT
                    active_session = get_active_session_info()
                    if active_session['has_active_session']:
                        status_text = f"""📊 **TRẠNG THÁI HỆ THỐNG**

👤 **User đang active:** {active_session['active_user']}
⏱️ **Thời gian chạy:** {active_session['duration']}
🆔 **User ID:** {active_session['user_id'][:8]}...
📅 **Bắt đầu lúc:** {active_session['start_time'][11:16] if active_session['start_time'] else 'Unknown'}

💡 *Gõ '.thoát web' để giải phóng phiên làm việc*"""
                    else:
                        status_text = """📊 **TRẠNG THÁI HỆ THỐNG**

🟢 **Trạng thái:** Đang rảnh - Không có user nào active
🎯 **Sẵn sàng:** Nhận lệnh đăng nhập mới

💡 *Gõ '.login username:password' để bắt đầu*"""
                    
                    send_line_message(target_id, status_text)
                
                elif message_text in ['.help', 'help', 'hướng dẫn', '.huongdan']:
                    # LỆNH .help
                    help_text = """🤖 **TICKET AUTOMATION - HƯỚNG DẪN**

📋 **LỆNH SỬ DỤNG:**
• `.login username:password` - Đăng nhập vào hệ thống
• `.thoát web` - Dừng automation và giải phóng phiên  
• `.status` - Xem trạng thái hệ thống chi tiết
• `.help` - Hướng dẫn sử dụng

🎯 **QUY TẮC HOẠT ĐỘNG:**
• Chỉ **1 user** được active tại thời điểm
• Khi có người đang sử dụng, hệ thống sẽ thông báo
• User phải thoát web (.thoát web) để người khác sử dụng
• Tự động giải phóng sau 2 giờ không hoạt động

⚠️ **LƯU Ý QUAN TRỌNG:**
• Không thể login khi có user khác đang active
• Thông báo sẽ được gửi khi có sự kiện quan trọng
• Hệ thống tự động phục hồi khi browser đóng đột ngột"""
                    
                    send_line_message(target_id, help_text)
                
                elif message_text in ['.force stop', '.admin stop']:
                    # LỆNH FORCE STOP (CHO TRƯỜNG HỢP KHẨN CẤP)
                    active_session = get_active_session_info()
                    if active_session['has_active_session']:
                        username = active_session['active_user']
                        user_id_to_stop = active_session['user_id']
                        
                        # Buộc kết thúc session
                        if force_end_session(user_id_to_stop):
                            send_line_message(target_id, f"🔴 ĐÃ BUỘC DỪNG session của {username}. Hệ thống sẵn sàng cho phiên mới.")
                        else:
                            send_line_message(target_id, f"❌ Không thể buộc dừng session của {username}")
                    else:
                        send_line_message(target_id, "❌ Không có session nào đang active để buộc dừng")
            
            elif event_type == 'join':
                welcome_text = """🎉 **Bot Ticket Automation** đã tham gia nhóm!

📋 **Sử dụng các lệnh sau:**
• `.login username:password` - Đăng nhập
• `.thoát web` - Dừng automation  
• `.status` - Trạng thái hệ thống
• `.help` - Hướng dẫn chi tiết

💡 **Lưu ý quan trọng:**
• Tất cả lệnh chỉ hoạt động trong nhóm này
• Chỉ 1 user được active tại thời điểm
• User phải thoát web để người khác sử dụng
• Tự động giải phóng phiên sau 2 giờ không hoạt động"""
                send_line_message(target_id, welcome_text)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ==================== 🎯 API QUẢN LÝ SESSION ====================

@app.route('/api/register_session', methods=['POST'])
def api_register_session():
    """API đăng ký session mới - ĐÃ SỬA ĐỂ XỬ LÝ CONFLICT"""
    try:
        data = request.get_json()
        username = data.get('username')
        user_id = data.get('user_id')
        
        if not username or not user_id:
            return jsonify({"status": "error", "message": "Thiếu tham số"})
        
        # 🔥 **KIỂM TRA SESSION CONFLICT - CHỈ 1 USER ĐƯỢC ACTIVE**
        active_session = get_active_session_info()
        if active_session['has_active_session']:
            active_user = active_session['active_user']
            
            # Nếu đã có user KHÁC đang active, từ chối
            if active_user != username:
                return jsonify({
                    "status": "conflict",
                    "message": f"User {active_user} đang sử dụng phiên làm việc",
                    "active_session": active_session
                })
            
            # Nếu cùng user, cho phép relogin (ghi đè session cũ)
            # Xóa session cũ trước
            old_user_id = active_session['user_id']
            if old_user_id in active_sessions:
                del active_sessions[old_user_id]
        
        # Đăng ký session mới
        active_sessions[user_id] = {
            'username': username,
            'start_time': datetime.now().isoformat(),
            'last_activity': time.time(),
            'registered_at': datetime.now().isoformat()
        }
        
        # Cập nhật user_sessions
        if user_id in user_sessions:
            user_sessions[user_id]['status'] = 'connected'
            user_sessions[user_id]['last_activity'] = time.time()
        
        # Gửi thông báo đến nhóm
        if active_session['has_active_session'] and active_session['active_user'] == username:
            send_to_group(f"🔄 {username} đã khởi động lại session automation")
        else:
            send_to_group(f"🎯 {username} đã bắt đầu session automation")
        
        logger.info(f"🎯 Registered session for {username}")
        
        return jsonify({
            "status": "registered",
            "message": "Đăng ký session thành công",
            "session_info": get_active_session_info()
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
    """API xóa session - ĐÃ SỬA ĐỂ ĐỒNG BỘ"""
    try:
        if user_id in active_sessions:
            username = active_sessions[user_id].get('username', 'Unknown')
            del active_sessions[user_id]
            
            # Xóa cả user_commands nếu có
            if user_id in user_commands:
                del user_commands[user_id]
                
            # Gửi thông báo đến nhóm
            send_to_group(f"🗑️ Session của {username} đã được xóa")
            logger.info(f"🗑️ Cleared session for {username}")
            return jsonify({"status": "cleared", "message": f"Đã xóa session của {username}"})
        else:
            return jsonify({"status": "not_found", "message": "Không tìm thấy session"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/force_clear_session', methods=['POST'])
def api_force_clear_session():
    """API buộc xóa session (khi browser đóng đột ngột)"""
    try:
        data = request.get_json()
        username = data.get('username')
        
        # Tìm user_id theo username
        user_id_to_clear = None
        for uid, session in active_sessions.items():
            if session.get('username') == username:
                user_id_to_clear = uid
                break
        
        if user_id_to_clear:
            return api_clear_session(user_id_to_clear)
        else:
            return jsonify({"status": "not_found", "message": f"Không tìm thấy session cho {username}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==================== 📢 API GỬI TIN NHẮN NHÓM ====================

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
    """API để client gửi tin nhắn LINE (cá nhân hoặc nhóm)"""
    try:
        data = request.get_json()
        target_id = data.get('target_id')  # Có thể là user_id hoặc group_id
        message = data.get('message')
        chat_type = data.get('chat_type', 'user')  # 'user' hoặc 'group'
        
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
        
        # Tìm user_id có lệnh đang chờ
        if user_commands:
            user_id = next(iter(user_commands))
            command = user_commands[user_id]
            
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
                "command": command
            })
        else:
            return jsonify({
                "status": "waiting", 
                "message": "No pending commands",
                "active_session": get_active_session_info()
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
                "command": command,
                "active_session": get_active_session_info()
            })
        else:
            return jsonify({
                "has_command": False,
                "active_session": get_active_session_info()
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
        
        if user_id in user_commands and user_commands[user_id]["id"] == command_id:
            # CHỈ xóa command nếu là stop command, giữ lại start command để có thể relogin
            command_type = user_commands[user_id].get('type')
            if command_type == 'stop_automation':
                del user_commands[user_id]
                logger.info(f"✅ Completed STOP command {command_id} for {user_id}")
            else:
                logger.info(f"✅ Processed command {command_id} for {user_id} (keeping for potential relogin)")
        
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

# ==================== 📊 HEALTH & MONITORING ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint tối ưu"""
    cleanup_old_sessions()  # Dọn dẹp khi có request
    
    active_users = len([u for u in user_sessions.values() if u.get('status') == 'connected'])
    pending_commands = len(user_commands)
    active_sessions_count = len(active_sessions)
    
    return jsonify({
        "status": "healthy",
        "memory_optimized": True,
        "group_only": True,
        "session_management": "ENABLED",
        "conflict_check": "ENABLED",
        "active_users": active_users,
        "pending_commands": pending_commands,
        "active_sessions": active_sessions_count,
        "total_sessions": len(user_sessions),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/admin_status', methods=['GET'])
def admin_status():
    """Trang trạng thái admin - ĐÃ LOẠI BỎ PHÂN QUYỀN"""
    cleanup_old_sessions()
    
    status_info = {
        "server": "LINE Ticket Automation Server",
        "version": "4.0 - Conflict Resolved - Group Only",
        "admin_features": "DISABLED",
        "session_management": "ENABLED",
        "conflict_prevention": "ENABLED",
        "group_only": "ENABLED",
        "line_group_id": LINE_GROUP_ID,
        "timestamp": datetime.now().isoformat(),
        "statistics": {
            "total_sessions": len(user_sessions),
            "active_commands": len(user_commands),
            "active_sessions": len(active_sessions)
        },
        "active_users": [],
        "active_sessions_list": [],
        "conflict_rules": [
            "Chỉ 1 user được active tại thời điểm",
            "Từ chối login khi có user khác đang active", 
            "Cho phép relogin cùng user",
            "Tự động giải phóng sau 2 giờ không hoạt động",
            "Thông báo conflict chi tiết qua LINE group"
        ]
    }
    
    # Thông tin user đang hoạt động
    for user_id, session in user_sessions.items():
        if session.get('status') == 'connected':
            status_info["active_users"].append({
                "user_id": user_id[:8] + "...",
                "username": session.get('username', 'N/A'),
                "last_activity": session.get('last_activity', 0),
                "client_ip": session.get('client_ip', 'N/A')
            })
    
    # Thông tin session đang active
    for user_id, session in active_sessions.items():
        status_info["active_sessions_list"].append({
            "user_id": user_id[:8] + "...",
            "username": session.get('username', 'N/A'),
            "start_time": session.get('start_time'),
            "last_activity": session.get('last_activity', 0),
            "registered_at": session.get('registered_at')
        })
    
    return jsonify(status_info)

@app.route('/', methods=['GET'])
def home():
    """Trang chủ - ĐÃ CẬP NHẬT VỚI CONFLICT RESOLUTION"""
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "version": "4.0 - Conflict Resolved - Group Only", 
        "status": "running",
        "mode": "GROUP_ONLY",
        "conflict_management": "ENABLED",
        "features": [
            "Auto ticket processing",
            "Session conflict prevention", 
            "Single user at a time",
            "LINE Group only commands"
        ],
        "rules": [
            "Tất cả lệnh chỉ hoạt động trong nhóm",
            "Chỉ 1 user được active tại thời điểm",
            "Từ chối login khi có user khác đang active",
            "Cho phép relogin cùng user",
            "Tự động giải phóng phiên sau 2 giờ"
        ],
        "commands_in_group": [
            ".login username:password",
            ".thoát web", 
            ".status",
            ".help"
        ],
        "endpoints": {
            "webhook": "/webhook",
            "health": "/health", 
            "session_status": "/api/get_session_status",
            "register_session": "/api/register_session",
            "send_to_group": "/api/send_to_group"
        }
    })

# ==================== 🚀 CHẠY SERVER ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    print(f"🚀 Starting Server với chế độ NHÓM ONLY & CONFLICT RESOLUTION trên port {port}")
    print(f"🌐 Server URL: {SERVER_URL}")
    print(f"👥 LINE Group ID: {LINE_GROUP_ID}")
    print(f"🛡️ Memory-optimized keep-alive: ACTIVE")
    print(f"🎯 Session Management: ENABLED")
    print(f"⚡ Conflict Prevention: ENABLED")
    print(f"📋 Commands: Chỉ hoạt động trong nhóm")
    print(f"🔐 Rules: CHỈ 1 USER ACTIVE - TỪ CHỐI KHI CÓ USER KHÁC")
    print(f"🔄 Relogin: CHO PHÉP CÙNG USER - TỪ CHỐI USER KHÁC")
    print(f"🧹 Auto-cleanup: ENABLED (2 hours)")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
