# app.py - SERVER ONLY (LINE BOT AUTOMATION SERVER)
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
LINE_GROUP_ID = "ZpXbVLYaj"

# ==================== 📊 BIẾN TOÀN CỤC ====================
# THÊM: Heartbeat tracking
HEARTBEAT_TIMEOUT = 1800  # 30 phút (tăng từ 5 phút)
HEARTBEAT_CHECK_INTERVAL = 60  # Kiểm tra mỗi phút

# QUẢN LÝ PHIÊN
active_session = {
    "is_active": False,
    "username": None,
    "start_time": None,
    "session_id": None,
    "client_id": None,
    "login_time": None,
    "last_heartbeat": None
}

# CLIENT ĐÃ ĐĂNG KÝ - {client_id: {data}}
registered_clients = {}

# LỆNH ĐANG CHỜ - KEY LÀ CLIENT_ID
pending_commands = {}

# LOCK cho thread safety
session_lock = threading.Lock()
clients_lock = threading.Lock()
commands_lock = threading.Lock()

# Cleanup thread
cleanup_thread = None
stop_cleanup = False

# ==================== 🔧 TIỆN ÍCH ====================

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

# ==================== 🔄 API HEARTBEAT 24/7 ====================

@app.route('/api/heartbeat/<client_id>', methods=['POST'])
def api_heartbeat(client_id):
    """
    🔥 ENDPOINT MỚI: Heartbeat để duy trì kết nối 24/7
    Client gửi mỗi 30 giây để báo "tôi còn sống"
    """
    try:
        data = request.get_json() or {}
        client_status = data.get('status', 'active')
        username = data.get('username')
        heartbeat_counter = data.get('counter', 0)
        
        logger.debug(f"❤️ Heartbeat #{heartbeat_counter} từ {client_id[:10]}... - Status: {client_status}")
        
        with clients_lock:
            if client_id in registered_clients:
                # CẬP NHẬT THỜI GIAN CUỐI CÙNG
                now = datetime.now()
                registered_clients[client_id]['last_seen'] = now.isoformat()
                registered_clients[client_id]['last_heartbeat'] = now.isoformat()
                registered_clients[client_id]['status'] = client_status
                registered_clients[client_id]['heartbeat_count'] = registered_clients[client_id].get('heartbeat_count', 0) + 1
                
                if username:
                    registered_clients[client_id]['current_user'] = username
                    registered_clients[client_id]['session_status'] = 'active'
                else:
                    registered_clients[client_id]['current_user'] = None
                    registered_clients[client_id]['session_status'] = 'standby'
                
                # Nếu client này đang active session, cập nhật heartbeat cho session
                with session_lock:
                    if active_session["client_id"] == client_id:
                        active_session["last_heartbeat"] = now.isoformat()
                
                return jsonify({
                    "status": "ok", 
                    "message": "heartbeat received",
                    "server_time": now.isoformat(),
                    "session_active": active_session["is_active"],
                    "heartbeat_received": True
                })
            else:
                # Client chưa đăng ký hoặc đã bị xóa - TỰ ĐỘNG ĐĂNG KÝ LẠI
                logger.warning(f"Heartbeat từ client không tồn tại: {client_id[:10]}... - Tự động đăng ký lại")
                
                new_client_data = {
                    "ip": request.remote_addr,
                    "registered_at": datetime.now().isoformat(),
                    "last_seen": datetime.now().isoformat(),
                    "last_heartbeat": datetime.now().isoformat(),
                    "status": client_status,
                    "reconnected": True,
                    "user_agent": request.headers.get('User-Agent', 'Unknown'),
                    "heartbeat_count": 1
                }
                
                if username:
                    new_client_data['current_user'] = username
                    new_client_data['session_status'] = 'active'
                else:
                    new_client_data['session_status'] = 'standby'
                
                registered_clients[client_id] = new_client_data
                logger.info(f"✅ Tự động đăng ký lại client: {client_id[:10]}...")
                
                return jsonify({
                    "status": "reconnected",
                    "message": "Client đã được đăng ký lại",
                    "client_id": client_id,
                    "session_active": active_session["is_active"]
                })
                
    except Exception as e:
        logger.error(f"❌ Heartbeat error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/client_status/<client_id>', methods=['GET'])
def api_client_status(client_id):
    """API kiểm tra trạng thái client"""
    try:
        with clients_lock:
            if client_id in registered_clients:
                client_data = registered_clients[client_id]
                
                # Kiểm tra client có còn sống không
                last_heartbeat_str = client_data.get('last_heartbeat')
                is_alive = False
                seconds_since_last_hb = 0
                
                if last_heartbeat_str:
                    try:
                        last_heartbeat = datetime.fromisoformat(last_heartbeat_str)
                        now = datetime.now()
                        seconds_since_last_hb = (now - last_heartbeat).total_seconds()
                        is_alive = seconds_since_last_hb < 90  # 1.5 phút không heartbeat = dead
                    except:
                        is_alive = False
                
                # Kiểm tra session trên server
                with session_lock:
                    has_active_session = active_session["is_active"] and active_session["client_id"] == client_id
                    session_username = active_session["username"] if has_active_session else None
                
                return jsonify({
                    "status": "found",
                    "client_id": client_id,
                    "is_alive": is_alive,
                    "seconds_since_last_hb": seconds_since_last_hb,
                    "last_heartbeat": client_data.get('last_heartbeat'),
                    "last_seen": client_data.get('last_seen'),
                    "current_user": client_data.get('current_user'),
                    "session_status": client_data.get('session_status', 'unknown'),
                    "registered_at": client_data.get('registered_at'),
                    "client_status": client_data.get('status', 'unknown'),
                    "heartbeat_count": client_data.get('heartbeat_count', 0),
                    "has_active_session_on_server": has_active_session,
                    "session_username": session_username,
                    "server_session_active": active_session["is_active"]
                })
            else:
                return jsonify({
                    "status": "not_found",
                    "message": "Client không tồn tại hoặc đã bị xóa",
                    "client_id": client_id
                })
    except Exception as e:
        logger.error(f"❌ Client status error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/list_clients', methods=['GET'])
def api_list_clients():
    """API liệt kê tất cả client đang kết nối"""
    try:
        with clients_lock:
            clients_list = []
            now = datetime.now()
            
            for client_id, client_data in registered_clients.items():
                last_hb_str = client_data.get('last_heartbeat')
                is_alive = False
                seconds_since_last_hb = 0
                
                if last_hb_str:
                    try:
                        last_hb = datetime.fromisoformat(last_hb_str)
                        seconds_since_last_hb = (now - last_hb).total_seconds()
                        is_alive = seconds_since_last_hb < 90
                    except:
                        pass
                
                clients_list.append({
                    "client_id": client_id[:15] + "...",
                    "is_alive": is_alive,
                    "seconds_since_last_hb": seconds_since_last_hb,
                    "status": client_data.get('status', 'unknown'),
                    "current_user": client_data.get('current_user'),
                    "session_status": client_data.get('session_status', 'unknown'),
                    "heartbeat_count": client_data.get('heartbeat_count', 0),
                    "registered_at": client_data.get('registered_at')
                })
            
            return jsonify({
                "status": "success",
                "total_clients": len(registered_clients),
                "alive_clients": len([c for c in clients_list if c['is_alive']]),
                "clients": clients_list
            })
    except Exception as e:
        logger.error(f"❌ List clients error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 🎯 API CHO LOCAL DAEMON ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API đăng ký client - CẬP NHẬT CHO 24/7"""
    try:
        client_ip = request.remote_addr
        client_id = generate_client_id()
        
        # Lưu client đã đăng ký
        with clients_lock:
            registered_clients[client_id] = {
                "ip": client_ip,
                "registered_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "last_heartbeat": datetime.now().isoformat(),
                "user_agent": request.headers.get('User-Agent', 'Unknown'),
                "status": "registered",
                "session_status": "standby",
                "heartbeat_count": 0
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
            "active_user": active_session["username"],
            "heartbeat_required": True,
            "heartbeat_interval": 30,
            "server_time": datetime.now().isoformat(),
            "message": "Đăng ký thành công. Hãy bắt đầu gửi heartbeat để duy trì kết nối."
        }
        
        if has_command:
            logger.info(f"📨 Client {client_id[:10]}... có lệnh đang chờ: {command.get('type')}")
        
        return jsonify(response_data)
            
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_commands/<client_id>', methods=['GET'])
def api_get_commands(client_id):
    """API lấy lệnh - CẬP NHẬT CHO 24/7"""
    try:
        # Cập nhật last seen và last heartbeat
        with clients_lock:
            if client_id in registered_clients:
                registered_clients[client_id]['last_seen'] = datetime.now().isoformat()
                registered_clients[client_id]['last_heartbeat'] = datetime.now().isoformat()
        
        logger.debug(f"🔍 Client {client_id[:10]}... đang check command")
        
        with commands_lock:
            if client_id in pending_commands:
                command = pending_commands[client_id]
                logger.info(f"📤 Gửi command đến {client_id[:10]}...: {command.get('type')}")
                return jsonify({
                    "has_command": True,
                    "command": command,
                    "timestamp": datetime.now().isoformat()
                })
            else:
                return jsonify({
                    "has_command": False,
                    "timestamp": datetime.now().isoformat()
                })
    except Exception as e:
        logger.error(f"❌ Get command error: {e}")
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên - CẬP NHẬT THÊM HEARTBEAT"""
    try:
        data = request.get_json()
        username = data.get('username')
        client_id = data.get('user_id')
        
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
                "login_time": datetime.now().isoformat(),
                "last_heartbeat": datetime.now().isoformat()
            })
            
            logger.info(f"✅ ĐÃ BẮT ĐẦU PHIÊN: {username} - Session: {session_id[:10]}...")
        
        # Cập nhật thông tin client
        with clients_lock:
            if client_id in registered_clients:
                registered_clients[client_id]['current_user'] = username
                registered_clients[client_id]['status'] = 'in_session'
                registered_clients[client_id]['session_status'] = 'active'
        
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
            },
            "heartbeat_required": True,
            "heartbeat_interval": 30,
            "server_time": datetime.now().isoformat()
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
                    "login_time": None,
                    "last_heartbeat": None
                })
                
                logger.info(f"✅ ĐÃ KẾT THÚC PHIÊN: {ended_user}")
                
                # Cập nhật thông tin client
                with clients_lock:
                    if ended_client in registered_clients:
                        registered_clients[ended_client]['current_user'] = None
                        registered_clients[ended_client]['status'] = 'standby'
                        registered_clients[ended_client]['session_status'] = 'ended'
                
                # Gửi thông báo LINE
                if message:
                    send_to_group(message)
                else:
                    send_to_group(f"✅ **KẾT THÚC PHIÊN**\n👤 User: {ended_user}\n📌 Lý do: {reason}")
                
                return jsonify({
                    "status": "ended",
                    "message": f"Đã kết thúc phiên của {ended_user}",
                    "system_reset": True,
                    "server_time": datetime.now().isoformat()
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
                    "login_time": None,
                    "last_heartbeat": None
                })
                
                logger.warning(f"⚠️ ĐÃ BUỘC KẾT THÚC PHIÊN: {ended_user} - Lý do: {reason}")
                
                # Cập nhật thông tin client
                with clients_lock:
                    if ended_client in registered_clients:
                        registered_clients[ended_client]['current_user'] = None
                        registered_clients[ended_client]['status'] = 'standby'
                        registered_clients[ended_client]['session_status'] = 'force_ended'
                
                # Gửi thông báo LINE
                if message:
                    send_to_group(message)
                
                return jsonify({
                    "status": "force_ended",
                    "message": f"Đã buộc kết thúc phiên của {ended_user}",
                    "server_time": datetime.now().isoformat()
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
        
        return jsonify({"status": "completed", "timestamp": datetime.now().isoformat()})
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
                "session_id": active_session["session_id"],
                "last_heartbeat": active_session.get("last_heartbeat"),
                "server_time": datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"❌ Get session info error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
                                f"📌 Kiểm tra local daemon đã chạy chưa?\n"
                                f"💡 Client cần luôn gửi heartbeat để duy trì kết nối"
                            )
                        else:
                            send_line_reply(reply_token, 
                                f"✅ **Đã nhận lệnh đăng nhập cho {username}**\n"
                                f"📤 Đang gửi đến {sent_count} client...\n"
                                f"⏳ Chờ client phản hồi..."
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
                            last_heartbeat = active_session.get("last_heartbeat")
                            
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
                            
                            # Tính thời gian từ heartbeat cuối
                            heartbeat_info = ""
                            if last_heartbeat:
                                try:
                                    last_hb_dt = datetime.fromisoformat(last_heartbeat)
                                    hb_diff = (datetime.now() - last_hb_dt).total_seconds()
                                    if hb_diff < 60:
                                        heartbeat_info = "✓ Kết nối live"
                                    else:
                                        heartbeat_info = f"⏰ HB: {int(hb_diff)}s trước"
                                except:
                                    heartbeat_info = ""
                            
                            with clients_lock:
                                total_clients = len(registered_clients)
                                alive_clients = sum(1 for c in registered_clients.values() 
                                                   if c.get('last_heartbeat') and 
                                                   (datetime.now() - datetime.fromisoformat(c['last_heartbeat'])).total_seconds() < 90)
                            
                            status_text = f"""📊 **TRẠNG THÁI HIỆN TẠI**

👤 User: {active_session['username']}
⏱️ Thời gian: {duration_text}
🔗 {heartbeat_info}
🆔 Session: {active_session['session_id'][:10]}...
📡 Client: {active_session['client_id'][:10] if active_session['client_id'] else 'N/A'}...

📊 **HỆ THỐNG**
🟢 Client kết nối: {alive_clients}/{total_clients}
💡 Gõ '.thoát web' để kết thúc"""
                        else:
                            with clients_lock:
                                total_clients = len(registered_clients)
                                alive_clients = sum(1 for c in registered_clients.values() 
                                                   if c.get('last_heartbeat') and 
                                                   (datetime.now() - datetime.fromisoformat(c['last_heartbeat'])).total_seconds() < 90)
                            
                            status_text = f"""📊 **TRẠNG THÁI HIỆN TẠI**

🟢 Trạng thái: STANDBY
🎯 Sẵn sàng nhận phiên mới

📊 **HỆ THỐNG**
📡 Client đang kết nối: {alive_clients}/{total_clients}
❤️ Heartbeat: Đang hoạt động
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
• .clients - Xem client đang kết nối

⚠️ **Lưu ý:**
- Chỉ 1 phiên làm việc tại 1 thời điểm
- Tự động kết thúc khi hết ca
- Client luôn gửi heartbeat để duy trì kết nối"""
                    send_line_reply(reply_token, help_text)
                
                # LỆNH INFO
                elif message_text == '.info':
                    with session_lock:
                        session_status = "ACTIVE" if active_session["is_active"] else "STANDBY"
                        user = active_session["username"] or "None"
                    
                    with clients_lock:
                        total_clients = len(registered_clients)
                        alive_clients = sum(1 for c in registered_clients.values() 
                                           if c.get('last_heartbeat') and 
                                           (datetime.now() - datetime.fromisoformat(c['last_heartbeat'])).total_seconds() < 90)
                    
                    info_text = f"""🔍 **THÔNG TIN SERVER 24/7**

🌐 Server: {SERVER_URL}
📊 Trạng thái: {session_status}
👤 User: {user}
📡 Client: {alive_clients}/{total_clients} (đang kết nối/tổng)
❤️ Heartbeat: 30s/30phút
⏰ Time: {datetime.now().strftime('%H:%M:%S')}
🔄 Uptime: 24/7 - Luôn sẵn sàng"""
                    send_line_reply(reply_token, info_text)
                
                # LỆNH CLIENTS
                elif message_text == '.clients':
                    with clients_lock:
                        total_clients = len(registered_clients)
                        alive_clients = 0
                        clients_info = []
                        
                        for client_id, client_data in registered_clients.items():
                            last_hb_str = client_data.get('last_heartbeat')
                            is_alive = False
                            
                            if last_hb_str:
                                try:
                                    last_hb = datetime.fromisoformat(last_hb_str)
                                    is_alive = (datetime.now() - last_hb).total_seconds() < 90
                                except:
                                    pass
                            
                            if is_alive:
                                alive_clients += 1
                            
                            client_status = "🟢" if is_alive else "🔴"
                            user = client_data.get('current_user', 'none')
                            status = client_data.get('status', 'unknown')
                            
                            clients_info.append(f"{client_status} {client_id[:10]}... | {user} | {status}")
                    
                    clients_text = f"""📡 **CLIENTS ĐANG KẾT NỐI**

🟢 Đang sống: {alive_clients}
🔴 Không phản hồi: {total_clients - alive_clients}
📊 Tổng: {total_clients}

"""
                    if clients_info:
                        clients_text += "\n".join(clients_info[:10])
                        if len(clients_info) > 10:
                            clients_text += f"\n... và {len(clients_info) - 10} client khác"
                    else:
                        clients_text += "Không có client nào"
                    
                    send_line_reply(reply_token, clients_text)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 📊 HEALTH & INFO ====================

@app.route('/health', methods=['GET'])
def health():
    with session_lock:
        session_active = active_session["is_active"]
        username = active_session["username"]
        client_id = active_session["client_id"]
        last_heartbeat = active_session.get("last_heartbeat")
    
    with clients_lock:
        client_count = len(registered_clients)
        
        # Đếm client đang sống
        alive_clients = 0
        now = datetime.now()
        for client_data in registered_clients.values():
            last_hb_str = client_data.get('last_heartbeat')
            if last_hb_str:
                try:
                    last_hb = datetime.fromisoformat(last_hb_str)
                    if (now - last_hb).total_seconds() < 90:
                        alive_clients += 1
                except:
                    pass
    
    with commands_lock:
        pending_count = len(pending_commands)
    
    return jsonify({
        "status": "healthy",
        "server": "LINE Automation Server",
        "version": "3.0",
        "features": ["heartbeat_24_7", "auto_reconnect", "client_tracking"],
        "active_session": {
            "is_active": session_active,
            "username": username,
            "client_id": client_id[:10] + "..." if client_id else None,
            "last_heartbeat": last_heartbeat
        },
        "statistics": {
            "pending_commands": pending_count,
            "registered_clients": client_count,
            "alive_clients": alive_clients,
            "heartbeat_timeout": HEARTBEAT_TIMEOUT,
            "uptime": "24/7"
        },
        "timestamp": datetime.now().isoformat(),
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": "Server 24/7 - Luôn sẵn sàng nhận lệnh"
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "LINE Ticket Automation Server 24/7",
        "description": "Quản lý phiên làm việc tự động - Kết nối liên tục",
        "endpoints": {
            "health": "/health",
            "register": "/api/register_local (POST)",
            "heartbeat": "/api/heartbeat/<client_id> (POST)",
            "client_status": "/api/client_status/<client_id> (GET)",
            "commands": "/api/get_commands/<client_id> (GET)",
            "start_session": "/api/start_session (POST)",
            "end_session": "/api/end_session (POST)"
        },
        "active": active_session["is_active"],
        "user": active_session["username"],
        "clients": len(registered_clients),
        "heartbeat_system": "active_24_7"
    })

# ==================== 🧹 CLEANUP THREAD 24/7 ====================

def cleanup_old_clients():
    """Dọn dẹp client không hoạt động - CHO 24/7"""
    global stop_cleanup
    
    while not stop_cleanup:
        try:
            time.sleep(HEARTBEAT_CHECK_INTERVAL)
            
            with clients_lock:
                now = datetime.now()
                clients_to_remove = []
                
                for client_id, client_data in registered_clients.items():
                    last_heartbeat_str = client_data.get('last_heartbeat')
                    
                    if last_heartbeat_str:
                        try:
                            last_heartbeat = datetime.fromisoformat(last_heartbeat_str)
                            
                            # 30 phút không heartbeat mới xóa
                            if (now - last_heartbeat) > timedelta(seconds=HEARTBEAT_TIMEOUT):
                                # Kiểm tra xem client có đang active session không
                                with session_lock:
                                    if active_session.get('client_id') != client_id:
                                        clients_to_remove.append(client_id)
                        except:
                            clients_to_remove.append(client_id)
                    else:
                        # Không có heartbeat record
                        registered_at_str = client_data.get('registered_at')
                        if registered_at_str:
                            try:
                                registered_at = datetime.fromisoformat(registered_at_str)
                                if (now - registered_at) > timedelta(minutes=60):
                                    clients_to_remove.append(client_id)
                            except:
                                clients_to_remove.append(client_id)
                
                # Xóa client cũ
                for client_id in clients_to_remove:
                    del registered_clients[client_id]
                    logger.info(f"🧹 Đã xóa client không hoạt động (sau {HEARTBEAT_TIMEOUT}s): {client_id[:10]}...")
                    
                    # Xóa lệnh pending của client này
                    with commands_lock:
                        if client_id in pending_commands:
                            del pending_commands[client_id]
            
            logger.debug(f"Cleanup 24/7: {len(registered_clients)} clients đang được theo dõi")
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ==================== 🚀 CHẠY SERVER 24/7 ====================
def start_cleanup_thread():
    """Bắt đầu thread cleanup 24/7"""
    global cleanup_thread, stop_cleanup
    
    if cleanup_thread and cleanup_thread.is_alive():
        return
    
    stop_cleanup = False
    cleanup_thread = threading.Thread(target=cleanup_old_clients, daemon=True)
    cleanup_thread.start()
    logger.info("✅ Đã bắt đầu cleanup thread 24/7")

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
🚀 SERVER START - 24/7 LIÊN TỤC KẾT NỐI
🚀 ========================================
🌐 Server: {SERVER_URL}
👥 Group: {LINE_GROUP_ID}

🎯 TÍNH NĂNG MỚI 24/7:
• Heartbeat system - duy trì kết nối liên tục
• Client tracking - theo dõi mọi client
• Auto-reconnect - tự động kết nối lại
• 30 phút timeout - tăng từ 5 phút
• Status chi tiết - biết client nào đang sống

📊 HIỆN TẠI:
• Session: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
• User: {active_session["username"] or 'None'}
• Clients: {len(registered_clients)}
• Heartbeat: Mỗi 30s / Timeout 30 phút
• Time: {datetime.now().strftime('%H:%M:%S')}
• Mode: 24/7 - Luôn sẵn sàng
========================================
    """)
    
    # Bắt đầu cleanup thread 24/7
    start_cleanup_thread()
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 Dừng server...")
    finally:
        stop_cleanup_thread()
