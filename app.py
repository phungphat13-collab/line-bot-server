from flask import Flask, request, jsonify
import requests
import time
import logging
import os
from datetime import datetime

app = Flask(__name__)

# ==================== CẤU HÌNH CHÍNH XÁC ====================
LINE_CHANNEL_TOKEN = "7HxJf6ykrTfMuz918kpokPMNUZOqpRv8FcGoJM/dkP8uIaqrwU5xFC+M8RoLUxYkkfZdrokoC9pMQ3kJv/SKxXTWTH1KhUe9fdXsNqVZXTA1w21+Wp1ywTQxZQViR2DVqR8w6CPvQpFJCbdvynuvSQdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b03437eaab695eb64192de4a7b268d6d"
LINE_GROUP_ID = "C807e14847947ac8d1ec1b673dfd95343"  # ✅ GROUP ID THỰC
SERVER_URL = "https://line-bot-server-m54s.onrender.com"

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

# ==================== TIỆN ÍCH ====================
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

def send_line_message(to_id, message):
    """Gửi tin nhắn LINE - ĐÃ SỬA VỚI GROUP ID THỰC"""
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
        
        logger.info(f"📤 Sending to {to_id[:15]}...")
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ Sent successfully")
            return True
        else:
            logger.error(f"❌ Send failed: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        return False

def verify_group_membership():
    """Xác minh bot có trong group không"""
    try:
        url = f"https://api.line.me/v2/bot/group/{LINE_GROUP_ID}/summary"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            group_info = response.json()
            logger.info(f"✅ Bot is in group: {group_info.get('groupName')}")
            return True, group_info
        else:
            logger.error(f"❌ Bot NOT in group: {response.status_code}")
            return False, None
            
    except Exception as e:
        logger.error(f"❌ Verify error: {e}")
        return False, None

# ========== ENDPOINTS KIỂM TRA ==========
@app.route('/')
def index():
    """Trang chủ với thông tin chi tiết"""
    bot_info = get_bot_info()
    in_group, group_info = verify_group_membership()
    
    return jsonify({
        "status": "online",
        "server": "LINE Bot Server v3.0",
        "bot_info": {
            "name": bot_info.get('displayName') if bot_info else "Unknown",
            "user_id": bot_info.get('userId') if bot_info else "Unknown"
        },
        "group_info": {
            "group_id": LINE_GROUP_ID,
            "group_name": group_info.get('groupName') if group_info else "Unknown",
            "bot_in_group": in_group,
            "member_count": group_info.get('count') if group_info else 0
        },
        "endpoints": {
            "webhook": f"{SERVER_URL}/webhook",
            "test": f"{SERVER_URL}/test",
            "send_hello": f"{SERVER_URL}/send_hello",
            "group_info": f"{SERVER_URL}/group_info"
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/test', methods=['GET'])
def test_server():
    """Test server hoạt động"""
    return jsonify({
        "status": "success",
        "message": "Server is running",
        "group_id": LINE_GROUP_ID,
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/send_hello', methods=['GET'])
def send_hello():
    """Gửi lời chào đến group"""
    try:
        message = f"👋 **XIN CHÀO TỪ BOT!**\n\n" \
                 f"✅ Kết nối thành công!\n" \
                 f"🆔 Group ID: {LINE_GROUP_ID}\n" \
                 f"🕒 {datetime.now().strftime('%H:%M:%S')}\n" \
                 f"🌐 Server: {SERVER_URL}"
        
        success = send_line_message(LINE_GROUP_ID, message)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Hello sent!" if success else "Failed to send",
            "group_id": LINE_GROUP_ID,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/group_info', methods=['GET'])
def get_group_info():
    """Lấy thông tin group"""
    try:
        in_group, group_info = verify_group_membership()
        
        if in_group:
            return jsonify({
                "status": "success",
                "bot_in_group": True,
                "group_id": LINE_GROUP_ID,
                "group_name": group_info.get('groupName'),
                "member_count": group_info.get('count'),
                "picture_url": group_info.get('pictureUrl'),
                "timestamp": time.time()
            })
        else:
            return jsonify({
                "status": "error",
                "bot_in_group": False,
                "message": "Bot is not in this group",
                "solution": f"Add bot using QR code from LINE Developer Console",
                "timestamp": time.time()
            }), 400
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time()
        }), 500

# ========== WEBHOOK CHÍNH ==========
@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    """Webhook xử lý tin nhắn từ LINE"""
    try:
        # Xử lý GET request (verification)
        if request.method == 'GET':
            logger.info("✅ LINE webhook verification")
            return 'OK', 200
        
        # Xử lý POST request (tin nhắn)
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
                    reply_token = event.get('replyToken')
                    
                    logger.info(f"💬 Message from {user_id[:10]}...: {text}")
                    
                    # Chỉ xử lý nếu là group đích
                    if group_id == LINE_GROUP_ID:
                        handle_group_message(text, group_id, user_id, reply_token)
                    else:
                        logger.warning(f"⚠️ Ignored: Message from other group {group_id}")
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        return 'OK', 200

def handle_group_message(text, group_id, user_id, reply_token):
    """Xử lý tin nhắn trong group"""
    try:
        # Sử dụng reply thay vì push để phản hồi ngay
        def reply_message(message_text):
            try:
                url = 'https://api.line.me/v2/bot/message/reply'
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
                }
                data = {
                    'replyToken': reply_token,
                    'messages': [{"type": "text", "text": message_text}]
                }
                requests.post(url, headers=headers, json=data, timeout=5)
                logger.info(f"📤 Replied to {user_id[:10]}...")
            except Exception as e:
                logger.error(f"❌ Reply error: {e}")
        
        # Xử lý các lệnh
        if text.lower() == '.hello':
            reply_message("👋 Xin chào! Tôi là bot của bạn!")
        
        elif text.lower() == '.test':
            reply_message(f"✅ **BOT HOẠT ĐỘNG**\n\n"
                         f"• Group ID: {group_id}\n"
                         f"• User: {user_id[:10]}...\n"
                         f"• Time: {datetime.now().strftime('%H:%M:%S')}")
        
        elif text.lower() == '.id':
            reply_message(f"🆔 **THÔNG TIN**\n\n"
                         f"• Group ID: `{group_id}`\n"
                         f"• User ID: `{user_id}`\n"
                         f"• Link: https://line.me/ti/g/{LINE_GROUP_ID}")
        
        elif text.lower() == '.help':
            help_text = "📋 **DANH SÁCH LỆNH**\n\n" \
                       "• `.hello` - Chào hỏi\n" \
                       "• `.test` - Kiểm tra bot\n" \
                       "• `.id` - Xem ID\n" \
                       "• `.server` - Thông tin server\n" \
                       "• `.send` - Gửi test push\n" \
                       "• `.help` - Trợ giúp"
            reply_message(help_text)
        
        elif text.lower() == '.server':
            reply_message(f"🌐 **SERVER INFO**\n\n"
                         f"• URL: {SERVER_URL}\n"
                         f"• Status: ✅ Online\n"
                         f"• Time: {datetime.now().strftime('%H:%M:%S')}")
        
        elif text.lower() == '.send':
            # Gửi push message riêng biệt
            push_message = f"📨 **PUSH MESSAGE TEST**\n\n" \
                          f"Tin nhắn này được gửi bằng push API\n" \
                          f"Từ user: {user_id[:10]}...\n" \
                          f"Time: {datetime.now().strftime('%H:%M:%S')}"
            
            send_line_message(group_id, push_message)
            reply_message("✅ Đã gửi push message!")
        
        else:
            # Phản hồi mặc định
            reply_message(f"📩 Bạn đã gửi: {text}\n\n"
                         f"Gõ `.help` để xem các lệnh có sẵn")
        
    except Exception as e:
        logger.error(f"❌ Handle message error: {e}")

# ==================== KHỞI ĐỘNG ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🚀 LINE BOT SERVER - GROUP ID ĐÃ XÁC ĐỊNH")
    logger.info(f"🎯 Group ID: {LINE_GROUP_ID}")
    logger.info(f"🔗 Server: {SERVER_URL}")
    logger.info("="*60)
    
    # Kiểm tra khi khởi động
    bot_info = get_bot_info()
    if bot_info:
        logger.info(f"🤖 Bot: {bot_info.get('displayName')}")
    
    in_group, group_info = verify_group_membership()
    if in_group:
        logger.info(f"✅ Bot đang trong group: {group_info.get('groupName')}")
    else:
        logger.warning("⚠️ Bot chưa trong group!")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
