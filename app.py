from flask import Flask, request, jsonify
import requests
import time
import logging
import os
from datetime import datetime

app = Flask(__name__)

# ==================== CẤU HÌNH ====================
LINE_CHANNEL_TOKEN = "7HxJf6ykrTfMuz918kpokPMNUZOqpRv8FcGoJM/dkP8uIaqrwU5xFC+M8RoLUxYkkfZdrokoC9pMQ3kJv/SKxXTWTH1KhUe9fdXsNqVZXTA1w21+Wp1ywTQxZQViR2DVqR8w6CPvQpFJCbdvynuvSQdB04t89/1O/w1cDnyilFU="
LINE_GROUP_ID = "Dc67tyJVQr"

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== TIỆN ÍCH ====================
def test_token():
    """Test token có hợp lệ không"""
    try:
        url = "https://api.line.me/v2/bot/info"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            bot_info = response.json()
            logger.info(f"✅ Token valid! Bot: {bot_info.get('displayName')}")
            return True, bot_info
        else:
            logger.error(f"❌ Token invalid! Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False, None
            
    except Exception as e:
        logger.error(f"❌ Test token error: {e}")
        return False, None

def send_line_message(to_id, message):
    """Gửi tin nhắn LINE"""
    try:
        # Kiểm tra token trước
        is_valid, bot_info = test_token()
        if not is_valid:
            logger.error("❌ Cannot send: Token invalid")
            return False
        
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        
        data = {
            'to': to_id,
            'messages': [{"type": "text", "text": message}]
        }
        
        logger.info(f"📤 Sending to {to_id}: {message[:30]}...")
        logger.info(f"📤 Token used: {LINE_CHANNEL_TOKEN[:20]}...")
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        logger.info(f"📤 Response Status: {response.status_code}")
        logger.info(f"📤 Response Body: {response.text}")
        
        if response.status_code == 200:
            logger.info(f"✅ Sent successfully to {to_id}")
            return True
        else:
            logger.error(f"❌ Failed to send. Status: {response.status_code}")
            logger.error(f"Error details: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send message error: {str(e)}")
        return False

# ========== ENDPOINTS ==========
@app.route('/')
def index():
    """Trang chủ"""
    return jsonify({
        "status": "online",
        "service": "LINE Bot Debug Server",
        "group_id": LINE_GROUP_ID,
        "timestamp": time.time()
    })

@app.route('/test_token', methods=['GET'])
def test_token_endpoint():
    """Test token endpoint"""
    is_valid, bot_info = test_token()
    
    if is_valid:
        return jsonify({
            "status": "success",
            "message": "Token is valid",
            "bot_name": bot_info.get('displayName'),
            "bot_id": bot_info.get('userId'),
            "basic_id": bot_info.get('basicId')
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Token is invalid",
            "timestamp": time.time()
        }), 400

@app.route('/test_send', methods=['GET'])
def test_send():
    """Test gửi tin nhắn đơn giản"""
    try:
        message = "🔄 Test message from server\n" \
                 f"Group: {LINE_GROUP_ID}\n" \
                 f"Time: {datetime.now().strftime('%H:%M:%S')}"
        
        success = send_line_message(LINE_GROUP_ID, message)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "Message sent successfully",
                "group_id": LINE_GROUP_ID,
                "timestamp": time.time()
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to send message",
                "group_id": LINE_GROUP_ID,
                "timestamp": time.time()
            }), 400
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/check_group', methods=['GET'])
def check_group():
    """Kiểm tra bot có trong group không"""
    try:
        # 1. Kiểm tra token
        is_valid, bot_info = test_token()
        if not is_valid:
            return jsonify({
                "status": "error",
                "message": "Token invalid",
                "timestamp": time.time()
            }), 400
        
        # 2. Kiểm tra bot có trong group không
        url = f"https://api.line.me/v2/bot/group/{LINE_GROUP_ID}/summary"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            group_info = response.json()
            return jsonify({
                "status": "success",
                "message": "Bot is in group",
                "group_id": LINE_GROUP_ID,
                "group_name": group_info.get('groupName'),
                "bot_in_group": True,
                "timestamp": time.time()
            })
        elif response.status_code == 400:
            # Bot không có trong group
            return jsonify({
                "status": "error",
                "message": "Bot is NOT in this group",
                "group_id": LINE_GROUP_ID,
                "bot_in_group": False,
                "solution": "Add bot to group using: https://line.me/R/ti/g/{LINE_GROUP_ID}",
                "timestamp": time.time()
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"API Error: {response.status_code}",
                "details": response.text,
                "timestamp": time.time()
            }), 400
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    """Webhook đơn giản"""
    if request.method == 'GET':
        return 'OK', 200
    
    try:
        data = request.json
        events = data.get('events', [])
        
        for event in events:
            if event.get('type') == 'message':
                message = event.get('message', {})
                if message.get('type') == 'text':
                    text = message.get('text', '').strip()
                    source = event.get('source', {})
                    group_id = source.get('groupId')
                    
                    logger.info(f"📨 Message: {text} in group: {group_id}")
                    
                    # Phản hồi đơn giản
                    if text == '.hello':
                        send_line_message(group_id, "👋 Hello from bot!")
                    
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200

# ==================== CHẠY SERVER ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🚀 LINE BOT DEBUG SERVER")
    logger.info(f"👥 Target Group: {LINE_GROUP_ID}")
    logger.info("="*60)
    
    # Test token khi khởi động
    logger.info("🔐 Testing token...")
    is_valid, bot_info = test_token()
    
    if is_valid:
        logger.info(f"✅ Token valid! Bot: {bot_info.get('displayName')}")
    else:
        logger.error("❌ Token invalid! Check your LINE Developer Console")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
