from flask import Flask, request, jsonify
import requests
import time
import logging
import os
from datetime import datetime, timedelta
import threading
import hashlib
import hmac
import base64
from functools import wraps

app = Flask(__name__)

# ==================== CẤU HÌNH ====================
LINE_CHANNEL_TOKEN = "7HxJf6ykrTfMuz918kpokPMNUZOqpRv8FcGoJM/dkP8uIaqrwU5xFC+M8RoLUxYkkfZdrokoC9pMQ3kJv/SKxXTWTH1KhUe9fdXsNqVZXTA1w21+Wp1ywTQxZQViR2DVqR8w6CPvQpFJCbdvynuvSQdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "af29ee5866ddf060e20024b1c08bc2cf"
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
PING_INTERVAL = 30

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_server.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== QUẢN LÝ DỮ LIỆU ====================
group_queues = {}
local_connections = {}
job_queue = []
active_automations = {}
user_sessions = {}  # Thêm: Lưu session của user để login lại nhanh

# ==================== TIỆN ÍCH BẢO MẬT ====================
def verify_signature(payload, signature):
    """Xác minh webhook signature từ LINE"""
    try:
        if not LINE_CHANNEL_SECRET:
            return False
            
        channel_secret_bytes = LINE_CHANNEL_SECRET.encode('utf-8')
        hash_digest = hmac.new(channel_secret_bytes, payload, hashlib.sha256).digest()
        computed_signature = base64.b64encode(hash_digest).decode('utf-8')
        
        return hmac.compare_digest(computed_signature, signature)
        
    except Exception as e:
        logger.error(f"❌ Lỗi verify signature: {e}")
        return False

def require_local_auth(f):
    """Decorator xác thực máy local"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            data = request.json
            local_id = data.get('local_id')
            
            if not local_id:
                return jsonify({"status": "error", "message": "Missing local_id"}), 400
            
            if local_id not in local_connections:
                if request.endpoint == 'register_local':
                    return f(*args, **kwargs)
                return jsonify({"status": "error", "message": "Local not registered"}), 401
            
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return decorated_function

# ==================== TIỆN ÍCH LINE API ====================
def send_line_message_direct(to_id, line_token, text, chat_type="user"):
    """Gửi tin nhắn LINE trực tiếp"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {line_token}'
        }
        
        data = {
            'to': to_id,
            'messages': [{"type": "text", "text": text}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ Đã gửi tin nhắn đến {to_id[:15]}...")
            return True
        else:
            logger.error(f"❌ Gửi tin nhắn thất bại: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Lỗi gửi tin nhắn: {e}")
        return False

# ==================== QUẢN LÝ MÁY LOCAL ====================
def cleanup_inactive_locals():
    """Dọn dẹp máy local không hoạt động"""
    try:
        current_time = datetime.now()
        inactive_locals = []
        
        for local_id, info in local_connections.items():
            last_ping = info.get("last_ping")
            if not last_ping:
                inactive_locals.append(local_id)
                continue
            
            if isinstance(last_ping, str):
                last_ping = datetime.fromisoformat(last_ping.replace('Z', '+00:00'))
            
            time_diff = (current_time - last_ping).total_seconds()
            
            if time_diff > 120:
                inactive_locals.append(local_id)
                logger.info(f"🔄 Dọn local không hoạt động: {local_id}")
        
        for local_id in inactive_locals:
            job = local_connections[local_id].get("current_job")
            if job:
                user_id = job.get("data", {}).get("user_id")
                job_id = job.get("job_id")
                
                if user_id in active_automations:
                    send_line_message_direct(
                        user_id,
                        LINE_CHANNEL_TOKEN,
                        "⚠️ Máy local mất kết nối. Vui lòng login lại.",
                        "user"
                    )
                    del active_automations[user_id]
                
                job_queue.insert(0, job)
                logger.info(f"🔄 Đưa job {job_id} trở lại queue")
            
            del local_connections[local_id]
            logger.info(f"🧹 Đã xóa local {local_id}")
        
        return len(inactive_locals)
    except Exception as e:
        logger.error(f"❌ Lỗi cleanup: {e}")
        return 0

def assign_job_to_local(local_id, job):
    """Gán job cho máy local"""
    try:
        if local_id not in local_connections:
            return False
        
        local_connections[local_id]["current_job"] = job
        local_connections[local_id]["status"] = "busy"
        local_connections[local_id]["last_ping"] = datetime.now()
        
        user_id = job.get("data", {}).get("user_id")
        if user_id:
            active_automations[user_id] = {
                "local_id": local_id,
                "job_id": job.get("job_id"),
                "username": job.get("data", {}).get("username"),
                "started_at": datetime.now().isoformat()
            }
        
        logger.info(f"✅ Đã gán job {job.get('job_id')} cho {local_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Lỗi gán job: {e}")
        return False

# ==================== QUẢN LÝ JOB QUEUE ====================
def create_job(user_id, username, password, group_id=None):
    """Tạo job mới"""
    try:
        job_id = f"JOB_{datetime.now().strftime('%Y%m%d%H%M%S')}_{user_id[:8]}"
        
        job = {
            "job_id": job_id,
            "type": "automation",
            "data": {
                "user_id": user_id,
                "username": username,
                "password": password,
                "group_id": group_id,
                "line_token": LINE_CHANNEL_TOKEN
            },
            "created_at": datetime.now().isoformat(),
            "status": "pending"
        }
        
        job_queue.append(job)
        logger.info(f"📥 Đã tạo job {job_id} cho {username}")
        
        return job_id
    except Exception as e:
        logger.error(f"❌ Lỗi tạo job: {e}")
        return None

def process_job_queue():
    """Xử lý job queue"""
    try:
        if not job_queue:
            return 0
        
        jobs_assigned = 0
        ready_locals = []
        
        for local_id, info in local_connections.items():
            if info.get("status") == "ready":
                last_ping = info.get("last_ping")
                if isinstance(last_ping, str):
                    last_ping = datetime.fromisoformat(last_ping.replace('Z', '+00:00'))
                
                time_diff = (datetime.now() - last_ping).total_seconds()
                
                if time_diff < 60:
                    ready_locals.append(local_id)
        
        for local_id in ready_locals:
            if job_queue:
                job = job_queue.pop(0)
                if assign_job_to_local(local_id, job):
                    jobs_assigned += 1
                    logger.info(f"✅ Đã gán job {job.get('job_id')} cho {local_id}")
                else:
                    job_queue.insert(0, job)
        
        return jobs_assigned
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý queue: {e}")
        return 0

# ==================== XỬ LÝ LỆNH THOÁT WEB ====================
def handle_exit_command(user_id, chat_id, chat_type, group_id):
    """Xử lý lệnh thoát web - THOÁT HOÀN TOÀN NHƯNG LƯU THÔNG TIN"""
    try:
        logger.info(f"🛑 Nhận lệnh 'thoát web' từ {user_id}")
        
        # 1. Xóa khỏi active automations
        if user_id in active_automations:
            job_info = active_automations[user_id]
            username = job_info.get("username", "unknown")
            local_id = job_info.get("local_id")
            
            # Lưu thông tin session để login lại nhanh
            if username:
                user_sessions[user_id] = {
                    "username": username,
                    "last_exit": datetime.now().isoformat(),
                    "group_id": group_id
                }
                logger.info(f"💾 Đã lưu session cho {username}")
            
            # Xóa khỏi active
            del active_automations[user_id]
            logger.info(f"🗑️ Đã xóa {username} khỏi active automations")
            
            # Thông báo cho local (nếu có)
            if local_id and local_id in local_connections:
                logger.info(f"📢 Thông báo 'thoát web' cho local {local_id}")
        
        # 2. Xóa job khỏi queue
        for i, job in enumerate(job_queue):
            if job.get("data", {}).get("user_id") == user_id:
                removed_job = job_queue.pop(i)
                logger.info(f"🗑️ Đã xóa job của {user_id} khỏi queue")
                break
        
        # 3. Xử lý trong group
        if group_id and group_id in group_queues:
            queue = group_queues[group_id]
            
            # Nếu là người đang sử dụng
            if queue["current_user"] == user_id:
                username = queue.get("current_username", "unknown")
                
                # GIẢI PHÓNG SLOT NGAY
                queue["current_user"] = None
                queue["current_username"] = None
                
                logger.info(f"🔄 Đã giải phóng slot trong group {group_id}")
                
                # Thông báo trong group
                send_line_message_direct(
                    group_id,
                    LINE_CHANNEL_TOKEN,
                    f"🛑 {username} đã thoát web. Slot đã được giải phóng!",
                    "group"
                )
                
                # KHÔNG tự động chuyển sang người tiếp theo
                # Để user có thể login lại ngay nếu muốn
                
            # Xóa khỏi waiting users
            for i, waiting_user in enumerate(queue["waiting_users"]):
                if waiting_user["user_id"] == user_id:
                    removed_user = queue["waiting_users"].pop(i)
                    logger.info(f"🗑️ Đã xóa {removed_user['username']} khỏi hàng chờ")
                    break
        
        # 4. Gửi thông báo cho user
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            "✅ ĐÃ THOÁT WEB THÀNH CÔNG!\n\n💡 Bạn có thể login lại ngay bằng lệnh:\n.login username:password",
            chat_type
        )
        
        # 5. Process queue để local có thể nhận job mới
        process_job_queue()
        
        logger.info(f"✅ Đã xử lý lệnh 'thoát web' cho {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý thoát web: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            f"❌ Lỗi thoát web: {str(e)[:100]}",
            chat_type
        )

# ==================== XỬ LÝ LỆNH LOGIN ====================
def handle_login_command(command, user_id, chat_id, chat_type, group_id):
    """Xử lý lệnh login - CHO PHÉP LOGIN LẠI NGAY SAU KHI THOÁT"""
    try:
        credentials = command[6:]  # Bỏ "login "
        
        if ':' not in credentials:
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "❌ Sai cú pháp! Dùng: .login username:password\nVí dụ: .login employee01:123456",
                chat_type
            )
            return
        
        username, password = credentials.split(':', 1)
        
        logger.info(f"🔐 User {user_id} muốn login với {username}")
        
        # KIỂM TRA ĐẶC BIỆT: Nếu user vừa thoát xong, cho phép login lại ngay
        if user_id in user_sessions:
            logger.info(f"🔄 User {username} vừa thoát xong, cho phép login lại ngay")
            # Xóa session cũ
            del user_sessions[user_id]
        
        # Kiểm tra trong group
        if group_id:
            if group_id not in group_queues:
                group_queues[group_id] = {
                    "current_user": None,
                    "current_username": None,
                    "waiting_users": []
                }
            
            queue = group_queues[group_id]
            
            # QUY TẮC MỚI: 
            # 1. Nếu slot trống -> login ngay
            # 2. Nếu slot đang dùng bởi chính mình -> login lại ngay (sau khi thoát)
            # 3. Nếu slot đang dùng bởi người khác -> vào hàng chờ
            
            if queue["current_user"] is None:
                # Slot trống, login ngay
                queue["current_user"] = user_id
                queue["current_username"] = username
                
                logger.info(f"✅ {username} login ngay (slot trống)")
                
            elif queue["current_user"] == user_id:
                # User đang là current_user (vừa thoát xong)
                # Cho phép login lại ngay
                queue["current_user"] = user_id
                queue["current_username"] = username
                
                logger.info(f"🔄 {username} login lại ngay (vừa thoát xong)")
                
            else:
                # Slot đang bận bởi người khác, vào hàng chờ
                
                # Kiểm tra đã trong hàng chờ chưa
                for waiting_user in queue["waiting_users"]:
                    if waiting_user.get("user_id") == user_id:
                        position = queue["waiting_users"].index(waiting_user) + 1
                        send_line_message_direct(
                            chat_id,
                            LINE_CHANNEL_TOKEN,
                            f"⏳ Bạn đã trong hàng chờ! Vị trí: {position}",
                            chat_type
                        )
                        return
                
                # Thêm vào hàng chờ
                queue["waiting_users"].append({
                    "user_id": user_id,
                    "username": username,
                    "password": password
                })
                
                position = len(queue["waiting_users"])
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    f"📋 ĐÃ THÊM VÀO HÀNG CHỜ\nVị trí: {position}\n⏳ Vui lòng đợi đến lượt...",
                    chat_type
                )
                return
        
        # Kiểm tra user đã có job đang chạy chưa
        if user_id in active_automations:
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "⏳ Bạn đã có automation đang chạy! Vui lòng đợi hoàn thành.",
                chat_type
            )
            return
        
        # Tạo job
        job_id = create_job(user_id, username, password, group_id)
        
        if not job_id:
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "❌ Không thể tạo job, vui lòng thử lại!",
                chat_type
            )
            return
        
        # Gửi thông báo
        if group_id:
            if queue["current_user"] == user_id:
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    f"✅ ĐÃ NHẬN LỆNH TỪ {username}\n🔄 Đang chờ máy local nhận job...",
                    chat_type
                )
        else:
            # User riêng lẻ
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                f"✅ ĐÃ NHẬN LỆNH TỪ {username}\n🔄 Đang chờ máy local nhận job...",
                chat_type
            )
        
        # Xử lý job queue ngay
        process_job_queue()
        
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý login: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            f"❌ Lỗi login: {str(e)[:100]}",
            chat_type
        )

# ==================== XỬ LÝ LỆNH STATUS ====================
def handle_status_command(user_id, chat_id, chat_type, group_id):
    """Xử lý lệnh status"""
    try:
        if chat_type == "user":
            if user_id in active_automations:
                info = active_automations[user_id]
                status_text = f"📊 TRẠNG THÁI CÁ NHÂN:\n• Đang chạy: ✅ CÓ\n• Username: {info.get('username')}\n• Bắt đầu: {info.get('started_at', 'Unknown')}"
            else:
                in_queue = any(job.get("data", {}).get("user_id") == user_id for job in job_queue)
                if in_queue:
                    status_text = "📊 TRẠNG THÁI CÁ NHÂN:\n• Đang chạy: ❌ KHÔNG\n• Trạng thái: ⏳ ĐANG CHỜ TRONG HÀNG ĐỢI"
                else:
                    status_text = "📊 TRẠNG THÁI CÁ NHÂN:\n• Đang chạy: ❌ KHÔNG\n• Trạng thái: 🟢 SẴN SÀNG"
        else:
            if group_id in group_queues:
                queue = group_queues[group_id]
                
                if queue["current_user"]:
                    status_text = f"📊 TRẠNG THÁI GROUP:\n• Đang sử dụng: {queue['current_username']}\n• Số người chờ: {len(queue['waiting_users'])}"
                    
                    if queue["waiting_users"]:
                        status_text += "\n\n📋 HÀNG CHỜ:\n"
                        for i, user in enumerate(queue["waiting_users"], 1):
                            status_text += f"{i}. {user['username']}\n"
                else:
                    status_text = "📊 TRẠNG THÁI GROUP:\n• Đang sử dụng: 🟢 KHÔNG CÓ\n• Số người chờ: 0\n• Trạng thái: SẴN SÀNG"
            else:
                status_text = "📊 TRẠNG THÁI GROUP:\n• Đang sử dụng: 🟢 KHÔNG CÓ\n• Trạng thái: SẴN SÀNG"
        
        # Thêm thông tin hệ thống
        online_locals = 0
        for local_id, info in local_connections.items():
            last_ping = info.get("last_ping")
            if last_ping:
                if isinstance(last_ping, str):
                    try:
                        last_ping = datetime.fromisoformat(last_ping.replace('Z', '+00:00'))
                    except:
                        last_ping = datetime.now()
                time_diff = (datetime.now() - last_ping).total_seconds()
                if time_diff < 60:
                    online_locals += 1
        
        status_text += f"\n\n⚙️ HỆ THỐNG:\n• Máy local online: {online_locals}/{len(local_connections)}\n• Job đang chờ: {len(job_queue)}\n• Server: ✅ ONLINE"
        
        send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, status_text, chat_type)
        
    except Exception as e:
        logger.error(f"❌ Lỗi status: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            "❌ Lỗi lấy trạng thái",
            chat_type
        )

# ==================== XỬ LÝ LỆNH QUEUE ====================
def handle_queue_command(chat_id, chat_type, group_id):
    """Xử lý lệnh xem hàng chờ"""
    try:
        if not group_id or group_id not in group_queues:
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "📋 HÀNG CHỜ TRỐNG",
                chat_type
            )
            return
        
        queue = group_queues[group_id]
        
        if not queue["current_user"] and not queue["waiting_users"]:
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "📋 HÀNG CHỜ TRỐNG\n🟢 Không có ai sử dụng hoặc chờ",
                chat_type
            )
            return
        
        queue_text = "📋 DANH SÁCH HÀNG CHỜ\n\n"
        
        if queue["current_user"]:
            queue_text += f"🎯 ĐANG SỬ DỤNG:\n• {queue['current_username']}\n\n"
        
        if queue["waiting_users"]:
            queue_text += "⏳ ĐANG CHỜ:\n"
            for i, user in enumerate(queue["waiting_users"], 1):
                queue_text += f"{i}. {user['username']}\n"
        
        # Thêm thông tin hệ thống
        online_locals = 0
        for local_id, info in local_connections.items():
            last_ping = info.get("last_ping")
            if last_ping:
                if isinstance(last_ping, str):
                    try:
                        last_ping = datetime.fromisoformat(last_ping.replace('Z', '+00:00'))
                    except:
                        last_ping = datetime.now()
                time_diff = (datetime.now() - last_ping).total_seconds()
                if time_diff < 60:
                    online_locals += 1
        
        queue_text += f"\n⚙️ THỐNG KÊ:\n• Máy local online: {online_locals}\n• Tổng job chờ: {len(job_queue)}"
        
        send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, queue_text, chat_type)
        
    except Exception as e:
        logger.error(f"❌ Lỗi queue: {e}")

# ==================== ENDPOINTS LOCAL API ====================
@app.route('/register_local', methods=['POST'])
@require_local_auth
def register_local():
    """Đăng ký máy local với server"""
    try:
        data = request.json
        local_id = data.get('local_id')
        status = data.get('status', 'ready')
        
        if local_id in local_connections:
            local_connections[local_id]["last_ping"] = datetime.now()
            local_connections[local_id]["status"] = status
            logger.info(f"🔄 Cập nhật local {local_id}")
        else:
            local_connections[local_id] = {
                "last_ping": datetime.now(),
                "status": status,
                "current_job": None,
                "registered_at": datetime.now().isoformat()
            }
            logger.info(f"✅ Đăng ký local mới: {local_id}")
        
        if status == "ready":
            process_job_queue()
        
        return jsonify({
            "status": "success",
            "local_id": local_id,
            "message": f"Đã đăng ký local {local_id}",
            "server_time": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Lỗi register local: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/ping', methods=['POST'])
@require_local_auth
def handle_ping():
    """Nhận ping từ máy local"""
    try:
        data = request.json
        local_id = data.get('local_id')
        status = data.get('status', 'ready')
        current_job = data.get('current_job')
        
        if local_id not in local_connections:
            return jsonify({
                "status": "not_registered",
                "message": "Local chưa đăng ký"
            }), 404
        
        local_connections[local_id]["last_ping"] = datetime.now()
        local_connections[local_id]["status"] = status
        
        if current_job:
            local_connections[local_id]["current_job"] = current_job
        
        has_job = False
        job_to_send = None
        
        if status == "ready":
            process_job_queue()
            
            if local_connections[local_id].get("current_job"):
                has_job = True
                job_to_send = local_connections[local_id]["current_job"]
        
        response_data = {
            "status": "pong",
            "local_id": local_id,
            "has_job": has_job,
            "job": job_to_send,
            "server_time": datetime.now().isoformat(),
            "message": "Ping received"
        }
        
        logger.info(f"📡 Ping từ {local_id} - Job: {has_job}")
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Lỗi ping: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/job_complete', methods=['POST'])
@require_local_auth
def job_complete():
    """Nhận thông báo hoàn thành job từ local"""
    try:
        data = request.json
        local_id = data.get('local_id')
        job_id = data.get('job_id')
        success = data.get('success', True)
        message = data.get('message', '')
        
        if local_id not in local_connections:
            return jsonify({"status": "error", "message": "Local not found"}), 404
        
        # Lấy thông tin user từ job
        job_info = local_connections[local_id].get("current_job")
        user_id = None
        username = None
        
        if job_info:
            user_id = job_info.get("data", {}).get("user_id")
            username = job_info.get("data", {}).get("username")
        
        # Reset local
        local_connections[local_id]["status"] = "ready"
        local_connections[local_id]["current_job"] = None
        local_connections[local_id]["last_ping"] = datetime.now()
        
        # Xóa khỏi active automations
        if user_id and user_id in active_automations:
            del active_automations[user_id]
            logger.info(f"✅ Đã xóa {username} khỏi active automations")
        
        # Xử lý trong group
        if user_id:
            for group_id, queue in group_queues.items():
                if queue["current_user"] == user_id:
                    # GIẢI PHÓNG SLOT TRONG GROUP
                    queue["current_user"] = None
                    queue["current_username"] = None
                    logger.info(f"🔄 Đã giải phóng slot trong group {group_id}")
                    
                    # KHÔNG tự động chuyển sang người tiếp theo
                    # Để user có thể login lại ngay nếu muốn
                    break
        
        logger.info(f"✅ Job {job_id} hoàn thành - Success: {success}")
        
        # Gửi thông báo cho user (nếu có message)
        if message and user_id:
            send_line_message_direct(
                user_id,
                LINE_CHANNEL_TOKEN,
                message,
                "user"
            )
        
        # Process queue để nhận job mới
        process_job_queue()
        
        return jsonify({
            "status": "acknowledged",
            "job_id": job_id,
            "message": "Job completion acknowledged"
        })
        
    except Exception as e:
        logger.error(f"❌ Lỗi job complete: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/check_exit', methods=['POST'])
@require_local_auth
def check_exit():
    """API để local kiểm tra lệnh thoát"""
    try:
        data = request.json
        local_id = data.get('local_id')
        user_id = data.get('user_id')
        
        # Kiểm tra xem user này có trong active automations không
        # Nếu không có nghĩa là đã bị xóa (đã thoát)
        if user_id and user_id not in active_automations:
            logger.info(f"🛑 User {user_id} không còn trong active, yêu cầu local thoát")
            return jsonify({
                "should_exit": True,
                "message": "User không còn trong active automations"
            })
        
        # Kiểm tra xem local có đang chạy job của user này không
        if local_id in local_connections:
            job = local_connections[local_id].get("current_job")
            if job:
                job_user_id = job.get("data", {}).get("user_id")
                if job_user_id == user_id and user_id not in active_automations:
                    logger.info(f"🛑 Job của {user_id} đã bị xóa, yêu cầu local thoát")
                    return jsonify({
                        "should_exit": True,
                        "message": "Job đã bị xóa khỏi hệ thống"
                    })
        
        return jsonify({
            "should_exit": False,
            "message": "Tiếp tục chạy"
        })
        
    except Exception as e:
        logger.error(f"❌ Lỗi check_exit: {e}")
        return jsonify({
            "should_exit": False,
            "message": f"Error: {str(e)}"
        })

@app.route('/check_local_exit', methods=['POST'])
def check_local_exit():
    """API đơn giản để local kiểm tra thoát - KHÔNG cần auth để dễ kiểm tra"""
    try:
        data = request.json
        local_id = data.get('local_id')
        
        if not local_id:
            return jsonify({
                "should_exit": False,
                "message": "Missing local_id"
            })
        
        # Logic đơn giản: Nếu local đang chạy job mà job không còn trong hệ thống
        if local_id in local_connections:
            job = local_connections[local_id].get("current_job")
            if job:
                job_id = job.get("job_id")
                user_id = job.get("data", {}).get("user_id")
                
                # KIỂM TRA 1: Job có còn trong job_queue không?
                job_in_queue = any(j.get("job_id") == job_id for j in job_queue)
                
                # KIỂM TRA 2: User có còn trong active automations không?
                user_in_active = user_id in active_automations
                
                # KIỂM TRA 3: Job có bị đánh dấu là đã thoát không?
                job_exit_marker = f"EXIT_{user_id}"
                
                logger.info(f"🔍 Check exit cho local {local_id}: Job in queue={job_in_queue}, User active={user_in_active}")
                
                if not job_in_queue and not user_in_active:
                    logger.info(f"🛑 Local {local_id} nhận lệnh thoát: Job không còn trong hệ thống")
                    return jsonify({
                        "should_exit": True,
                        "message": "Job đã bị xóa, thoát web",
                        "reason": "job_not_found"
                    })
                
                # KIỂM TRA THÊM: Nếu user đã gửi lệnh thoát web
                # (thêm logic này nếu server lưu trạng thái thoát)
                if user_id and user_id in user_sessions:
                    session_info = user_sessions[user_id]
                    # Nếu session có đánh dấu vừa thoát (trong vòng 30s)
                    last_exit_str = session_info.get("last_exit")
                    if last_exit_str:
                        try:
                            last_exit = datetime.fromisoformat(last_exit_str.replace('Z', '+00:00'))
                            time_diff = (datetime.now() - last_exit).total_seconds()
                            if time_diff < 30:  # Trong vòng 30s sau khi thoát
                                logger.info(f"🛑 User {user_id} vừa thoát {time_diff:.0f}s trước, yêu cầu local dừng")
                                return jsonify({
                                    "should_exit": True,
                                    "message": "User vừa thoát web",
                                    "reason": "user_exited_recently"
                                })
                        except:
                            pass
        
        return jsonify({
            "should_exit": False,
            "message": "Tiếp tục chạy",
            "reason": "no_exit_command"
        })
        
    except Exception as e:
        logger.error(f"❌ Lỗi check_local_exit: {e}")
        return jsonify({
            "should_exit": False,
            "message": f"Error: {str(e)}"
        })

# ==================== ENDPOINT FORCE THOÁT ====================
@app.route('/force_exit_local', methods=['POST'])
def force_exit_local():
    """API để force local thoát (dùng khi cần thiết)"""
    try:
        data = request.json
        local_id = data.get('local_id')
        
        if not local_id:
            return jsonify({"status": "error", "message": "Missing local_id"}), 400
        
        if local_id not in local_connections:
            return jsonify({"status": "error", "message": "Local not found"}), 404
        
        logger.info(f"🛑 FORCE EXIT local {local_id}")
        
        # Lấy thông tin job đang chạy
        job = local_connections[local_id].get("current_job")
        if job:
            user_id = job.get("data", {}).get("user_id")
            
            # Xóa khỏi active automations
            if user_id in active_automations:
                del active_automations[user_id]
                logger.info(f"🗑️ Đã xóa {user_id} khỏi active automations")
            
            # Xóa job khỏi queue nếu có
            for i, j in enumerate(job_queue):
                if j.get("data", {}).get("user_id") == user_id:
                    job_queue.pop(i)
                    logger.info(f"🗑️ Đã xóa job của {user_id} khỏi queue")
                    break
        
        # Reset local
        local_connections[local_id]["status"] = "ready"
        local_connections[local_id]["current_job"] = None
        local_connections[local_id]["last_ping"] = datetime.now()
        
        return jsonify({
            "status": "success",
            "message": f"Đã gửi lệnh force exit cho local {local_id}",
            "force_exit": True
        })
        
    except Exception as e:
        logger.error(f"❌ Lỗi force_exit_local: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== ENDPOINTS QUẢN LÝ ====================
@app.route('/locals_status', methods=['GET'])
def get_locals_status():
    """API xem trạng thái tất cả máy local"""

# ... (giữ nguyên các endpoints khác)

# ==================== WEBHOOK LINE ====================
@app.route('/webhook', methods=['POST', 'GET'])
def line_webhook():
    """Webhook nhận tin nhắn từ LINE"""
    
    if request.method == 'GET':
        return 'OK', 200
    
    try:
        signature = request.headers.get('X-Line-Signature', '')
        body = request.get_data(as_text=False)
        
        if not verify_signature(body, signature):
            logger.warning("⚠️ Invalid LINE signature")
            return 'OK', 200
        
        data = request.json
        events = data.get('events', [])
        
        logger.info(f"✅ Nhận {len(events)} events từ LINE")
        
        for event in events:
            process_line_event(event)
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200

def process_line_event(event):
    """Xử lý sự kiện từ LINE"""
    try:
        event_type = event.get('type')
        source = event.get('source', {})
        user_id = source.get('userId')
        group_id = source.get('groupId')
        room_id = source.get('roomId')
        
        chat_type = "user"
        chat_id = user_id
        if group_id:
            chat_type = "group"
            chat_id = group_id
        elif room_id:
            chat_type = "room"
            chat_id = room_id
        
        logger.info(f"📱 Event từ {chat_type} {chat_id}: {event_type}")
        
        if event_type == 'message':
            message = event.get('message', {})
            message_text = message.get('text', '').strip()
            
            logger.info(f"💬 Tin nhắn: {message_text[:100]}...")
            
            if message_text.startswith('.'):
                process_line_command(message_text, user_id, chat_id, chat_type, group_id or room_id)
            else:
                # Phản hồi tin nhắn thường
                reply_text = f"📩 Bạn đã gửi: {message_text}\n\nGõ '.help' để xem các lệnh"
                send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, reply_text, chat_type)
        
        elif event_type == 'join':
            if chat_type in ["group", "room"]:
                send_welcome_message(chat_id, chat_type)
        
        elif event_type == 'leave':
            if group_id in group_queues:
                del group_queues[group_id]
                logger.info(f"🗑️ Đã xóa group queue {group_id}")
        
    except Exception as e:
        logger.error(f"❌ Lỗi process LINE event: {e}")

def process_line_command(command_text, user_id, chat_id, chat_type, group_id=None):
    """Xử lý lệnh từ LINE"""
    try:
        command = command_text[1:].lower().strip()
        
        logger.info(f"🖥️ Xử lý lệnh: {command} từ {user_id}")
        
        if command == 'help':
            send_help_message(chat_id, chat_type, group_id)
        
        elif command.startswith('login '):
            handle_login_command(command, user_id, chat_id, chat_type, group_id)
        
        elif command == 'status':
            handle_status_command(user_id, chat_id, chat_type, group_id)
        
        elif command == 'thoát web':
            handle_exit_command(user_id, chat_id, chat_type, group_id)
        
        elif command == 'queue':
            handle_queue_command(chat_id, chat_type, group_id)
        
        elif command == 'test':
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "✅ BOT HOẠT ĐỘNG BÌNH THƯỜNG!",
                chat_type
            )
        
        else:
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                f"❌ Lệnh không xác định: {command_text}\nGõ '.help' để xem hướng dẫn",
                chat_type
            )
            
    except Exception as e:
        logger.error(f"❌ Lỗi command: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            f"❌ Lỗi xử lý lệnh: {str(e)[:100]}",
            chat_type
        )

def send_welcome_message(chat_id, chat_type):
    """Gửi tin nhắn chào mừng"""
    welcome_message = """🎉 Xin chào! Tôi là Bot Ticket Automation

🤖 Tôi có thể giúp tự động hóa xử lý ticket trên hệ thống.

📝 LỆNH TRONG GROUP (bắt đầu bằng dấu .):
• .login username:password - Đăng nhập & chạy auto
• .thoát web - Kết thúc và giải phóng slot NGAY LẬP TỨC
• .status - Xem trạng thái
• .queue - Xem hàng chờ
• .help - Hướng dẫn đầy đủ
• .test - Test bot hoạt động

⚡ CHẾ ĐỘ MỚI:
• Thoát web → Giải phóng slot NGAY
• Có thể login lại username mới NGAY LẬP TỨC
• Công bằng và minh bạch!"""
    
    send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, welcome_message, chat_type)

def send_help_message(chat_id, chat_type, group_id=None):
    """Gửi tin nhắn trợ giúp"""
    help_text = """🤖 TICKET AUTOMATION - LOCAL MODE

📝 LỆNH (bắt đầu bằng dấu .):
• .help - Hướng dẫn
• .login username:password - Đăng nhập & chạy auto ticket
• .status - Trạng thái hệ thống  
• .thoát web - Thoát web NGAY và về standby
• .queue - Xem hàng chờ (trong group)
• .test - Test bot hoạt động

⚡ CÁCH HOẠT ĐỘNG MỚI:
1. .login username:password → Đăng nhập và chạy
2. .thoát web → Kết thúc NGAY, giải phóng slot
3. Có thể .login username_mới ngay lập tức

👥 TRONG GROUP:
• 1 người sử dụng tại 1 thời điểm
• Thoát web → Giải phóng slot NGAY
• Login lại → Chiếm slot nếu trống

⚙️ TRẠNG THÁI HỆ THỐNG:
• Server: luôn online
• Local: kết nối qua ping 30s
• Job: xếp hàng chờ nếu local bận"""
    
    send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, help_text, chat_type)

# ==================== SYNC WORKER ====================
def sync_worker():
    """Worker đồng bộ hệ thống"""
    while True:
        try:
            cleaned = cleanup_inactive_locals()
            if cleaned > 0:
                logger.info(f"🧹 Đã dọn {cleaned} local không hoạt động")
            
            assigned = process_job_queue()
            if assigned > 0:
                logger.info(f"⚡ Đã gán {assigned} job")
            
            # Log status định kỳ
            if int(time.time()) % 300 < 5:
                online_locals = 0
                for local_id, info in local_connections.items():
                    last_ping = info.get("last_ping")
                    if last_ping:
                        if isinstance(last_ping, str):
                            try:
                                last_ping = datetime.fromisoformat(last_ping.replace('Z', '+00:00'))
                            except:
                                last_ping = datetime.now()
                        time_diff = (datetime.now() - last_ping).total_seconds()
                        if time_diff < 60:
                            online_locals += 1
                
                logger.info(f"📊 Status - Locals: {online_locals}/{len(local_connections)}, Jobs: {len(job_queue)}, Active: {len(active_automations)}")
            
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"❌ Lỗi sync worker: {e}")
            time.sleep(30)

# ==================== KHỞI ĐỘNG ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER v5.0 - THOÁT WEB HOÀN TOÀN")
    logger.info(f"🔗 Server URL: {SERVER_URL}")
    logger.info("="*60)
    
    # Khởi động sync worker
    try:
        sync_thread = threading.Thread(target=sync_worker, daemon=True)
        sync_thread.start()
        logger.info("🔄 Đã khởi động sync worker")
    except Exception as e:
        logger.error(f"❌ Lỗi khởi động sync worker: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
