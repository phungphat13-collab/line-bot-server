# app.py - SERVER ONLY (LINE BOT AUTOMATION SERVER) - FIXED 24/7
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime, timedelta
import time
import random
import threading
import sqlite3
from contextlib import contextmanager

# ==================== ⚙️ CẤU HÌNH ====================
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "MCerQE7Kk9"  # ⬅️ GROUP ID MỚI

# ==================== 📊 DATABASE ====================
@contextmanager
def get_db():
    conn = sqlite3.connect('server.db')
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        # Bảng clients
        conn.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                ip TEXT,
                registered_at TEXT,
                last_seen TEXT,
                last_heartbeat TEXT,
                status TEXT,
                user_agent TEXT,
                current_user TEXT,
                session_status TEXT,
                heartbeat_count INTEGER DEFAULT 0,
                is_alive BOOLEAN DEFAULT 1
            )
        ''')
        
        # Bảng sessions
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                client_id TEXT,
                username TEXT,
                start_time TEXT,
                end_time TEXT,
                reason TEXT,
                shift_name TEXT,
                duration_seconds INTEGER,
                FOREIGN KEY (client_id) REFERENCES clients (id)
            )
        ''')
        
        # Bảng commands
        conn.execute('''
            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY,
                client_id TEXT,
                type TEXT,
                data TEXT,
                created_at TEXT,
                completed_at TEXT,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (client_id) REFERENCES clients (id)
            )
        ''')
        
        # Bảng heartbeats (logs chi tiết)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT,
                timestamp TEXT,
                status TEXT,
                response_time REAL,
                FOREIGN KEY (client_id) REFERENCES clients (id)
            )
        ''')
        conn.commit()
    
    logger.info("✅ Database initialized")

# ==================== 📊 BIẾN TOÀN CỤC ====================
HEARTBEAT_TIMEOUT = 120  # 2 phút (giảm để phát hiện mất kết nối nhanh)
HEARTBEAT_CHECK_INTERVAL = 30  # Kiểm tra mỗi 30 giây

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
        if response.status_code != 200:
            logger.error(f"Line reply failed: {response.text}")
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
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
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
            logger.info(f"📤 Đã gửi tới group: {text[:50]}...")
        else:
            logger.error(f"❌ Gửi group thất bại: {text[:50]}...")
        return success
    return False

def save_heartbeat_log(client_id, status, response_time):
    """Lưu log heartbeat vào database"""
    try:
        with get_db() as conn:
            conn.execute('''
                INSERT INTO heartbeats (client_id, timestamp, status, response_time)
                VALUES (?, ?, ?, ?)
            ''', (client_id, datetime.now().isoformat(), status, response_time))
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Lỗi lưu heartbeat log: {e}")

def update_client_status(client_id, is_alive=True):
    """Cập nhật trạng thái client"""
    try:
        with get_db() as conn:
            conn.execute('''
                UPDATE clients 
                SET is_alive = ?, last_seen = ?
                WHERE id = ?
            ''', (1 if is_alive else 0, datetime.now().isoformat(), client_id))
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Lỗi cập nhật client status: {e}")

# ==================== ❤️ API HEARTBEAT 24/7 ====================

@app.route('/api/heartbeat/<client_id>', methods=['POST'])
def api_heartbeat(client_id):
    """
    🔥 ENDPOINT HEARTBEAT - Client gửi mỗi 30 giây
    """
    start_time = time.time()
    try:
        data = request.get_json() or {}
        client_status = data.get('status', 'active')
        username = data.get('username')
        heartbeat_counter = data.get('counter', 0)
        
        logger.debug(f"❤️ Heartbeat #{heartbeat_counter} từ {client_id[:12]}...")
        
        with clients_lock:
            now = datetime.now()
            now_iso = now.isoformat()
            
            if client_id in registered_clients:
                # CẬP NHẬT THỜI GIAN CUỐI CÙNG
                registered_clients[client_id].update({
                    'last_seen': now_iso,
                    'last_heartbeat': now_iso,
                    'status': client_status,
                    'is_alive': True
                })
                
                if 'heartbeat_count' in registered_clients[client_id]:
                    registered_clients[client_id]['heartbeat_count'] += 1
                else:
                    registered_clients[client_id]['heartbeat_count'] = 1
                
                if username:
                    registered_clients[client_id]['current_user'] = username
                    registered_clients[client_id]['session_status'] = 'active'
                else:
                    registered_clients[client_id]['current_user'] = None
                    registered_clients[client_id]['session_status'] = 'standby'
                
                # Nếu client này đang active session, cập nhật heartbeat cho session
                with session_lock:
                    if active_session["client_id"] == client_id:
                        active_session["last_heartbeat"] = now_iso
                
                # Cập nhật database
                update_client_status(client_id, True)
                
                # Tính response time
                response_time = time.time() - start_time
                save_heartbeat_log(client_id, 'success', response_time)
                
                # Kiểm tra nếu có lệnh đang chờ
                with commands_lock:
                    has_command = client_id in pending_commands
                    command = pending_commands.get(client_id) if has_command else None
                
                return jsonify({
                    "status": "ok", 
                    "message": "heartbeat_received",
                    "server_time": now_iso,
                    "session_active": active_session["is_active"],
                    "has_command": has_command,
                    "command": command,
                    "heartbeat_interval": 30,
                    "response_time_ms": round(response_time * 1000, 2)
                })
            else:
                # Client chưa đăng ký - TỰ ĐỘNG ĐĂNG KÝ LẠI
                logger.warning(f"❤️ Client không tồn tại: {client_id[:12]}... - Tự động đăng ký lại")
                
                new_client_data = {
                    "ip": request.remote_addr,
                    "registered_at": now_iso,
                    "last_seen": now_iso,
                    "last_heartbeat": now_iso,
                    "status": client_status,
                    "reconnected": True,
                    "user_agent": request.headers.get('User-Agent', 'Unknown'),
                    "heartbeat_count": 1,
                    "is_alive": True
                }
                
                if username:
                    new_client_data['current_user'] = username
                    new_client_data['session_status'] = 'active'
                else:
                    new_client_data['session_status'] = 'standby'
                
                registered_clients[client_id] = new_client_data
                
                # Lưu vào database
                try:
                    with get_db() as conn:
                        conn.execute('''
                            INSERT INTO clients (id, ip, registered_at, last_seen, last_heartbeat, 
                                               status, user_agent, session_status, heartbeat_count, is_alive)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            client_id,
                            request.remote_addr,
                            now_iso,
                            now_iso,
                            now_iso,
                            client_status,
                            request.headers.get('User-Agent', 'Unknown'),
                            'standby',
                            1,
                            1
                        ))
                        conn.commit()
                except Exception as e:
                    logger.error(f"❌ Lỗi lưu client vào DB: {e}")
                
                logger.info(f"✅ Tự động đăng ký lại client: {client_id[:12]}...")
                
                response_time = time.time() - start_time
                save_heartbeat_log(client_id, 'reconnected', response_time)
                
                return jsonify({
                    "status": "reconnected",
                    "message": "Client đã được đăng ký lại",
                    "client_id": client_id,
                    "session_active": active_session["is_active"],
                    "heartbeat_interval": 30
                })
                
    except Exception as e:
        logger.error(f"❌ Heartbeat error: {e}")
        response_time = time.time() - start_time
        save_heartbeat_log(client_id, 'error', response_time)
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 📡 API CLIENT STATUS ====================

@app.route('/api/client_status/<client_id>', methods=['GET'])
def api_client_status(client_id):
    """API kiểm tra trạng thái client chi tiết"""
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
                
                # Lấy thông tin từ database
                db_info = {}
                try:
                    with get_db() as conn:
                        cursor = conn.execute('''
                            SELECT heartbeat_count, is_alive, registered_at 
                            FROM clients WHERE id = ?
                        ''', (client_id,))
                        row = cursor.fetchone()
                        if row:
                            db_info = dict(row)
                except:
                    pass
                
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
                    "server_session_active": active_session["is_active"],
                    "database_info": db_info,
                    "connection_status": "active" if is_alive else "disconnected"
                })
            else:
                return jsonify({
                    "status": "not_found",
                    "message": "Client không tồn tại hoặc đã bị xóa",
                    "client_id": client_id,
                    "connection_status": "never_connected"
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
                    "full_id": client_id,
                    "is_alive": is_alive,
                    "seconds_since_last_hb": seconds_since_last_hb,
                    "status": client_data.get('status', 'unknown'),
                    "current_user": client_data.get('current_user'),
                    "session_status": client_data.get('session_status', 'unknown'),
                    "heartbeat_count": client_data.get('heartbeat_count', 0),
                    "registered_at": client_data.get('registered_at'),
                    "ip": client_data.get('ip', 'unknown')
                })
            
            # Lấy từ database để có số liệu chính xác
            db_clients = []
            try:
                with get_db() as conn:
                    cursor = conn.execute('SELECT id, is_alive, heartbeat_count FROM clients')
                    for row in cursor:
                        db_clients.append(dict(row))
            except:
                pass
            
            return jsonify({
                "status": "success",
                "total_clients": len(registered_clients),
                "alive_clients": len([c for c in clients_list if c['is_alive']]),
                "in_memory_clients": clients_list,
                "database_clients_count": len(db_clients),
                "server_time": now.isoformat(),
                "heartbeat_timeout": HEARTBEAT_TIMEOUT
            })
    except Exception as e:
        logger.error(f"❌ List clients error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 🎯 API CHO LOCAL DAEMON ====================

@app.route('/api/register_local', methods=['POST'])
def api_register_local():
    """API đăng ký client - CẢI THIỆN RETRY"""
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
                "heartbeat_count": 0,
                "is_alive": True
            }
        
        # Lưu vào database
        try:
            with get_db() as conn:
                conn.execute('''
                    INSERT INTO clients (id, ip, registered_at, last_seen, last_heartbeat, 
                                       status, user_agent, session_status, heartbeat_count, is_alive)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    client_id,
                    client_ip,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    "registered",
                    request.headers.get('User-Agent', 'Unknown'),
                    "standby",
                    0,
                    1
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Lỗi lưu client vào DB: {e}")
        
        logger.info(f"✅ Client đăng ký: {client_id[:12]}... từ IP: {client_ip}")
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
            "heartbeat_interval": 30,  # ⬅️ Client phải gửi mỗi 30 giây
            "heartbeat_endpoint": f"{SERVER_URL}/api/heartbeat/{client_id}",
            "server_time": datetime.now().isoformat(),
            "message": "Đăng ký thành công. Hãy bắt đầu gửi heartbeat để duy trì kết nối."
        }
        
        if has_command:
            logger.info(f"📨 Client {client_id[:12]}... có lệnh đang chờ: {command.get('type')}")
        
        return jsonify(response_data)
            
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_commands/<client_id>', methods=['GET'])
def api_get_commands(client_id):
    """API lấy lệnh - LUÔN CÓ SẴN"""
    try:
        # Cập nhật last seen
        with clients_lock:
            if client_id in registered_clients:
                registered_clients[client_id]['last_seen'] = datetime.now().isoformat()
                registered_clients[client_id]['is_alive'] = True
        
        logger.debug(f"🔍 Client {client_id[:12]}... đang check command")
        
        with commands_lock:
            if client_id in pending_commands:
                command = pending_commands[client_id]
                logger.info(f"📤 Gửi command đến {client_id[:12]}...: {command.get('type')}")
                
                # Lưu command vào database
                try:
                    with get_db() as conn:
                        conn.execute('''
                            INSERT INTO commands (id, client_id, type, data, created_at, status)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (
                            command.get('id'),
                            client_id,
                            command.get('type'),
                            json.dumps(command),
                            datetime.now().isoformat(),
                            'sent'
                        ))
                        conn.commit()
                except Exception as e:
                    logger.error(f"❌ Lỗi lưu command vào DB: {e}")
                
                return jsonify({
                    "has_command": True,
                    "command": command,
                    "timestamp": datetime.now().isoformat()
                })
            else:
                # Trả về empty response nhưng vẫn giữ kết nối
                return jsonify({
                    "has_command": False,
                    "timestamp": datetime.now().isoformat(),
                    "message": "no_command",
                    "heartbeat_reminder": True
                })
    except Exception as e:
        logger.error(f"❌ Get command error: {e}")
        return jsonify({"has_command": False, "error": str(e)})

@app.route('/api/start_session', methods=['POST'])
def api_start_session():
    """API bắt đầu phiên - CẢI THIỆN"""
    try:
        data = request.get_json()
        username = data.get('username')
        client_id = data.get('user_id')
        
        if not username or not client_id:
            return jsonify({"status": "error", "message": "Thiếu username hoặc client_id"})
        
        logger.info(f"📥 Start session: {username} (Client: {client_id[:12]})")
        
        with session_lock:
            # KIỂM TRA PHIÊN HIỆN TẠI
            if active_session["is_active"]:
                current_user = active_session["username"]
                logger.warning(f"Session conflict: {current_user} đang active")
                return jsonify({
                    "status": "conflict",
                    "message": f"Phiên làm việc đang được sử dụng bởi {current_user}"
                })
            
            # KIỂM TRA CLIENT CÓ TỒN TẠI VÀ CÒN SỐNG KHÔNG
            with clients_lock:
                if client_id not in registered_clients:
                    logger.warning(f"Client không tồn tại: {client_id}")
                    return jsonify({
                        "status": "error",
                        "message": "Client chưa đăng ký hoặc đã disconnect"
                    })
                
                # Kiểm tra client có còn sống không
                last_hb = registered_clients[client_id].get('last_heartbeat')
                if last_hb:
                    try:
                        last_hb_time = datetime.fromisoformat(last_hb)
                        if (datetime.now() - last_hb_time).total_seconds() > 120:
                            logger.warning(f"Client không phản hồi heartbeat: {client_id}")
                            return jsonify({
                                "status": "error",
                                "message": "Client không phản hồi. Vui lòng kiểm tra kết nối."
                            })
                    except:
                        pass
            
            # BẮT ĐẦU PHIÊN MỚI
            session_id = generate_session_id()
            now = datetime.now()
            
            active_session.update({
                "is_active": True,
                "username": username,
                "start_time": now.isoformat(),
                "session_id": session_id,
                "client_id": client_id,
                "login_time": now.isoformat(),
                "last_heartbeat": now.isoformat()
            })
            
            logger.info(f"✅ ĐÃ BẮT ĐẦU PHIÊN: {username} - Session: {session_id[:10]}...")
        
        # Cập nhật thông tin client
        with clients_lock:
            if client_id in registered_clients:
                registered_clients[client_id].update({
                    'current_user': username,
                    'status': 'in_session',
                    'session_status': 'active',
                    'is_alive': True
                })
        
        # Lưu session vào database
        try:
            with get_db() as conn:
                conn.execute('''
                    INSERT INTO sessions (id, client_id, username, start_time, reason)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session_id, client_id, username, now.isoformat(), 'started'))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Lỗi lưu session vào DB: {e}")
        
        # Gửi thông báo LINE
        send_to_group(f"🎯 **BẮT ĐẦU PHIÊN**\n👤 User: {username}\n🆔 Client: {client_id[:12]}\n⏰ {now.strftime('%H:%M:%S')}")
        
        return jsonify({
            "status": "started",
            "message": f"Đã bắt đầu phiên làm việc cho {username}",
            "session_id": session_id,
            "session_info": {
                "username": username,
                "start_time": active_session["start_time"],
                "session_id": session_id,
                "client_id": client_id
            },
            "heartbeat_required": True,
            "heartbeat_interval": 30,
            "server_time": now.isoformat()
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
        
        logger.info(f"📥 End session: {username}, reason: {reason}, client: {client_id[:12] if client_id else 'N/A'}")
        
        with session_lock:
            if active_session["is_active"]:
                ended_user = active_session["username"]
                ended_client = active_session["client_id"]
                start_time = active_session["start_time"]
                
                # Xác minh client
                if client_id and client_id != ended_client:
                    logger.warning(f"Client mismatch: {client_id} != {ended_client}")
                
                # Tính thời lượng session
                duration_seconds = 0
                if start_time:
                    try:
                        start_dt = datetime.fromisoformat(start_time)
                        duration_seconds = int((datetime.now() - start_dt).total_seconds())
                    except:
                        pass
                
                # Xóa lệnh pending của client này
                with commands_lock:
                    if ended_client in pending_commands:
                        del pending_commands[ended_client]
                        logger.info(f"🧹 Đã xóa lệnh pending của client {ended_client[:12]}...")
                
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
                
                logger.info(f"✅ ĐÃ KẾT THÚC PHIÊN: {ended_user} (duration: {duration_seconds}s)")
                
                # Cập nhật thông tin client
                with clients_lock:
                    if ended_client in registered_clients:
                        registered_clients[ended_client].update({
                            'current_user': None,
                            'status': 'standby',
                            'session_status': 'ended'
                        })
                
                # Cập nhật session trong database
                try:
                    with get_db() as conn:
                        conn.execute('''
                            UPDATE sessions 
                            SET end_time = ?, reason = ?, duration_seconds = ?
                            WHERE client_id = ? AND end_time IS NULL
                        ''', (
                            datetime.now().isoformat(),
                            reason,
                            duration_seconds,
                            ended_client
                        ))
                        conn.commit()
                except Exception as e:
                    logger.error(f"❌ Lỗi cập nhật session vào DB: {e}")
                
                # Gửi thông báo LINE
                if message:
                    send_to_group(message)
                else:
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    duration_text = f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"
                    
                    send_to_group(f"✅ **KẾT THÚC PHIÊN**\n👤 User: {ended_user}\n⏱️ Thời gian: {duration_text}\n📌 Lý do: {reason}")
                
                return jsonify({
                    "status": "ended",
                    "message": f"Đã kết thúc phiên của {ended_user}",
                    "duration_seconds": duration_seconds,
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

# ... (CÁC API KHÁC GIỮ NGUYÊN) ...

# ==================== 🧹 CLEANUP THREAD 24/7 ====================

def cleanup_old_clients():
    """Dọn dẹp client không hoạt động - CHẠY LIÊN TỤC"""
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
                            
                            # 2 phút không heartbeat mới xóa
                            if (now - last_heartbeat) > timedelta(seconds=HEARTBEAT_TIMEOUT):
                                # Kiểm tra xem client có đang active session không
                                with session_lock:
                                    if active_session.get('client_id') != client_id:
                                        clients_to_remove.append(client_id)
                                        # Cập nhật database
                                        update_client_status(client_id, False)
                        except:
                            clients_to_remove.append(client_id)
                    
                # Xóa client cũ
                for client_id in clients_to_remove:
                    del registered_clients[client_id]
                    logger.info(f"🧹 Đã xóa client không hoạt động (sau {HEARTBEAT_TIMEOUT}s): {client_id[:12]}...")
                    
                    # Xóa lệnh pending của client này
                    with commands_lock:
                        if client_id in pending_commands:
                            del pending_commands[client_id]
            
            logger.debug(f"🧹 Cleanup 24/7: {len(registered_clients)} clients đang được theo dõi")
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ==================== 🌐 WEBHOOK LINE ====================

@app.route('/webhook', methods=['POST'])
def line_webhook():
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        logger.info(f"📥 Nhận {len(events)} events từ LINE")
        
        for event in events:
            event_type = event.get('type')
            reply_token = event.get('replyToken')
            user_id = event.get('source', {}).get('userId')
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip()
                logger.info(f"💬 Tin nhắn từ {user_id[:10] if user_id else 'unknown'}: {message_text[:50]}...")
                
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
                            # Chỉ gửi cho client đang sống
                            for client_id, client_data in registered_clients.items():
                                last_hb = client_data.get('last_heartbeat')
                                is_alive = False
                                if last_hb:
                                    try:
                                        last_hb_time = datetime.fromisoformat(last_hb)
                                        is_alive = (datetime.now() - last_hb_time).total_seconds() < 90
                                    except:
                                        pass
                                
                                if is_alive:
                                    with commands_lock:
                                        pending_commands[client_id] = command_data
                                    sent_count += 1
                                    logger.info(f"📨 Gửi lệnh login đến client: {client_id[:12]}...")
                        
                        if sent_count == 0:
                            send_line_reply(reply_token, 
                                f"❌ **Không có client nào đang kết nối!**\n"
                                f"📌 Kiểm tra local daemon đã chạy chưa?\n"
                                f"💡 Client cần gửi heartbeat mỗi 30s để duy trì kết nối"
                            )
                        else:
                            send_line_reply(reply_token, 
                                f"✅ **Đã nhận lệnh đăng nhập cho {username}**\n"
                                f"📤 Đang gửi đến {sent_count} client đang sống...\n"
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
                                logger.info(f"📤 Gửi lệnh stop đến client: {client_id[:12]}...")
                            
                            send_line_reply(reply_token, f"🚪 **Đang yêu cầu {current_user} thoát web...**")
                        else:
                            send_line_reply(reply_token, "❌ Không có phiên làm việc nào đang chạy")
                
                # LỆNH STATUS
                elif message_text in ['.status', '.trangthai']:
                    with session_lock:
                        if active_session["is_active"]:
                            start_time = active_session["start_time"]
                            last_heartbeat = active_session.get("last_heartbeat")
                            client_id = active_session["client_id"]
                            
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
                                    if hb_diff < 30:
                                        heartbeat_info = "✅ Kết nối live"
                                    elif hb_diff < 60:
                                        heartbeat_info = "⚠️ HB: 30s trước"
                                    else:
                                        heartbeat_info = f"🔴 HB: {int(hb_diff)}s trước"
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
🆔 Client: {client_id[:12] if client_id else 'N/A'}

📊 **HỆ THỐNG**
🟢 Client kết nối: {alive_clients}/{total_clients}
❤️ Heartbeat: Mỗi 30s
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
                
                # LỆNH CLIENTS
                elif message_text == '.clients':
                    with clients_lock:
                        total_clients = len(registered_clients)
                        alive_clients = 0
                        clients_info = []
                        
                        for client_id, client_data in registered_clients.items():
                            last_hb_str = client_data.get('last_heartbeat')
                            is_alive = False
                            hb_ago = "N/A"
                            
                            if last_hb_str:
                                try:
                                    last_hb = datetime.fromisoformat(last_hb_str)
                                    diff_seconds = (datetime.now() - last_hb).total_seconds()
                                    is_alive = diff_seconds < 90
                                    hb_ago = f"{int(diff_seconds)}s"
                                except:
                                    pass
                            
                            if is_alive:
                                alive_clients += 1
                            
                            client_status = "🟢" if is_alive else "🔴"
                            user = client_data.get('current_user', 'none')
                            status = client_data.get('status', 'unknown')
                            
                            clients_info.append(f"{client_status} {client_id[:10]}... | {user} | {status} | HB:{hb_ago}")
                    
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

# ==================== 🚀 KHỞI ĐỘNG ====================

if __name__ == "__main__":
    # Khởi tạo database
    init_db()
    
    port = int(os.environ.get('PORT', 5002))
    
    print(f"""
🚀 ========================================
🚀 SERVER START - 24/7 LIÊN TỤC KẾT NỐI
🚀 ========================================
🌐 Server: {SERVER_URL}
👥 Group: {LINE_GROUP_ID}

🎯 TÍNH NĂNG KẾT NỐI LIÊN TỤC:
• Heartbeat system - Client gửi mỗi 30s
• Auto-reconnect - Tự động đăng ký lại
• 2 phút timeout - Phát hiện mất kết nối nhanh
• Database persistent - Lưu trữ lịch sử
• Status real-time - Biết client nào đang sống

📊 HIỆN TẠI:
• Session: {'ACTIVE' if active_session["is_active"] else 'STANDBY'}
• User: {active_session["username"] or 'None'}
• Clients: {len(registered_clients)}
• Heartbeat: Mỗi 30s / Timeout 2 phút
• Database: Đã sẵn sàng
• Time: {datetime.now().strftime('%H:%M:%S')}
========================================
    """)
    
    # Bắt đầu cleanup thread
    stop_cleanup = False
    cleanup_thread = threading.Thread(target=cleanup_old_clients, daemon=True)
    cleanup_thread.start()
    logger.info("✅ Đã bắt đầu cleanup thread 24/7")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 Dừng server...")
    finally:
        stop_cleanup = True
        if cleanup_thread:
            cleanup_thread.join(timeout=2)
