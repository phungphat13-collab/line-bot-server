from flask import Flask, request, jsonify
from threading import Thread, Lock
import requests
import time
import logging
import json
import os
from datetime import datetime
import traceback

app = Flask(__name__)

# ==================== CẤU HÌNH MỚI ====================
LINE_CHANNEL_TOKEN = "Z45KyBW+4pEZM8OJDh0qM8+8AD2/hQxZdnMSGHRfbuPBMBWF5G3FAXKyS4GqXDzXA1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5gjAofn+Z3Hq/guCI0Q6V5uw6n5l1k/gWURHvcK1+loMQdB04t89/1O/w1cDnyilFU="
SERVER_URL = "https://line-bot-server-m54s.onrender.com"
# ⚠️ CHÚ Ý: ĐÃ THAY ĐỔI GROUP ID NÀY
LINE_GROUP_ID = "Dc67tyJVQr"  # GROUP ID TỪ LINK MỚI: https://line.me/ti/g/Dc67tyJVQr

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

# ==================== TIỆN ÍCH ====================
def send_line_message(to_id, message):
    """Gửi tin nhắn LINE"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
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
            logger.error(f"❌ Line API error: {response.status_code} - {response.text}")
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
    with clients_lock:
        client_count = len(local_clients)
    
    with queue_lock:
        waiting_count = len(group_queues[LINE_GROUP_ID]["waiting_users"])
    
    return jsonify({
        "status": "online",
        "service": "LINE Bot Server",
        "version": "2.0",
        "group_id": LINE_GROUP_ID,
        "group_link": f"https://line.me/ti/g/{LINE_GROUP_ID}",
        "clients_connected": client_count,
        "waiting_users": waiting_count,
        "webhook": f"{SERVER_URL}/webhook",
        "server_time": datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "group_id": LINE_GROUP_ID
    })

# ========== DEBUG ENDPOINTS ==========
@app.route('/test', methods=['GET'])
def test_webhook():
    """Test webhook endpoint"""
    return jsonify({
        "status": "success",
        "server": SERVER_URL,
        "webhook": f"{SERVER_URL}/webhook",
        "group_id": LINE_GROUP_ID,
        "timestamp": time.time()
    })

@app.route('/send_test', methods=['GET'])
def send_test_message():
    """Gửi test message đến group mới"""
    try:
        message = f"🔄 **TEST TỪ SERVER**\n\n" \
                 f"✅ Group mới: {LINE_GROUP_ID}\n" \
                 f"🔗 Link: https://line.me/ti/g/{LINE_GROUP_ID}\n" \
                 f"🕒 {datetime.now().strftime('%H:%M:%S')}\n" \
                 f"🌐 Server: {SERVER_URL}"
        
        success = send_line_message(LINE_GROUP_ID, message)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Test sent to new group" if success else "Failed",
            "group_id": LINE_GROUP_ID,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check_group', methods=['GET'])
def check_bot_location():
    """Kiểm tra bot đang ở group nào"""
    try:
        # Lấy danh sách group bot đang tham gia
        url = "https://api.line.me/v2/bot/group/list"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            groups = response.json().get('groups', [])
            
            result = {
                "target_group_id": LINE_GROUP_ID,
                "target_group_link": f"https://line.me/ti/g/{LINE_GROUP_ID}",
                "total_groups": len(groups),
                "groups": [],
                "in_target_group": False
            }
            
            for group in groups:
                group_id = group.get('groupId')
                is_target = (group_id == LINE_GROUP_ID)
                
                if is_target:
                    result["in_target_group"] = True
                
                result["groups"].append({
                    "group_id": group_id,
                    "group_name": group.get('groupName', 'Unknown'),
                    "is_target_group": is_target
                })
            
            return jsonify(result)
        else:
            return jsonify({
                "error": f"API Error: {response.status_code}",
                "message": response.text
            }), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== LOCAL CLIENT REGISTRATION ==========
@app.route('/register', methods=['POST'])
def register_group():
    try:
        data = request.json
        group_id = data.get('group_id', LINE_GROUP_ID)
        
        # Chỉ chấp nhận group ID mới
        if group_id != LINE_GROUP_ID:
            return jsonify({
                "error": "Invalid group_id",
                "expected": LINE_GROUP_ID,
                "received": group_id
            }), 400
        
        with clients_lock:
            local_clients[group_id] = {
                'last_ping': time.time(),
                'status': 'active',
                'ip': request.remote_addr,
                'tasks': [],
                'registered_at': datetime.now().isoformat()
            }
        
        logger.info(f"✅ Client registered for group: {group_id}")
        
        return jsonify({
            "status": "success",
            "message": "Client registered successfully",
            "group_id": group_id,
            "webhook": f"{SERVER_URL}/webhook"
        })
        
    except Exception as e:
        logger.error(f"❌ Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/ping', methods=['POST'])
def ping_group():
    """Ping để giữ kết nối"""
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
                    "group_id": group_id,
                    "timestamp": time.time()
                })
            else:
                return jsonify({"error": "Group not registered"}), 404
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== LINE WEBHOOK - SIMPLIFIED ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    """Endpoint nhận webhook từ LINE"""
    try:
        if request.method == 'GET':
            logger.info("✅ Webhook verification request")
            return 'OK', 200
        
        # Nhận dữ liệu từ LINE
        data = request.json
        events = data.get('events', [])
        
        logger.info(f"📨 Received {len(events)} events from LINE")
        
        for event in events:
            event_type = event.get('type')
            
            # Chỉ xử lý message event
            if event_type == 'message':
                message = event.get('message', {})
                
                if message.get('type') == 'text':
                    text = message.get('text', '').strip()
                    source = event.get('source', {})
                    group_id = source.get('groupId')
                    
                    logger.info(f"💬 Message in group {group_id}: {text}")
                    
                    # Chỉ xử lý nếu là group đích
                    if group_id == LINE_GROUP_ID:
                        handle_message(text, group_id)
                    else:
                        logger.warning(f"⚠️ Ignored message from other group: {group_id}")
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        return 'OK', 200  # Vẫn trả về 200 để LINE không gửi lại

def handle_message(text, group_id):
    """Xử lý tin nhắn từ group"""
    try:
        if text == '.hello':
            reply = "👋 Chào bạn! Tôi là LINE Bot.\nGõ .help để xem hướng dẫn"
        
        elif text == '.help':
            reply = "📋 **HƯỚNG DẪN SỬ DỤNG**\n\n" \
                   "• `.hello` - Chào hỏi\n" \
                   "• `.test` - Kiểm tra bot\n" \
                   "• `.id` - Xem Group ID\n" \
                   "• `.status` - Trạng thái hệ thống\n" \
                   "• `.server` - Thông tin server\n" \
                   "• `.help` - Hiển thị hướng dẫn này"
        
        elif text == '.test':
            reply = f"✅ **BOT ĐANG HOẠT ĐỘNG**\n\n" \
                   f"• Group: {LINE_GROUP_ID}\n" \
                   f"• Server: {SERVER_URL}\n" \
                   f"• Time: {datetime.now().strftime('%H:%M:%S')}"
        
        elif text == '.id':
            reply = f"👥 **GROUP INFO**\n\n" \
                   f"• ID: `{group_id}`\n" \
                   f"• Link: https://line.me/ti/g/{group_id}\n" \
                   f"• Webhook: {SERVER_URL}/webhook"
        
        elif text == '.status':
            with clients_lock:
                client_count = len(local_clients)
            
            reply = f"📊 **SYSTEM STATUS**\n\n" \
                   f"• Server: ✅ Online\n" \
                   f"• Group ID: {LINE_GROUP_ID}\n" \
                   f"• Clients: {client_count}\n" \
                   f"• Time: {datetime.now().strftime('%H:%M:%S')}"
        
        elif text == '.server':
            reply = f"🌐 **SERVER INFO**\n\n" \
                   f"• URL: {SERVER_URL}\n" \
                   f"• Webhook: {SERVER_URL}/webhook\n" \
                   f"• Health: {SERVER_URL}/health\n" \
                   f"• Group: {SERVER_URL}/check_group"
        
        else:
            # Phản hồi mặc định cho tin nhắn không phải lệnh
            reply = f"📩 Bạn đã gửi: {text}\n\n" \
                   f"Gõ `.help` để xem các lệnh có sẵn"
        
        # Gửi phản hồi
        send_line_message(group_id, reply)
        logger.info(f"📤 Replied to group {group_id}")
        
    except Exception as e:
        logger.error(f"❌ Error handling message: {e}")

# ==================== CHẠY SERVER ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER STARTING")
    logger.info(f"👥 Target Group: {LINE_GROUP_ID}")
    logger.info(f"🔗 Group Link: https://line.me/ti/g/{LINE_GROUP_ID}")
    logger.info(f"🌐 Server URL: {SERVER_URL}")
    logger.info(f"🔄 Webhook: {SERVER_URL}/webhook")
    logger.info("="*60)
    
    # Khởi động monitor thread
    monitor_thread = Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()
    
    # Khởi động Flask server
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
