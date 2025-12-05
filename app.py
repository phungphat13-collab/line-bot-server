from flask import Flask, request, jsonify
import requests
import time
import logging
import os
from datetime import datetime
import json

app = Flask(__name__)

# ==================== CẤU HÌNH ====================
LINE_CHANNEL_TOKEN = "7HxJf6ykrTfMuz918kpokPMNUZOqpRv8FcGoJM/dkP8uIaqrwU5xFC+M8RoLUxYkkfZdrokoC9pMQ3kJv/SKxXTWTH1KhUe9fdXsNqVZXTA1w21+Wp1ywTQxZQViR2DVqR8w6CPvQpFJCbdvynuvSQdB04t89/1O/w1cDnyilFU="

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

def get_bot_groups():
    """Lấy danh sách tất cả group mà bot đang tham gia"""
    try:
        url = "https://api.line.me/v2/bot/group/list"
        headers = {'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            groups = data.get('groups', [])
            logger.info(f"📊 Bot is in {len(groups)} groups")
            return groups
        else:
            logger.error(f"❌ Failed to get groups: {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"❌ Get groups error: {e}")
        return []

def send_to_group(group_id, message):
    """Gửi tin nhắn đến group"""
    try:
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'
        }
        
        data = {
            'to': group_id,
            'messages': [{"type": "text", "text": message}]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ Sent to group {group_id[:10]}...")
            return True
        else:
            logger.error(f"❌ Send failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Send error: {e}")
        return False

# ========== ENDPOINTS ==========
@app.route('/')
def index():
    """Trang chủ"""
    groups = get_bot_groups()
    
    return jsonify({
        "status": "online",
        "bot_groups_count": len(groups),
        "groups": groups,
        "timestamp": time.time()
    })

@app.route('/debug_groups', methods=['GET'])
def debug_groups():
    """Debug: Hiển thị tất cả group bot đang tham gia"""
    groups = get_bot_groups()
    
    group_list = []
    for group in groups:
        group_list.append({
            "group_id": group.get('groupId'),
            "group_name": group.get('groupName', 'Unknown'),
            "group_type": "Regular Group" if group.get('groupId', '').startswith('C') else "Other"
        })
    
    return jsonify({
        "status": "success",
        "total_groups": len(groups),
        "groups": group_list,
        "timestamp": time.time()
    })

@app.route('/find_real_group_id', methods=['GET'])
def find_real_group_id():
    """
    Tìm Group ID thực sự từ link ID
    Bằng cách gửi test message và xem webhook log
    """
    return jsonify({
        "instructions": "Để tìm Real Group ID, làm theo các bước:",
        "steps": [
            "1. Mở group LINE mà bot đã tham gia",
            "2. Gửi bất kỳ tin nhắn nào trong group",
            "3. Webhook sẽ nhận được event với REAL groupId",
            "4. Xem logs trên Render để thấy groupId thực",
            "5. Dùng groupId đó trong code"
        ],
        "webhook_url": "https://line-bot-server-m54s.onrender.com/webhook",
        "note": "Group ID thực thường bắt đầu bằng 'C' (ví dụ: C1234567890abcdef)"
    })

@app.route('/send_to_all_groups', methods=['GET'])
def send_to_all_groups():
    """Gửi test message đến tất cả group"""
    groups = get_bot_groups()
    results = []
    
    for group in groups:
        group_id = group.get('groupId')
        group_name = group.get('groupName', 'Unknown')
        
        message = f"📢 Test từ server\nGroup: {group_name}\nID: {group_id[:10]}...\nTime: {datetime.now().strftime('%H:%M:%S')}"
        
        success = send_to_group(group_id, message)
        
        results.append({
            "group_id": group_id,
            "group_name": group_name,
            "success": success
        })
    
    return jsonify({
        "status": "completed",
        "total_groups": len(groups),
        "results": results,
        "timestamp": time.time()
    })

@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    """Webhook - QUAN TRỌNG: Nơi lấy Group ID thực"""
    if request.method == 'GET':
        return 'OK', 200
    
    try:
        data = request.json
        events = data.get('events', [])
        
        logger.info("="*50)
        logger.info("📨 WEBHOOK EVENT RECEIVED")
        logger.info(f"Total events: {len(events)}")
        
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            source_type = source.get('type')
            
            logger.info(f"🎯 Event type: {event_type}")
            logger.info(f"🎯 Source type: {source_type}")
            
            if source_type == 'group':
                group_id = source.get('groupId')
                logger.info(f"✅ REAL GROUP ID FOUND: {group_id}")
                logger.info(f"🔗 Group ID type: {'C-prefix' if group_id.startswith('C') else 'Other'}")
                
                # Lưu vào file để xem sau
                with open('group_info.txt', 'w') as f:
                    f.write(f"Group ID: {group_id}\n")
                    f.write(f"Time: {datetime.now().isoformat()}\n")
                    f.write(f"Full event: {json.dumps(event, indent=2)}")
            
            if event_type == 'message':
                message = event.get('message', {})
                if message.get('type') == 'text':
                    text = message.get('text', '').strip()
                    logger.info(f"💬 Message text: {text}")
                    
                    # Phản hồi với Group ID thực
                    if source_type == 'group' and text == '.id':
                        group_id = source.get('groupId')
                        reply = f"👥 **GROUP ID THỰC**:\n`{group_id}`\n\n" \
                               f"⚠️ Dùng ID này trong code!"
                        send_to_group(group_id, reply)
                    
                    elif source_type == 'group' and text == '.test':
                        group_id = source.get('groupId')
                        reply = f"✅ Bot đang hoạt động!\n" \
                               f"📊 Group ID: {group_id}\n" \
                               f"🕒 {datetime.now().strftime('%H:%M:%S')}"
                        send_to_group(group_id, reply)
                    
                    elif source_type == 'group' and text == '.hello':
                        group_id = source.get('groupId')
                        send_to_group(group_id, "👋 Xin chào từ bot!")
        
        logger.info("="*50)
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'OK', 200

# ==================== CHẠY SERVER ====================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🚀 LINE BOT GROUP FINDER")
    logger.info("="*60)
    
    # Test token
    is_valid, bot_info = test_token()
    if is_valid:
        logger.info(f"✅ Bot: {bot_info.get('displayName')}")
        
        # Lấy groups
        groups = get_bot_groups()
        if groups:
            logger.info(f"📊 Bot is in {len(groups)} groups:")
            for group in groups:
                group_id = group.get('groupId')
                group_name = group.get('groupName', 'Unknown')
                logger.info(f"  • {group_name} - ID: {group_id}")
        else:
            logger.warning("⚠️ Bot is not in any groups")
    else:
        logger.error("❌ Token invalid!")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
