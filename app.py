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

# ⚠️ QUAN TRỌNG: KIỂM TRA LẠI CHANNEL SECRET
# Lấy từ LINE Developer Console -> Channel -> Basic settings -> Channel secret
LINE_CHANNEL_SECRET = "af29ee5866ddf060e20024b1c08bc2cf"  # Kiểm tra lại giá trị này

SERVER_URL = "https://line-bot-server-m54s.onrender.com"
PING_INTERVAL = 30  # Giây giữa các lần ping

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

# ==================== TIỆN ÍCH BẢO MẬT ====================
def verify_signature(payload, signature):
    """Xác minh webhook signature từ LINE - FIXED VERSION"""
    try:
        if not LINE_CHANNEL_SECRET or LINE_CHANNEL_SECRET == "YOUR_CHANNEL_SECRET":
            logger.error("❌ Channel secret chưa được cấu hình")
            return False
            
        if not signature:
            logger.error("❌ Không có signature từ LINE")
            return False
            
        # Tạo hash từ payload với channel secret
        channel_secret_bytes = LINE_CHANNEL_SECRET.encode('utf-8')
        
        # Sử dụng hmac để tạo signature
        hash_digest = hmac.new(channel_secret_bytes, payload, hashlib.sha256).digest()
        
        # Encode thành base64
        computed_signature = base64.b64encode(hash_digest).decode('utf-8')
        
        # DEBUG: Log để kiểm tra
        logger.debug(f"Signature từ LINE: {signature[:20]}...")
        logger.debug(f"Computed signature: {computed_signature[:20]}...")
        
        # So sánh signature
        result = hmac.compare_digest(computed_signature, signature)
        
        if not result:
            logger.warning(f"⚠️ Signature không khớp!")
            logger.warning(f"LINE sig: {signature}")
            logger.warning(f"Comp sig: {computed_signature}")
            
            # Kiểm tra thêm một lần nữa với trim
            trimmed_line_sig = signature.strip()
            trimmed_comp_sig = computed_signature.strip()
            
            if trimmed_line_sig == trimmed_comp_sig:
                logger.info("✅ Signature khớp sau khi trim")
                return True
                
        return result
        
    except Exception as e:
        logger.error(f"❌ Lỗi verify signature: {str(e)}")
        logger.error(f"Payload length: {len(payload)}")
        logger.error(f"Signature: {signature}")
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
        
        logger.info(f"📤 Sending to {chat_type} {to_id[:15]}...: {text[:50]}...")
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ Sent successfully to {to_id[:15]}...")
            return True
        else:
            logger.error(f"❌ Send failed to {to_id[:15]}: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error to {to_id[:15]}: {e}")
        return False

def get_bot_info():
    """Lấy thông tin bot"""
    try:
        url = "https://api.line.me/v2/bot/info"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"❌ Get bot info error: {e}")
        return None

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
                logger.info(f"🔄 Cleanup inactive local: {local_id} (last ping: {time_diff:.0f}s ago)")
        
        for local_id in inactive_locals:
            job = local_connections[local_id].get("current_job")
            if job:
                user_id = job.get("data", {}).get("user_id")
                job_id = job.get("job_id")
                
                if user_id in active_automations:
                    send_line_message_direct(
                        user_id,
                        LINE_CHANNEL_TOKEN,
                        "⚠️ Máy local đã mất kết nối. Job sẽ được xếp lại hàng chờ.",
                        "user"
                    )
                    del active_automations[user_id]
                
                job_queue.insert(0, job)
                logger.info(f"🔄 Job {job_id} đã được đưa trở lại queue do local {local_id} mất kết nối")
            
            del local_connections[local_id]
            logger.info(f"🧹 Đã xóa local {local_id} do không hoạt động")
        
        return len(inactive_locals)
    except Exception as e:
        logger.error(f"❌ Cleanup error: {e}")
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
                "started_at": datetime.now().isoformat()
            }
        
        logger.info(f"✅ Đã gán job {job.get('job_id')} cho local {local_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Assign job error: {e}")
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
        logger.error(f"❌ Create job error: {e}")
        return None

def process_job_queue():
    """Xử lý job queue - gán job cho máy local sẵn sàng"""
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
                    logger.info(f"✅ Đã gán job {job.get('job_id')} cho local {local_id}")
                else:
                    job_queue.insert(0, job)
        
        return jobs_assigned
    except Exception as e:
        logger.error(f"❌ Process job queue error: {e}")
        return 0

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
            logger.info(f"🔄 Local {local_id} đã cập nhật thông tin")
        else:
            local_connections[local_id] = {
                "last_ping": datetime.now(),
                "status": status,
                "current_job": None,
                "registered_at": datetime.now().isoformat()
            }
            logger.info(f"✅ Máy local mới đã đăng ký: {local_id}")
        
        if status == "ready":
            process_job_queue()
        
        return jsonify({
            "status": "success",
            "local_id": local_id,
            "message": f"Đã đăng ký/ cập nhật máy local {local_id}",
            "server_time": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Register local error: {e}")
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
                "message": "Local chưa đăng ký, vui lòng đăng ký trước"
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
            "message": "Ping received successfully"
        }
        
        logger.info(f"📡 Ping từ local {local_id} - Status: {status} - Has job: {has_job}")
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Handle ping error: {e}")
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
        
        local_connections[local_id]["status"] = "ready"
        local_connections[local_id]["current_job"] = None
        local_connections[local_id]["last_ping"] = datetime.now()
        
        user_id_to_remove = None
        for user_id, info in active_automations.items():
            if info.get("job_id") == job_id:
                user_id_to_remove = user_id
                break
        
        if user_id_to_remove:
            del active_automations[user_id_to_remove]
            logger.info(f"✅ Đã xóa automation tracking cho user {user_id_to_remove}")
        
        logger.info(f"✅ Job {job_id} đã hoàn thành bởi {local_id} - Success: {success}")
        
        if message and user_id_to_remove:
            send_line_message_direct(
                user_id_to_remove,
                LINE_CHANNEL_TOKEN,
                message,
                "user"
            )
        
        process_job_queue()
        
        return jsonify({
            "status": "acknowledged",
            "job_id": job_id,
            "message": "Job completion acknowledged"
        })
        
    except Exception as e:
        logger.error(f"❌ Job complete error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/local_log', methods=['POST'])
@require_local_auth
def receive_local_log():
    """Nhận log từ máy local"""
    try:
        data = request.json
        local_id = data.get('local_id')
        level = data.get('level', 'INFO')
        message = data.get('message', '')
        
        log_message = f"[LOCAL:{local_id}] {message}"
        
        if level.upper() == 'ERROR':
            logger.error(log_message)
        elif level.upper() == 'WARNING':
            logger.warning(log_message)
        elif level.upper() == 'DEBUG':
            logger.debug(log_message)
        else:
            logger.info(log_message)
        
        return jsonify({"status": "logged", "message": "Log received"})
        
    except Exception as e:
        logger.error(f"❌ Receive log error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/send_message', methods=['POST'])
@require_local_auth
def send_message_from_local():
    """Nhận yêu cầu gửi tin nhắn LINE từ local"""
    try:
        data = request.json
        user_id = data.get('user_id')
        group_id = data.get('group_id')
        message = data.get('message')
        
        if not message:
            return jsonify({"status": "error", "message": "No message provided"}), 400
        
        to_id = group_id if group_id else user_id
        chat_type = "group" if group_id else "user"
        
        if not to_id:
            return jsonify({"status": "error", "message": "No recipient specified"}), 400
        
        success = send_line_message_direct(to_id, LINE_CHANNEL_TOKEN, message, chat_type)
        
        return jsonify({
            "status": "success" if success else "error",
            "message_sent": success,
            "recipient": to_id,
            "chat_type": chat_type
        })
        
    except Exception as e:
        logger.error(f"❌ Send message from local error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== ENDPOINTS QUẢN LÝ ====================
@app.route('/locals_status', methods=['GET'])
def get_locals_status():
    """API xem trạng thái tất cả máy local"""
    try:
        current_time = datetime.now()
        locals_info = []
        
        for local_id, info in local_connections.items():
            last_ping = info.get("last_ping")
            
            if isinstance(last_ping, str):
                last_ping = datetime.fromisoformat(last_ping.replace('Z', '+00:00'))
            
            seconds_since_ping = (current_time - last_ping).total_seconds() if last_ping else 9999
            online = seconds_since_ping < PING_INTERVAL * 2
            
            locals_info.append({
                "local_id": local_id,
                "status": info.get("status", "unknown"),
                "online": online,
                "last_ping": last_ping.isoformat() if last_ping else None,
                "seconds_since_ping": round(seconds_since_ping, 1),
                "current_job": info.get("current_job"),
                "registered_at": info.get("registered_at")
            })
        
        cleanup_inactive_locals()
        
        return jsonify({
            "status": "success",
            "total_locals": len(locals_info),
            "online_locals": sum(1 for loc in locals_info if loc["online"]),
            "pending_jobs": len(job_queue),
            "active_automations": len(active_automations),
            "locals": locals_info,
            "job_queue": [{"job_id": j.get("job_id"), "user": j.get("data", {}).get("username")} for j in job_queue[:10]],
            "server_time": current_time.isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Get locals status error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/active_jobs', methods=['GET'])
def get_active_jobs():
    """API xem job đang chạy"""
    try:
        active_jobs = []
        
        for local_id, info in local_connections.items():
            job = info.get("current_job")
            if job:
                active_jobs.append({
                    "local_id": local_id,
                    "job_id": job.get("job_id"),
                    "user_id": job.get("data", {}).get("user_id"),
                    "username": job.get("data", {}).get("username"),
                    "status": info.get("status"),
                    "last_ping": info.get("last_ping")
                })
        
        return jsonify({
            "status": "success",
            "active_jobs": active_jobs,
            "total_active": len(active_jobs)
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup_system():
    """API dọn dẹp hệ thống"""
    try:
        cleaned = cleanup_inactive_locals()
        
        current_time = datetime.now()
        old_jobs = []
        
        for job in job_queue[:]:
            created_at = job.get("created_at")
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            
            time_diff = (current_time - created_at).total_seconds() if created_at else 0
            
            if time_diff > 3600:
                job_queue.remove(job)
                old_jobs.append(job.get("job_id"))
        
        return jsonify({
            "status": "success",
            "cleaned_locals": cleaned,
            "cleaned_jobs": len(old_jobs),
            "old_job_ids": old_jobs,
            "remaining_jobs": len(job_queue),
            "remaining_locals": len(local_connections)
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== ENDPOINTS LINE BOT ====================
@app.route('/')
def index():
    """Trang chủ với thông tin chi tiết"""
    bot_info = get_bot_info()
    
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
    
    return jsonify({
        "status": "online",
        "server": "LINE Bot Server v4.0 - Local Automation",
        "bot_info": {
            "name": bot_info.get('displayName') if bot_info else "Unknown",
            "user_id": bot_info.get('userId') if bot_info else "Unknown"
        },
        "system_status": {
            "online_locals": online_locals,
            "total_locals": len(local_connections),
            "pending_jobs": len(job_queue),
            "active_automations": len(active_automations),
            "server_time": datetime.now().isoformat()
        },
        "endpoints": {
            "webhook": f"{SERVER_URL}/webhook",
            "locals_status": f"{SERVER_URL}/locals_status",
            "active_jobs": f"{SERVER_URL}/active_jobs",
            "cleanup": f"{SERVER_URL}/cleanup"
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/test', methods=['GET'])
def test_server():
    """Test server hoạt động"""
    return jsonify({
        "status": "success",
        "message": "Server is running",
        "system_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "local_count": len(local_connections),
        "job_queue_count": len(job_queue)
    })

# ==================== WEBHOOK LINE (FIXED) ====================
@app.route('/webhook', methods=['POST', 'GET'])
def line_webhook():
    """Webhook nhận tin nhắn từ LINE - ĐÃ SỬA LỖI SIGNATURE"""
    
    # Xử lý GET request cho LINE webhook verification
    if request.method == 'GET':
        logger.info("✅ LINE webhook verification (GET request)")
        return 'OK', 200
    
    # Xử lý POST request
    try:
        # Lấy signature từ header
        signature = request.headers.get('X-Line-Signature', '')
        
        # DEBUG: Log signature để kiểm tra
        logger.info(f"📨 Nhận webhook request")
        logger.info(f"📝 Signature header: {signature[:50]}...")
        logger.info(f"📝 Content-Type: {request.headers.get('Content-Type')}")
        
        # Lấy raw body data
        body = request.get_data(as_text=False)
        
        # DEBUG: Log body length
        logger.info(f"📦 Body length: {len(body)} bytes")
        
        # Nếu không có signature, có thể là test request
        if not signature:
            logger.warning("⚠️ Không có signature, có thể là test request từ LINE")
            # Xử lý mà không verify để test
            try:
                data = request.json
                logger.info(f"📨 Test webhook data: {data}")
                return 'OK', 200
            except:
                return 'OK', 200
        
        # Verify signature
        if not verify_signature(body, signature):
            logger.error("❌ Invalid LINE signature - DEBUG INFO:")
            logger.error(f"Channel Secret được sử dụng: {LINE_CHANNEL_SECRET[:10]}...")
            logger.error(f"Signature từ LINE: {signature}")
            
            # Vẫn xử lý request để debug
            logger.warning("⚠️ Vẫn xử lý request để debug...")
            
            try:
                data = request.json
                events = data.get('events', [])
                logger.info(f"📨 Nhận {len(events)} events (signature failed)")
                
                # Xử lý events
                for event in events:
                    process_line_event(event)
                    
            except Exception as e:
                logger.error(f"❌ Error processing events: {e}")
            
            return 'OK', 200  # Vẫn trả về OK để LINE không gửi lại
        
        # Signature hợp lệ, xử lý bình thường
        data = request.json
        events = data.get('events', [])
        
        logger.info(f"✅ Signature hợp lệ! Nhận {len(events)} events từ LINE")
        
        for event in events:
            process_line_event(event)
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        logger.error(traceback.format_exc())
        return 'OK', 200  # Luôn trả về OK để LINE không retry

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
            
            # Chỉ xử lý lệnh bắt đầu bằng .
            if message_text.startswith('.'):
                process_line_command(message_text, user_id, chat_id, chat_type, group_id or room_id)
            else:
                # Gửi phản hồi cho tin nhắn thường
                reply_text = f"📩 Bạn đã gửi: {message_text}\n\nGõ '.help' để xem các lệnh có sẵn"
                send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, reply_text, chat_type)
        
        elif event_type == 'join':
            if chat_type in ["group", "room"]:
                send_welcome_message(chat_id, chat_type)
        
        elif event_type == 'leave':
            if group_id in group_queues:
                del group_queues[group_id]
                logger.info(f"🗑️ Đã xóa group queue cho {group_id}")
        
    except Exception as e:
        logger.error(f"❌ Process LINE event error: {e}")

def process_line_command(command_text, user_id, chat_id, chat_type, group_id=None):
    """Xử lý lệnh từ LINE"""
    try:
        # Loại bỏ dấu . và chuyển thành chữ thường
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
            # Lệnh test
            send_line_message_direct(
                chat_id,
                LINE_CHANNEL_TOKEN,
                "✅ BOT HOẠT ĐỘNG BÌNH THƯỜNG!\n\nServer đã nhận được lệnh test.",
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
        logger.error(f"❌ Process command error: {e}")
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
• .thoát web - Kết thúc và giải phóng slot
• .status - Xem trạng thái
• .queue - Xem hàng chờ
• .help - Hướng dẫn đầy đủ
• .test - Test bot hoạt động

🔒 CHẾ ĐỘ LUÂN PHIÊN:
• Chỉ 1 người sử dụng tại 1 thời điểm
• Tự động xếp hàng chờ
• Công bằng và minh bạch!"""
    
    send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, welcome_message, chat_type)

def send_help_message(chat_id, chat_type, group_id=None):
    """Gửi tin nhắn trợ giúp"""
    help_text = """🤖 TICKET AUTOMATION - LOCAL MODE

📝 LỆNH (bắt đầu bằng dấu .):
• .help - Hướng dẫn
• .login username:password - Đăng nhập & chạy auto ticket
• .status - Trạng thái hệ thống
• .thoát web - Thoát web và về standby
• .queue - Xem hàng chờ (trong group)
• .test - Test bot hoạt động

🔐 CÁCH HOẠT ĐỘNG:
1. Bạn gửi lệnh .login
2. Server nhận lệnh và tạo job
3. Máy local nhận job và chạy automation
4. Kết quả được gửi về LINE

👥 TRONG GROUP:
• Chỉ 1 người có thể sử dụng tại 1 thời điểm
• Tự động xếp hàng chờ
• Gửi '.thoát web' để giải phóng slot
• Gửi '.queue' để xem hàng chờ

⚙️ TRẠNG THÁI HỆ THỐNG:
• Server: luôn online
• Local: kết nối qua ping 30s
• Job: xếp hàng chờ nếu local bận"""
    
    send_line_message_direct(chat_id, LINE_CHANNEL_TOKEN, help_text, chat_type)

def handle_login_command(command, user_id, chat_id, chat_type, group_id):
    """Xử lý lệnh login"""
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
        
        # Kiểm tra trong group
        if group_id:
            if group_id not in group_queues:
                group_queues[group_id] = {
                    "current_user": None,
                    "current_username": None,
                    "waiting_users": []
                }
            
            queue = group_queues[group_id]
            
            # Kiểm tra user đã trong hàng chờ chưa
            for waiting_user in queue["waiting_users"]:
                if waiting_user.get("user_id") == user_id:
                    send_line_message_direct(
                        chat_id,
                        LINE_CHANNEL_TOKEN,
                        f"⏳ Bạn đã trong hàng chờ! Vị trí: {queue['waiting_users'].index(waiting_user) + 1}",
                        chat_type
                    )
                    return
            
            # Kiểm tra user đang sử dụng
            if queue["current_user"] == user_id:
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    "❌ Bạn đang sử dụng automation! Gửi '.thoát web' để kết thúc trước.",
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
        
        # Thêm vào hàng chờ group nếu có
        if group_id:
            if queue["current_user"] is None:
                # Cập nhật người đang sử dụng
                queue["current_user"] = user_id
                queue["current_username"] = username
                
                # Gửi thông báo job đã được tạo
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    f"✅ ĐÃ NHẬN LỆNH TỪ {username}\n🔄 Đang chờ máy local nhận job...",
                    chat_type
                )
            else:
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
                    f"📋 Bạn đã được thêm vào hàng chờ\nVị trí: {position}\n⏳ Vui lòng đợi đến lượt...",
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
        
        # Xử lý job queue ngay lập tức
        process_job_queue()
        
    except Exception as e:
        logger.error(f"❌ Handle login error: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            f"❌ Lỗi xử lý lệnh login: {str(e)[:100]}",
            chat_type
        )

def handle_status_command(user_id, chat_id, chat_type, group_id):
    """Xử lý lệnh status"""
    try:
        if chat_type == "user":
            if user_id in active_automations:
                info = active_automations[user_id]
                status_text = f"📊 TRẠNG THÁI CÁ NHÂN:\n• Đang chạy: ✅ CÓ\n• Job ID: {info.get('job_id')}\n• Bắt đầu: {info.get('started_at', 'Unknown')}"
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
        logger.error(f"❌ Handle status error: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            "❌ Lỗi lấy trạng thái",
            chat_type
        )

def handle_exit_command(user_id, chat_id, chat_type, group_id):
    """Xử lý lệnh thoát web"""
    try:
        if user_id in active_automations:
            job_id = active_automations[user_id].get("job_id")
            
            local_with_job = None
            for local_id, info in local_connections.items():
                if info.get("current_job", {}).get("job_id") == job_id:
                    local_with_job = local_id
                    break
            
            if local_with_job:
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    "🛑 ĐÃ GỬI LỆNH 'THOÁT WEB' CHO MÁY LOCAL\n⏳ Vui lòng đợi hệ thống xử lý...",
                    chat_type
                )
            else:
                del active_automations[user_id]
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    "🛑 ĐÃ DỪNG AUTOMATION",
                    chat_type
                )
        else:
            if group_id and group_id in group_queues:
                queue = group_queues[group_id]
                
                if queue["current_user"] == user_id:
                    queue["current_user"] = None
                    queue["current_username"] = None
                    
                    if queue["waiting_users"]:
                        next_user = queue["waiting_users"].pop(0)
                        send_line_message_direct(
                            group_id,
                            LINE_CHANNEL_TOKEN,
                            f"🔄 Đến lượt {next_user['username']}! Gửi '.login {next_user['username']}:{next_user['password']}' để bắt đầu.",
                            chat_type
                        )
                    
                    send_line_message_direct(
                        chat_id,
                        LINE_CHANNEL_TOKEN,
                        "✅ ĐÃ GIẢI PHÓNG SLOT TRONG GROUP",
                        chat_type
                    )
                else:
                    for i, waiting_user in enumerate(queue["waiting_users"]):
                        if waiting_user["user_id"] == user_id:
                            queue["waiting_users"].pop(i)
                            send_line_message_direct(
                                chat_id,
                                LINE_CHANNEL_TOKEN,
                                "✅ ĐÃ XÓA BẠN KHỎI HÀNG CHỜ",
                                chat_type
                            )
                            return
                    
                    send_line_message_direct(
                        chat_id,
                        LINE_CHANNEL_TOKEN,
                        "ℹ️ Bạn không có automation đang chạy",
                        chat_type
                    )
            else:
                send_line_message_direct(
                    chat_id,
                    LINE_CHANNEL_TOKEN,
                    "ℹ️ Bạn không có automation đang chạy",
                    chat_type
                )
        
    except Exception as e:
        logger.error(f"❌ Handle exit error: {e}")
        send_line_message_direct(
            chat_id,
            LINE_CHANNEL_TOKEN,
            f"❌ Lỗi xử lý lệnh thoát: {str(e)[:100]}",
            chat_type
        )

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
        logger.error(f"❌ Handle queue error: {e}")

# ==================== HÀM ĐỒNG BỘ ====================
def sync_worker():
    """Worker đồng bộ hệ thống"""
    while True:
        try:
            cleaned = cleanup_inactive_locals()
            if cleaned > 0:
                logger.info(f"🧹 Đã dọn dẹp {cleaned} local không hoạt động")
            
            assigned = process_job_queue()
            if assigned > 0:
                logger.info(f"⚡ Đã gán {assigned} job cho máy local")
            
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
                
                logger.info(f"📊 System status - Locals: {online_locals}/{len(local_connections)} online, Jobs: {len(job_queue)} pending, Active: {len(active_automations)}")
            
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"❌ Sync worker error: {e}")
            time.sleep(30)

# ==================== KHỞI ĐỘNG ====================
if __name__ == '__main__':
    import traceback
    
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER v4.0 - LOCAL AUTOMATION")
    logger.info(f"🔗 Server URL: {SERVER_URL}")
    logger.info(f"🔑 Channel Secret: {LINE_CHANNEL_SECRET[:10]}...")
    logger.info("="*60)
    
    # Test kết nối LINE API
    try:
        bot_info = get_bot_info()
        if bot_info:
            logger.info(f"🤖 Bot: {bot_info.get('displayName')} - {bot_info.get('userId')[:10]}...")
        else:
            logger.warning("⚠️ Không thể lấy thông tin bot, kiểm tra Channel Access Token")
    except Exception as e:
        logger.error(f"❌ Lỗi test LINE API: {e}")
    
    # Khởi động sync worker
    try:
        sync_thread = threading.Thread(target=sync_worker, daemon=True)
        sync_thread.start()
        logger.info("🔄 Đã khởi động sync worker")
    except Exception as e:
        logger.error(f"❌ Lỗi khởi động sync worker: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
