from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime

# Tắt log để tiết kiệm tài nguyên
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình LINE
LINE_CHANNEL_TOKEN = os.getenv('LINE_ACCESS_TOKEN', "yrazgly8JwQb7zaoAb13wck530QXpo7meQ+Fx0mILCbGJd2zAO8S5dhRNnKjsYn4nbGN/OHZlwrk1rFrO8FWXNzPQQ/dLVbftskrYvFoPBOHFbCRDVyM8WonW5anLpTz330+LfCrVdAdsZRgH3u1fgdB04t89/1O/w1cDnyilFU=")

# Lưu trạng thái user
user_sessions = {}
group_queues = {}

def send_line_message(chat_id, text, chat_type="user"):
    """Gửi tin nhắn LINE - TỐI ƯU CHO RENDER"""
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
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Line message failed: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def line_webhook():
    """Webhook nhận lệnh từ LINE - CHỈ QUẢN LÝ LỆNH"""
    try:
        data = request.get_json()
        events = data.get('events', [])
        
        for event in events:
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
            
            if event_type == 'message':
                message_text = event.get('message', {}).get('text', '').strip().lower()
                
                # Xử lý lệnh đơn giản
                if message_text in ['/help', 'help', 'hướng dẫn']:
                    help_text = """🤖 TICKET AUTOMATION BOT

📋 LỆNH CƠ BẢN:
• login username:password - Kết nối và chạy auto
• status - Kiểm tra trạng thái
• stop - Dừng automation
• help - Hướng dẫn này

🔧 CÁCH DÙNG:
1. Gửi 'login username:password'
2. Bot sẽ hướng dẫn kết nối máy local
3. Chạy script trên máy bạn

💡 Lưu ý: Cần chạy script local để auto ticket"""
                    send_line_message(chat_id, help_text, chat_type)
                
                elif message_text.startswith('login '):
                    credentials = message_text[6:]
                    if ':' in credentials:
                        username, password = credentials.split(':', 1)
                        # Lưu thông tin user
                        user_sessions[user_id] = {
                            'username': username,
                            'password': password,
                            'group_id': group_id,
                            'room_id': room_id,
                            'status': 'waiting_local'
                        }
                        
                        response_msg = f"""✅ Đã lưu thông tin: {username}

📝 HƯỚNG DẪN KẾT NỐI LOCAL:

Bước 1: Tải script local từ:
https://github.com/your-repo/ticket-automation

Bước 2: Chạy script trên máy bạn:
python local_client.py {user_id} {username}

Bước 3: Script sẽ tự động kết nối và chạy

🔒 Bảo mật: Password được mã hóa"""
                        send_line_message(chat_id, response_msg, chat_type)
                        
                        # Thông báo trong group
                        if group_id:
                            send_line_message(group_id, f"🔄 {username} đang thiết lập kết nối local...", "group")
                    
                    else:
                        send_line_message(chat_id, "❌ Sai cú pháp! Dùng: login username:password", chat_type)
                
                elif message_text in ['status', 'trạng thái']:
                    if user_id in user_sessions:
                        status = user_sessions[user_id].get('status', 'unknown')
                        username = user_sessions[user_id].get('username', 'N/A')
                        response_msg = f"📊 Trạng thái {username}: {status}"
                    else:
                        response_msg = "📊 Bạn chưa đăng nhập. Gửi 'login username:password'"
                    send_line_message(chat_id, response_msg, chat_type)
                
                elif message_text in ['stop', 'dừng', 'thoát']:
                    if user_id in user_sessions:
                        user_sessions[user_id]['status'] = 'stopped'
                        send_line_message(chat_id, "🛑 Đã gửi lệnh dừng automation", chat_type)
                    else:
                        send_line_message(chat_id, "❌ Không tìm thấy session đang chạy", chat_type)
            
            elif event_type == 'join':
                welcome_msg = "🎉 Chào mừng! Tôi là Bot Ticket Automation. Gửi 'help' để xem hướng dẫn."
                send_line_message(chat_id, welcome_msg, chat_type)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
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
            
            # Thông báo cho user
            username = user_sessions[user_id].get('username')
            send_line_message(user_id, f"✅ Đã kết nối với máy local\nIP: {client_ip}\nUser: {username}")
            
            return jsonify({"status": "connected", "message": "Kết nối thành công"})
        else:
            return jsonify({"status": "error", "message": "User không tồn tại"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/update_status', methods=['POST'])
def update_status():
    """API cập nhật trạng thái từ local client"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        status = data.get('status')
        message = data.get('message', '')
        
        if user_id in user_sessions:
            user_sessions[user_id]['status'] = status
            user_sessions[user_id]['last_update'] = datetime.now().isoformat()
            
            # Gửi thông báo cho user
            if message:
                send_line_message(user_id, message)
            
            return jsonify({"status": "updated"})
        else:
            return jsonify({"status": "error", "message": "User không tồn tại"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_credentials', methods=['GET'])
def get_credentials():
    """API lấy thông tin đăng nhập (bảo mật)"""
    try:
        user_id = request.args.get('user_id')
        
        if user_id in user_sessions:
            # Trả về thông tin cần thiết (không trả password trực tiếp)
            return jsonify({
                "status": "success",
                "username": user_sessions[user_id].get('username'),
                "user_id": user_id
            })
        else:
            return jsonify({"status": "error", "message": "User không tồn tại"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    active_users = len([u for u in user_sessions.values() if u.get('status') == 'connected'])
    return jsonify({
        "status": "healthy",
        "active_users": active_users,
        "total_sessions": len(user_sessions),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    """Trang chủ"""
    return jsonify({
        "service": "Ticket Automation API Server",
        "version": "1.0",
        "status": "running"
    })

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
