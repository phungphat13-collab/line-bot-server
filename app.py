from flask import Flask, request, jsonify
from threading import Thread, Lock
import requests
import time
import logging
import json
import os
from datetime import datetime
import hmac
import hashlib
import traceback

app = Flask(__name__)

# ==================== CẤU HÌNH VỚI TOKEN MỚI ====================
LINE_CHANNEL_SECRET = "b03437eaab695eb64192de4a7b268d6d"  # CHANNEL SECRET MỚI
LINE_CHANNEL_TOKEN = "7HxJf6ykrTfMuz918kpokPMNUZOqpRv8FcGoJM/dkP8uIaqrwU5xFC+M8RoLUxYkkfZdrokoC9pMQ3kJv/SKxXTWTH1KhUe9fdXsNqVZXTA1w21+Wp1ywTQxZQViR2DVqR8w6CPvQpFJCbdvynuvSQdB04t89/1O/w1cDnyilFU="  # TOKEN MỚI
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
LINE_GROUP_ID = "Dc67tyJVQr"  # GROUP ID MỚI

# ==================== BIẾN TOÀN CỤC ====================
local_clients = {}
group_queues = {
    LINE_GROUP_ID: {
        "waiting_users": [],
        "current_user": None,
        "current_username": None,
        "current_task": None
    }
}

clients_lock = Lock()
queue_lock = Lock()

# ==================== LOGGING ====================
def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('server.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==================== XÁC MINH WEBHOOK ====================
def verify_signature(body, signature):
    """Xác minh chữ ký webhook từ LINE"""
    try:
        hash = hmac.new(
            LINE_CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hash).decode('utf-8')
        
        if signature != expected_signature:
            logger.warning(f"⚠️ Signature mismatch!")
            logger.warning(f"  Expected: {expected_signature[:50]}...")
            logger.warning(f"  Received: {signature[:50]}...")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ Verify signature error: {e}")
        return False

# ==================== TIỆN ÍCH ====================
def send_line_message(to_id, message):
    """Gửi tin nhắn LINE với token mới"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'  # DÙNG TOKEN MỚI
        }
        
        data = {
            'to': to_id,
            'messages': [{"type": "text", "text": message}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"📤 Sent to {to_id}: {message[:50]}...")
            return True
        else:
            logger.error(f"❌ Line API error: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        return False

# ==================== MONITOR THREAD ====================
def connection_monitor():
    """Giám sát kết nối local client"""
    logger.info("🔍 Starting connection monitor...")
    
    while True:
        try:
            current_time = time.time()
            disconnected_groups = []
            
            with clients_lock:
                for group_id, client_info in list(local_clients.items()):
                    last_ping = client_info.get('last_ping', 0)
                    if current_time - last_ping > 60:
                        disconnected_groups.append(group_id)
                        logger.warning(f"⏰ Timeout GROUP: {group_id}")
            
            for group_id in disconnected_groups:
                with clients_lock:
                    if group_id in local_clients:
                        del local_clients[group_id]
                        logger.info(f"🗑️ Removed: {group_id}")
                
                send_line_message(
                    group_id,
                    "⚠️ Mất kết nối với local client! Vui lòng khởi động lại."
                )
            
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"❌ Monitor error: {e}")
            time.sleep(30)

# ========== HEALTH & INFO ==========
@app.route('/')
def index():
    """Trang chủ"""
    return jsonify({
        "status": "online",
        "service": "LINE Bot Server",
        "version": "3.0",
        "token_status": "NEW TOKEN CONFIGURED",
        "group_id": LINE_GROUP_ID,
        "group_link": f"https://line.me/ti/g/{LINE_GROUP_ID}",
        "webhook": f"{SERVER_URL}/webhook",
        "server_time": datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "group_id": LINE_GROUP_ID,
        "token_valid": True
    })

# ========== TEST ENDPOINTS ==========
@app.route('/test_token', methods=['GET'])
def test_token():
    """Test token mới"""
    try:
        # Test token bằng cách lấy bot profile
        url = "https://api.line.me/v2/bot/info"
        headers = {
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            bot_info = response.json()
            return jsonify({
                "status": "success",
                "message": "Token is valid",
                "bot_info": bot_info,
                "channel_secret": LINE_CHANNEL_SECRET[:10] + "...",
                "channel_token": LINE_CHANNEL_TOKEN[:10] + "..."
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Token invalid: {response.status_code}",
                "response": response.text
            }), 400
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/send_demo', methods=['GET'])
def send_demo_message():
    """Gửi demo message với token mới"""
    try:
        message = f"🚀 **LINE BOT ĐÃ ĐƯỢC CẬP NHẬT**\n\n" \
                 f"✅ Token mới đã được áp dụng\n" \
                 f"🔗 Group: https://line.me/ti/g/{LINE_GROUP_ID}\n" \
                 f"🕒 {datetime.now().strftime('%H:%M:%S')}\n" \
                 f"🌐 Server: {SERVER_URL}"
        
        success = send_line_message(LINE_GROUP_ID, message)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Demo message sent" if success else "Failed to send",
            "group_id": LINE_GROUP_ID,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== LINE WEBHOOK ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    """Endpoint nhận webhook từ LINE"""
    try:
        # Xử lý GET request (LINE verification)
        if request.method == 'GET':
            logger.info("✅ LINE webhook verification request")
            return 'OK', 200
        
        # Xác minh chữ ký
        signature = request.headers.get('X-Line-Signature', '')
        body = request.get_data(as_text=True)
        
        if not verify_signature(body, signature):
            logger.error("❌ Invalid signature!")
            return 'Invalid signature', 400
        
        # Parse JSON data
        data = request.json
        events = data.get('events', [])
        
        logger.info(f"📨 Received {len(events)} events")
        
        for event in events:
            event_type = event.get('type')
            
            if event_type == 'message':
                message = event.get('message', {})
                
                if message.get('type') == 'text':
                    text = message.get('text', '').strip()
                    source = event.get('source', {})
                    group_id = source.get('groupId')
                    user_id = source.get('userId')
                    
                    logger.info(f"💬 Message from {user_id} in {group_id}: {text}")
                    
                    # Chỉ xử lý nếu là group đích
                    if group_id == LINE_GROUP_ID:
                        process_message(text, group_id, user_id)
                    else:
                        logger.warning(f"⚠️ Ignored: Message from other group {group_id}")
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        traceback.print_exc()
        return 'OK', 200

def process_message(text, group_id, user_id):
    """Xử lý tin nhắn từ group"""
    try:
        # Lệnh đơn giản
        if text == '.hello':
            reply = "👋 Xin chào! Tôi là LINE Bot với token mới!"
        
        elif text == '.help':
            reply = "📋 **DANH SÁCH LỆNH**\n\n" \
                   "• `.hello` - Chào hỏi\n" \
                   "• `.test` - Kiểm tra bot\n" \
                   "• `.id` - Xem Group ID\n" \
                   "• `.token` - Kiểm tra token\n" \
                   "• `.server` - Thông tin server\n" \
                   "• `.help` - Hướng dẫn sử dụng"
        
        elif text == '.test':
            reply = f"✅ **BOT HOẠT ĐỘNG BÌNH THƯỜNG**\n\n" \
                   f"• Token: MỚI ✅\n" \
                   f"• Group: {LINE_GROUP_ID}\n" \
                   f"• User: {user_id}\n" \
                   f"• Time: {datetime.now().strftime('%H:%M:%S')}"
        
        elif text == '.id':
            reply = f"👥 **THÔNG TIN**\n\n" \
                   f"• Group ID: `{group_id}`\n" \
                   f"• User ID: `{user_id}`\n" \
                   f"• Link: https://line.me/ti/g/{group_id}"
        
        elif text == '.token':
            reply = f"🔐 **TOKEN INFO**\n\n" \
                   f"• Status: ĐÃ CẬP NHẬT ✅\n" \
                   f"• Token: {LINE_CHANNEL_TOKEN[:15]}...\n" \
                   f"• Secret: {LINE_CHANNEL_SECRET[:15]}..."
        
        elif text == '.server':
            reply = f"🌐 **SERVER**\n\n" \
                   f"• URL: {SERVER_URL}\n" \
                   f"• Webhook: {SERVER_URL}/webhook\n" \
                   f"• Health: {SERVER_URL}/health\n" \
                   f"• Test: {SERVER_URL}/test_token"
        
        else:
            # Phản hồi cho tin nhắn thường
            reply = f"📩 Bạn đã gửi: {text}\n\n" \
                   f"Đây là bot với token mới!\n" \
                   f"Gõ `.help` để xem các lệnh."
        
        # Gửi phản hồi
        send_line_message(group_id, reply)
        logger.info(f"📤 Replied to {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Process message error: {e}")
        send_line_message(group_id, f"❌ Lỗi xử lý: {str(e)}")

# ========== LOCAL CLIENT API ==========
@app.route('/register', methods=['POST'])
def register_client():
    """Đăng ký local client"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        if group_id != LINE_GROUP_ID:
            return jsonify({
                "error": "Invalid group_id",
                "expected": LINE_GROUP_ID
            }), 400
        
        with clients_lock:
            local_clients[group_id] = {
                'last_ping': time.time(),
                'status': 'active',
                'ip': request.remote_addr,
                'registered_at': datetime.now().isoformat()
            }
        
        logger.info(f"✅ Client registered: {group_id}")
        
        return jsonify({
            "status": "success",
            "message": "Registered successfully",
            "group_id": group_id,
            "token": "NEW_TOKEN_ACTIVE"
        })
        
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/ping', methods=['POST'])
def ping_client():
    """Ping từ local client"""
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        if group_id != LINE_GROUP_ID:
            return jsonify({"error": "Invalid group_id"}), 400
        
        with clients_lock:
            if group_id in local_clients:
                local_clients[group_id]['last_ping'] = time.time()
                return jsonify({
                    "status": "pong",
                    "timestamp": time.time()
                })
            else:
                return jsonify({"error": "Not registered"}), 404
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== CHẠY SERVER ====================
if __name__ == '__main__':
    import base64
    
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER - TOKEN MỚI")
    logger.info(f"🔐 Channel Secret: {LINE_CHANNEL_SECRET[:10]}...")
    logger.info(f"🔑 Channel Token: {LINE_CHANNEL_TOKEN[:10]}...")
    logger.info(f"👥 Group ID: {LINE_GROUP_ID}")
    logger.info(f"🔗 Group Link: https://line.me/ti/g/{LINE_GROUP_ID}")
    logger.info(f"🌐 Server URL: {SERVER_URL}")
    logger.info("="*60)
    
    # Khởi động monitor thread
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    # Khởi động Flask server
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
