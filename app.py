# app.py (SERVER - TỐI ƯU VÀ ĐỒNG BỘ)
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime, timedelta
import time
import random
import threading

# ==================== ⚙️ CẤU HÌNH ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
    "client_id": None,
    "login_time": None
}

# LỆNH ĐANG CHỜ - KEY LÀ CLIENT_ID
pending_commands = {}

# CLIENT ĐÃ ĐĂNG KÝ - {client_id: {data}}
registered_clients = {}

# LOCK cho thread safety
session_lock = threading.Lock()
clients_lock = threading.Lock()
commands_lock = threading.Lock()

# Cleanup thread
cleanup_thread = None
stop_cleanup = False

def generate_client_id():
    """Tạo ID duy nhất cho client"""
    return f"client_{int(time.time())}_{random.randint(1000, 9999)}"

def generate_session_id():
    """Tạo ID duy nhất cho session"""
    return f"session_{int(time.time())}_{random.randint(1000, 9999)}"

def send_line_reply(reply_token, text):
    """Gửi reply tin nhắn LINE"""
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
        
        response = requests.post(url, headers=headers, json=data, timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Line reply error: {e}")
        return False

def send_line_message(chat_id, text):
    """Gửi tin nhắn LINE đến chat_id cụ thể"""
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
        
        response = requests.post(url, headers=headers, json=data, timeout=5)
        if response.status_code != 200:
            logger.error(f"Line push failed: {response.text}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Line push error: {e}")
        return False

def send_to_group(text):
    """Gửi tin nhắn đến group LINE"""
    if LINE_GROUP_ID:
        success = send_line_message(LINE_GROUP_ID, text)
        if success:
            logger.info(f"Đã gửi tới group: {text[:50]}...")
        return success
    return False

def cleanup_old_clients():
    """Dọn dẹp client không hoạt động (chạy trong thread riêng)"""
    global stop_cleanup
    
    while not stop_cleanup:
        try:
            time.sleep(60)  # Chạy mỗi phút
            
            with clients_lock:
                now = datetime.now()
                clients_to_remove = []
                
                for client_id, client_data in registered_clients.items():
                    last_seen_str = client_data.get('last_seen')
                    if last_seen_str:
                        try:
                            last_seen = datetime.fromisoformat(last_seen_str)
                            if (now - last_seen) > timedelta(minutes=5):  # Quá 5 phút
                                clients_to_remove.append(client_id)
                        except:
                            clients_to_remove.append(client_id)
                
                # Xóa client cũ
                for client_id in clients_to_remove:
                    # Kiểm tra xem client có đang active không
                    if active_session.get('client_id') != client_id:
                        del registered_clients[client_id]
                        logger.info(f"Đã xóa client không hoạt động: {client_id[:10]}...")
                        
                        # Xóa lệnh pending của client này
                        with commands_lock:
                            if client_id in pending_commands:
                                del pending_commands[client_id]
            
            logger.debug(f"Cleanup: {len(registered_clients)} clients active")
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ==================== 🌐 WEBHOOK LINE ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        logger.info(f"Nhận {len(events)} events từ LINE")
        
        for event in events:
            event_type = event.get('type')
            reply_token = event.get('replyToken')
            user_id = event.get('source', {}).get('userId')
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                logger.info(f"Tin nhắn từ {user_id[:10] if user_id else 'unknown'}: {message_text[:50]}...")
                
                # LỆNH LOGIN
                if message_text.startswith('.login '):
                    credentials = message_text[7:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        
                        with session_lock:
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
                            "timestamp": datetime.now().isoformat(),
                            "source": "line_webhook"
                        }
                        
                        # Gửi lệnh đến tất cả client đã đăng ký
                        sent_count = 0
                        with clients_lock:
                            client_ids = list(registered_clients.keys())
                        
                        for client_id in client_ids:
                            with commands_lock:
                                pending_commands[client_id] = command_data
                            sent_count += 1
                            logger.info(f"📨 Gửi lệnh login đến client: {client_id[:10]}...")
                        
                        if sent_count == 0:
                            send_line_reply(reply_token, 
                                f"❌ **Không có client nào kết nối!**\n"
                                f"📌 Kiểm tra local daemon đã chạy chưa?"
                            )
                        else:
                            send_line_reply(reply_token, 
                                f"✅ **Đã nhận lệnh đăng nhập cho {username}**\n"
                                f"📤 Đang gửi đến {sent_count} client..."
                            )
                        
                        logger.info(f"📝 Lưu lệnh login cho {username}, gửi đến {sent_count} client")
                        
                    else:
                        send_line_reply(reply_token, "❌ Sai cú pháp! Dùng: .login username:password")
                
                # LỆNH THOÁT WEB
                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng']:
                    with session_lock:
                        if active_session["is_active"]:
                            current_user = active_session["username"]
                            client_id = active_session["client_id"]
                            
                            if client_id:
                                # Tạo lệnh stop cho client đang active
                                command_id = f"cmd_{int(time.time())}"
                                with commands_lock:
                                    pending_commands[client_id] = {
                                        "id": command_id,
                                        "type": "stop_automation",
                                        "username": current_user,
                                        "timestamp": datetime.now().isoformat(),
                                        "source": "line_webhook"
                                    }
                                logger.info(f"📤 Gửi lệnh stop đến client: {client_id[:10]}...")
                            
                            send_line_reply(reply_token, f"🚪 **Đang yêu cầu {current_user} thoát web...**")
                        else:
                            send_line_reply(reply_token, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai']:
                    with session_lock:
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
📡 Client: {active_session['client_id'][:10] if active_session['client_id'] else 'N/A'}...
💡 Gõ '.thoát web' để kết thúc"""
                        else:
                            with clients_lock:
                                active_clients = len(registered_clients)
                            
                            status_text = f"""📊 **TRẠNG THÁI**

🟢 Trạng thái: STANDBY
🎯 Sẵn sàng nhận phiên mới
📡 Client đang kết nối: {active_clients}
💡 Gõ '.login username:password' để bắt đầu"""
                    
                    send_line_reply(reply_token, status_text)
                
                # LỆNH HELP
                elif message_text in ['.help', 'help', '.menu']:
                    help_text = """📋 **DANH SÁCH LỆNH:**

🎯 **Quản lý phiên:**
• .login username:password - Bắt đầu phiên làm việc
• .thoát web - Kết thúc phiên hiện tại
• .status - Xem trạng thái hệ thống

📊 **Thông tin:**
• .help - Hiển thị hướng dẫn
• .info - Thông tin server

⚠️ **Lưu ý:**
- Chỉ 1 phiên làm việc tại 1 thời điểm
- Tự động kết thúc khi hết ca
- Thông báo sẽ gửi vào nhóm LINE"""
                    send_line_reply(reply_token, help_text)
                
                # LỆNH INFO
                elif message_text == '.info':
                    with session_lock:
                        session_status = "ACTIVE" if active_session["is_active"] else "STANDBY"
                        user = active_session["username"] or "None"
                    
                    with clients_lock:
                        client_count = len(registered_clients)
                    
                    info_text = f"""🔍 **THÔNG TIN SERVER**

🌐 Server: {SERVER_URL}
📊 Trạng thái: {session_status}
👤 User: {user}
📡 Client: {client_count}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}
🔄 Uptime: Đang chạy ổn định"""
                    send_line_reply(reply_token, info_text)
        
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
        with clients_lock:
            registered_clients[client_id] = {
                "ip": client_ip,
                "registered_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "user_agent": request.headers.get('User-Agent', 'Unknown')
            }
        
        logger.info(f"✅ Client đăng ký: {client_id[:10]}... từ IP: {client_ip}")
        logger.info(f"📊 Tổng client đã đăng ký: {len(registered_clients)}")
        
        # Kiểm tra nếu có lệnh đang chờ cho client này
        with commands_lock:
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
            logger.info(f"📨 Client {client_id[:10]}... có lệnh đang chờ: {command.get('type')}")
        
        return jsonify(response_data)
            
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_commands/<client_id>', methods=['GET'])
def api_get_commands(client_id):
    """API lấy lệnh - ĐÃ SỬA TÊN (quan trọng)"""
    try:
        # Cập nhật last seen
        with clients_lock:
            if client_id in registered_clients:
                registered_clients[client_id]['last_seen'] = datetime.now().isoformat()
        
        logger.debug(f"🔍 Client {client_id[:10]}... đang check command")
        
        with commands_lock:
            if client_id in pending_commands:
                command = pending_commands[client_id]
                logger.info(f"📤 Gửi command đến {client_id[:10]}...: {command.get('type')}")
                return jsonify({
                    "has_command": True,
                    "command": command
                })
            else:
                return jsonify({"has_command": False})
    except Exception as e:
        logger.error(f"❌ Get command error: {e}")
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên"""
    try:
        data = request.get_json()
        username = data.get('username')
        client_id = data.get('user_id')  # ĐỒNG BỘ VỚI LOCAL
        
        logger.info(f"📥 Start session: {username} (Client: {client_id[:10] if client_id else 'N/A'})")
        
        with session_lock:
            # KIỂM TRA PHIÊN HIỆN TẠI
            if active_session["is_active"]:
                current_user = active_session["username"]
                logger.warning(f"Session conflict: {current_user} đang active")
                return jsonify({
                    "status": "conflict",
                    "message": f"Phiên làm việc đang được sử dụng bởi {current_user}"
                })
            
            # KIỂM TRA CLIENT CÓ TỒN TẠI KHÔNG
            with clients_lock:
                if client_id not in registered_clients:
                    logger.warning(f"Client không tồn tại: {client_id}")
                    return jsonify({
                        "status": "error",
                        "message": "Client chưa đăng ký hoặc đã disconnect"
                    })
            
            # BẮT ĐẦU PHIÊN MỚI
            session_id = generate_session_id()
            
            active_session.update({
                "is_active": True,
                "username": username,
                "start_time": datetime.now().isoformat(),
                "session_id": session_id,
                "client_id": client_id,
                "login_time": datetime.now().isoformat()
            })
            
            logger.info(f"✅ ĐÃ BẮT ĐẦU PHIÊN: {username} - Session: {session_id[:10]}...")
        
        # Gửi thông báo LINE
        send_to_group(f"🎯 **BẮT ĐẦU PHIÊN**\n👤 User: {username}\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        
        return jsonify({
            "status": "started",
            "message": f"Đã bắt đầu phiên làm việc cho {username}",
            "session_id": session_id,
            "session_info": {
                "username": username,
                "start_time": active_session["start_time"],
                "session_id": session_id
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Start session error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/end_session', methods=['POST'])
def api_end_session():
    """API kết thúc phiên"""
    try:
        data = request.get_json()
        username = data.get('username')
        reason = data.get('reason', 'normal_exit')
        message = data.get('message', '')
        client_id = data.get('user_id')
        
        logger.info(f"📥 End session: {username}, reason: {reason}, client: {client_id[:10] if client_id else 'N/A'}")
        
        with session_lock:
            if active_session["is_active"]:
                ended_user = active_session["username"]
                ended_client = active_session["client_id"]
                
                # Xác minh client (tùy chọn)
                if client_id and client_id != ended_client:
                    logger.warning(f"Client mismatch: {client_id} != {ended_client}")
                
                # Xóa lệnh pending của client này
                with commands_lock:
                    if ended_client in pending_commands:
                        del pending_commands[ended_client]
                        logger.info(f"🧹 Đã xóa lệnh pending của client {ended_client[:10]}...")
                
                # Reset session
                active_session.update({
                    "is_active": False,
                    "username": None,
                    "start_time": None,
                    "session_id": None,
                    "client_id": None,
                    "login_time": None
                })
                
                logger.info(f"✅ ĐÃ KẾT THÚC PHIÊN: {ended_user}")
                
                # Gửi thông báo LINE
                if message:
                    send_to_group(message)
                else:
                    send_to_group(f"✅ **KẾT THÚC PHIÊN**\n👤 User: {ended_user}\n📌 Lý do: {reason}")
                
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
        logger.error(f"❌ End session error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/force_end_session', methods=['POST'])
def api_force_end_session():
    """API buộc kết thúc phiên (khi có lỗi)"""
    try:
        data = request.get_json()
        reason = data.get('reason', 'force_exit')
        message = data.get('message', '')
        
        logger.warning(f"📥 Force end session: {reason}")
        
        with session_lock:
            if active_session["is_active"]:
                ended_user = active_session["username"]
                ended_client = active_session["client_id"]
                
                # Xóa lệnh pending của client này
                with commands_lock:
                    if ended_client in pending_commands:
                        del pending_commands[ended_client]
                
                # Reset session
                active_session.update({
                    "is_active": False,
                    "username": None,
                    "start_time": None,
                    "session_id": None,
                    "client_id": None,
                    "login_time": None
                })
                
                logger.warning(f"⚠️ ĐÃ BUỘC KẾT THÚC PHIÊN: {ended_user} - Lý do: {reason}")
                
                # Gửi thông báo LINE
                if message:
                    send_to_group(message)
                
                return jsonify({
                    "status": "force_ended",
                    "message": f"Đã buộc kết thúc phiên của {ended_user}"
                })
        
        return jsonify({
            "status": "no_session",
            "message": "Không có phiên nào để kết thúc"
        })
        
    except Exception as e:
        logger.error(f"❌ Force end session error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/complete_command', methods=['POST'])
def api_complete_command():
    """API hoàn thành lệnh"""
    try:
        data = request.get_json()
        client_id = data.get('user_id')
        command_id = data.get('command_id')
        command_type = data.get('command_type')
        
        logger.info(f"📥 Complete command: client={client_id[:10] if client_id else 'unknown'}, cmd={command_id}, type={command_type}")
        
        # Xóa lệnh đã hoàn thành
        with commands_lock:
            if client_id in pending_commands and pending_commands[client_id]["id"] == command_id:
                del pending_commands[client_id]
                logger.info(f"✅ Đã xóa lệnh {command_id} ({command_type}) của client {client_id[:10]}...")
            else:
                logger.warning(f"Không tìm thấy lệnh {command_id} cho client {client_id[:10]}...")
        
        return jsonify({"status": "completed"})
    except Exception as e:
        logger.error(f"❌ Complete command error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    """API gửi tin nhắn LINE"""
    try:
        data = request.get_json()
        target_id = data.get('user_id')
        message = data.get('message')
        
        if not target_id or not message:
            return jsonify({"status": "error", "message": "Thiếu user_id hoặc message"})
        
        success = send_line_message(target_id, message)
        return jsonify({"status": "sent" if success else "error"})
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_session_info', methods=['GET'])
def api_get_session_info():
    """API lấy thông tin phiên hiện tại"""
    try:
        with session_lock:
            return jsonify({
                "is_active": active_session["is_active"],
                "username": active_session["username"],
                "start_time": active_session["start_time"],
                "client_id": active_session["client_id"],
                "session_id": active_session["session_id"]
            })
    except Exception as e:
        logger.error(f"❌ Get session info error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 📊 HEALTH & INFO ====================

@app.route('/health', methods=['GET'])
def health():
    with session_lock:
        session_active = active_session["is_active"]
        username = active_session["username"]
        client_id = active_session["client_id"]
    
    with clients_lock:
        client_count = len(registered_clients)
    
    with commands_lock:
        pending_count = len(pending_commands)
    
    return jsonify({
        "status": "healthy",
        "server": "LINE Automation Server",
        "version": "2.0",
        "active_session": {
            "is_active": session_active,
            "username": username,
            "client_id": client_id[:10] + "..." if client_id else None
        },
        "statistics": {
            "pending_commands": pending_count,
            "registered_clients": client_count,
            "uptime": "running"
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "LINE Ticket Automation Server",
        "description": "Quản lý phiên làm việc tự động",
        "endpoints": {
            "health": "/health",
            "register": "/api/register_local (POST)",
            "commands": "/api/get_commands/<client_id> (GET)",
            "start_session": "/api/start_session (POST)",
            "end_session": "/api/end_session (POST)"
        },
        "active": active_session["is_active"],
        "user": active_session["username"],
        "clients": len(registered_clients)
    })

# ==================== 🚀 CHẠY SERVER ====================
def start_cleanup_thread():
    """Bắt đầu thread cleanup"""
    global cleanup_thread, stop_cleanup
    
    if cleanup_thread and cleanup_thread.is_alive():
        return
    
    stop_cleanup = False
    cleanup_thread = threading.Thread(target=cleanup_old_clients, daemon=True)
    cleanup_thread.start()
    logger.info("✅ Đã bắt đầu cleanup thread")

def stop_cleanup_thread():
    """Dừng cleanup thread"""
    global stop_cleanup
    stop_cleanup = True
    if cleanup_thread:
        cleanup_thread.join(timeout=2)
    logger.info("✅ Đã dừng cleanup thread")

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================
🚀 SERVER START - TỐI ƯU VÀ ĐỒNG BỘ
🚀 ========================================
🌐 Server: {SERVER_URL}
👥 Group: {LINE_GROUP_ID}

🎯 TÍNH NĂNG MỚI:
• Thread-safe với locks
• Tự động cleanup client
• Logging chi tiết
• Xử lý lỗi tốt hơn
• Đồng bộ với local daemon

📊 HIỆN TẠI:
• Session: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
• User: {active_session["username"] or 'None'}
• Clients: {len(registered_clients)}
• Time: {datetime.now().strftime('%H:%M:%S')}
========================================
    """)
    
    # Bắt đầu cleanup thread
    start_cleanup_thread()
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 Dừng server...")
    finally:
        stop_cleanup_thread()
