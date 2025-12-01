# app.py (SERVER - FIX ĐỒNG BỘ CLIENT-SERVER)


# app.py (SERVER - FIX ĐỒNG BỘ CLIENT-SERVER VÀ LINE BOT)

from flask import Flask, request, jsonify

import requests

import os

@@ -14,7 +14,7 @@



app = Flask(__name__)




# TOKEN LINE BOT


# TOKEN LINE BOT - KIỂM TRA LẠI

LINE_CHANNEL_TOKEN = "gafJcryENWN5ofFbD5sHFR60emoVN0p8EtzvrjxesEi8xnNupQD6pD0cwanobsr3A1zr/wRw6kixaU0z42nVUaVduNufOSr5WDhteHfjf5hCHXqFKTe9UyjGP0xQuLVi8GdfWnM9ODmDpTUqIdxpiQdB04t89/1O/w1cDnyilFU="

SERVER_URL = "https://line-bot-server-m54s.onrender.com"



@@ -24,14 +24,14 @@

# ==================== 📊 BIẾN TOÀN CỤC ====================

# QUẢN LÝ PHIÊN LÀM VIỆC

active_session = {


    "is_active": False,           # Có phiên đang chạy không


    "username": None,             # Username đang active


    "user_id": None,              # ID của user LINE


    "start_time": None,           # Thời gian bắt đầu phiên


    "session_id": None,           # ID phiên làm việc


    "end_reason": None,           # Lý do kết thúc


    "end_time": None,             # Thời gian kết thúc


    "last_activity": None         # Thời gian hoạt động cuối


    "is_active": False,


    "username": None,


    "user_id": None,


    "start_time": None,


    "session_id": None,


    "end_reason": None,


    "end_time": None,


    "last_activity": None

}



# LỆNH ĐANG CHỜ XỬ LÝ

@@ -46,13 +46,11 @@ def cleanup_old_data():

    try:

        current_time = time.time()




        # Xóa cooldown cũ (5 phút)

        expired_cooldowns = [k for k, v in message_cooldown.items() 

                           if current_time - v > 300]

        for key in expired_cooldowns:

            del message_cooldown[key]




        # Xóa commands trống hoặc cũ (quá 30 phút)

        expired_commands = []

        for user_id, cmd in user_commands.items():

            if cmd.get('timestamp'):

@@ -85,18 +83,48 @@ def keep_alive():

        except Exception as e:

            print(f"⚠️ Keep-alive: {e}")




        time.sleep(300)  # 5 phút


        time.sleep(300)



# Khởi chạy keep-alive

keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)

keep_alive_thread.start()

print("🛡️ Keep-alive started")



# ==================== 📱 HÀM GỬI LINE ====================


def send_line_reply(reply_token, text):


    """Gửi tin nhắn reply LINE (ngay lập tức)"""


    try:


        key = f"reply_{reply_token}"


        current_time = time.time()


        if key in message_cooldown and current_time - message_cooldown[key] < 5:


            return False


            


        message_cooldown[key] = current_time


        


        url = 'https://api.line.me/v2/bot/message/reply'


        headers = {


            'Content-Type': 'application/json',


            'Authorization': f'Bearer {LINE_CHANNEL_TOKEN}'


        }


        data = {


            'replyToken': reply_token,


            'messages': [{'type': 'text', 'text': text}]


        }


        


        response = requests.post(url, headers=headers, json=data, timeout=3)


        if response.status_code == 200:


            print(f"✅ Đã reply LINE: {text[:50]}...")


            return True


        else:


            print(f"❌ Reply LINE failed: {response.status_code} - {response.text}")


            return False


    except Exception as e:


        logger.warning(f"Line reply failed: {e}")


        return False




def send_line_message(chat_id, text, chat_type="user"):


    """Gửi tin nhắn LINE"""


    """Gửi tin nhắn LINE push"""

    try:


        # Chống spam

        key = f"{chat_id}_{hash(text) % 10000}"

        current_time = time.time()

        if key in message_cooldown and current_time - message_cooldown[key] < 5:

@@ -115,9 +143,14 @@ def send_line_message(chat_id, text, chat_type="user"):

        }



        response = requests.post(url, headers=headers, json=data, timeout=3)


        return response.status_code == 200


        if response.status_code == 200:


            print(f"✅ Đã gửi LINE push: {text[:50]}...")


            return True


        else:


            print(f"❌ LINE push failed: {response.status_code} - {response.text}")


            return False

    except Exception as e:


        logger.warning(f"Line message failed: {e}")


        logger.warning(f"Line push failed: {e}")

        return False



def send_to_group(text):

@@ -126,6 +159,7 @@ def send_to_group(text):

        if LINE_GROUP_ID:

            return send_line_message(LINE_GROUP_ID, text, "group")

        else:


            print("❌ Không có LINE_GROUP_ID")

            return False

    except Exception as e:

        logger.error(f"Send to group error: {e}")

@@ -159,25 +193,21 @@ def start_new_session(username, user_id):

    return True, f"Đã bắt đầu phiên làm việc cho {username}"



def end_current_session(username=None, reason="normal_exit", message=""):


    """🔥 HÀM CHÍNH: Kết thúc phiên - LUÔN RESET PHIÊN"""


    """Kết thúc phiên - LUÔN RESET PHIÊN"""

    if not active_session["is_active"]:

        print(f"⚠️ Không có phiên nào để kết thúc")

        return False, "Không có phiên làm việc nào đang chạy"




    # Nếu có username, kiểm tra xem có khớp không

    if username and username != active_session["username"]:

        print(f"⚠️ Username không khớp: Active={active_session['username']}, Request={username}")


        # Vẫn reset phiên để đảm bảo đồng bộ

        current_username = active_session["username"]

    else:

        current_username = active_session["username"]



    print(f"📌 Đang kết thúc phiên: {current_username} - Lý do: {reason}")




    # LƯU THÔNG TIN PHIÊN TRƯỚC KHI RESET

    ended_session = active_session.copy()




    # 🔥 RESET PHIÊN NGAY LẬP TỨC

    active_session.update({

        "is_active": False,

        "username": None,

@@ -189,7 +219,6 @@ def end_current_session(username=None, reason="normal_exit", message=""):

        "last_activity": None

    })




    # Xóa lệnh của user này nếu có

    user_id_to_delete = None

    for uid, cmd in user_commands.items():

        if cmd.get('username') == current_username:

@@ -202,7 +231,6 @@ def end_current_session(username=None, reason="normal_exit", message=""):



    print(f"✅ ĐÃ KẾT THÚC PHIÊN: {current_username} - Reason: {reason}")




    # 🔥 GỬI THÔNG BÁO LINE NẾU CÓ MESSAGE (chỉ cho .thoát web)

    if reason == "normal_exit" and message:

        send_to_group(message)



@@ -216,7 +244,6 @@ def force_end_session(reason="force_end", message=""):

    username = active_session["username"]

    print(f"📌 Đang force end phiên: {username} - Lý do: {reason}")




    # RESET PHIÊN

    active_session.update({

        "is_active": False,

        "username": None,

@@ -266,48 +293,52 @@ def get_session_info():

        "is_ready_for_new_session": False

    }




# ==================== 🌐 WEBHOOK LINE ====================


# ==================== 🌐 WEBHOOK LINE - FIX KHÔNG TRẢ LỜI ====================



@app.route('/webhook', methods=['POST'])

def line_webhook():


    """Webhook nhận lệnh từ LINE"""


    """Webhook nhận lệnh từ LINE - ĐÃ FIX"""

    try:


        # 🔥 LOG REQUEST ĐỂ DEBUG


        print(f"📥 Nhận webhook từ LINE...")


        

        data = request.get_json()

        events = data.get('events', [])




        print(f"📊 Số events: {len(events)}")


        

        for event in events:

            event_type = event.get('type')

            source = event.get('source', {})

            user_id = source.get('userId')

            group_id = source.get('groupId')


            reply_token = event.get('replyToken')




            # CHỈ XỬ LÝ TRONG NHÓM


            if not group_id:


                continue


                


            target_id = group_id


            print(f"🔍 Event: {event_type}, User: {user_id}, Group: {group_id}, ReplyToken: {reply_token}")



            if event_type == 'message':

                message_text = event.get('message', {}).get('text', '').strip()


                print(f"💬 Message: {message_text}")


                


                # XÁC ĐỊNH TARGET_ID (ƯU TIÊN GROUP)


                target_id = group_id if group_id else user_id



                # LỆNH LOGIN

                if message_text.startswith('.login '):

                    credentials = message_text[7:]

                    if ':' in credentials:

                        username, password = credentials.split(':', 1)




                        # KIỂM TRA PHIÊN ĐANG CHẠY

                        session_info = get_session_info()

                        if session_info["is_active"]:

                            current_user = session_info["username"]


                            send_line_message(target_id, 


                            send_line_reply(reply_token, 

                                f"⚠️ **{current_user} đang sử dụng tools.**\n\n"

                                f"📌 Vui lòng đợi {current_user} thoát web (.thoát web)\n"

                                f"💡 Trạng thái: CHỈ 1 PHIÊN tại thời điểm"

                            )

                            continue




                        # Tạo command mới

                        command_id = f"cmd_{int(time.time())}"

                        user_commands[user_id] = {

                            "id": command_id,

@@ -318,11 +349,11 @@ def line_webhook():

                            "session_required": True

                        }




                        send_line_message(target_id, f"✅ Đã nhận lệnh đăng nhập cho {username}")


                        send_line_reply(reply_token, f"✅ Đã nhận lệnh đăng nhập cho {username}")

                        print(f"📨 Lệnh login cho {username} từ user_id: {user_id}")



                    else:


                        send_line_message(target_id, "❌ Sai cú pháp! Dùng: .login username:password")


                        send_line_reply(reply_token, "❌ Sai cú pháp! Dùng: .login username:password")



                # 🔥 LỆNH THOÁT WEB

                elif message_text in ['.thoát web', '.thoat web', '.stop', '.dừng', '.exit']:

@@ -331,7 +362,6 @@ def line_webhook():

                    if session_info["is_active"]:

                        current_user = session_info["username"]




                        # 🔥 GỬI LỆNH STOP ĐẾN CLIENT

                        active_user_id = active_session["user_id"]

                        if active_user_id:

                            command_id = f"cmd_stop_{int(time.time())}"

@@ -344,9 +374,8 @@ def line_webhook():

                            }

                            print(f"📤 Đã gửi lệnh stop đến client: {current_user}")




                        send_line_message(target_id, f"🚪 **Đang yêu cầu {current_user} thoát web...**")


                        send_line_reply(reply_token, f"🚪 **Đang yêu cầu {current_user} thoát web...**")




                        # ĐỢI 2 GIÂY RỒI TỰ ĐỘNG KẾT THÚC PHIÊN

                        def delayed_end_session():

                            time.sleep(2)

                            session_info_check = get_session_info()

@@ -361,7 +390,7 @@ def delayed_end_session():

                        threading.Thread(target=delayed_end_session, daemon=True).start()



                    else:


                        send_line_message(target_id, "❌ Không có phiên làm việc nào đang chạy")


                        send_line_reply(reply_token, "❌ Không có phiên làm việc nào đang chạy")



                # LỆNH STATUS

                elif message_text in ['.status', '.trangthai', 'status']:

@@ -383,9 +412,9 @@ def delayed_end_session():



💡 Gõ '.login username:password' để bắt đầu phiên làm việc mới"""




                    send_line_message(target_id, status_text)


                    send_line_reply(reply_token, status_text)




                # LỆNH HELP - ĐÃ SỬA ĐỂ HIỂN THỊ MENU NHƯ YÊU CẦU


                # LỆNH HELP

                elif message_text in ['.help', 'help', 'hướng dẫn', '.huongdan']:

                    help_text = """📋 **LỆNH SỬ DỤNG:**

• `.login username:password` 

@@ -402,10 +431,21 @@ def delayed_end_session():

• **KHÔNG** cho phép login mới khi có phiên đang chạy

• Phải **.thoát web** hoàn toàn trước khi bắt đầu phiên mới"""




                    send_line_message(target_id, help_text)


                    send_line_reply(reply_token, help_text)


                


                # LỆNH TEST (ẩn)


                elif message_text == '.test':


                    send_line_reply(reply_token, "✅ Bot đang hoạt động bình thường!")


                


                # KHÔNG PHẢI LỆNH - BỎ QUA


                else:


                    # Không reply các tin nhắn thường


                    pass



            elif event_type == 'join':


                welcome_text = """🎉 **Bot Ticket Automation** đã tham gia nhóm!


                # Khi bot được thêm vào group


                if group_id:


                    welcome_text = """🎉 **Bot Ticket Automation** đã tham gia nhóm!



📋 **QUY TRÌNH LÀM VIỆC:**

1️⃣ .login username:password → Bắt đầu phiên mới

@@ -414,13 +454,13 @@ def delayed_end_session():

4️⃣ Chờ phiên tiếp theo



💡 **Lưu ý:** KHÔNG cho phép login mới khi có phiên đang chạy!"""


                send_line_message(target_id, welcome_text)


                    send_line_message(group_id, welcome_text)




        return jsonify({"status": "success"})


        return jsonify({"status": "success", "message": "Webhook processed"})



    except Exception as e:

        logger.error(f"Webhook error: {e}")


        return jsonify({"status": "error", "message": str(e)})


        return jsonify({"status": "error", "message": str(e)}), 500



# ==================== 🎯 API QUẢN LÝ PHIÊN ====================



@@ -437,7 +477,6 @@ def api_start_session():



        print(f"📥 Yêu cầu start_session: {username} ({user_id})")




        # KIỂM TRA PHIÊN ĐANG CHẠY

        session_info = get_session_info()

        if session_info["is_active"]:

            current_user = session_info["username"]

@@ -447,10 +486,8 @@ def api_start_session():

                "current_session": session_info

            })




        # BẮT ĐẦU PHIÊN MỚI

        success, message = start_new_session(username, user_id)

        if success:


            # 🔥 GỬI THÔNG BÁO LINE TỪ SERVER

            send_to_group(f"🎯 **BẮT ĐẦU PHIÊN MỚI**\n👤 User: {username}")



            return jsonify({

@@ -467,7 +504,7 @@ def api_start_session():



@app.route('/api/end_session', methods=['POST'])

def api_end_session():


    """🔥 API để client thông báo kết thúc phiên - LUÔN RESET PHIÊN NGAY"""


    """API để client thông báo kết thúc phiên"""

    try:

        data = request.get_json()

        username = data.get('username')

@@ -476,7 +513,6 @@ def api_end_session():



        print(f"📥 Nhận end_session từ client: username={username}, reason={reason}")




        # 🔥 LUÔN GỌI end_current_session ĐỂ RESET PHIÊN

        success, result_message = end_current_session(username, reason, message)



        if success:

@@ -500,15 +536,14 @@ def api_end_session():



@app.route('/api/force_end_session', methods=['POST'])

def api_force_end_session():


    """🔥 API force end session - RESET PHIÊN KHÔNG CẦN VERIFY"""


    """API force end session"""

    try:

        data = request.get_json()

        reason = data.get('reason', 'unknown')

        message = data.get('message', '')



        print(f"📥 Nhận force_end_session: reason={reason}")




        # 🔥 LUÔN GỌI force_end_session

        success, result_message = force_end_session(reason, message)



        if success:

@@ -542,7 +577,7 @@ def api_get_session_info():



@app.route('/api/send_to_group', methods=['POST'])

def api_send_to_group():


    """API để client gửi thông báo LINE (dùng cho 3 trường hợp lỗi)"""


    """API để client gửi thông báo LINE"""

    try:

        data = request.get_json()

        message = data.get('message')

@@ -581,7 +616,6 @@ def api_register_local():



        print(f"📥 Nhận yêu cầu register_local từ IP: {client_ip}")




        # Tìm user_id có lệnh đang chờ

        if user_commands:

            user_id = next(iter(user_commands))

            command = user_commands[user_id]

@@ -656,6 +690,7 @@ def health():

        "timestamp": datetime.now().isoformat(),

        "session": session_info,

        "pending_commands": len(user_commands),


        "line_bot_status": "✅ Webhook Active",

        "notification_flow": [

            "🔥 .thoát web → Server gửi LINE",

            "🔥 3 trường hợp khác → Client tự gửi LINE",

@@ -675,13 +710,14 @@ def home():



    return jsonify({

        "service": "LINE Ticket Automation Server",


        "version": "13.0 - ĐỒNG BỘ HOÀN TOÀN", 


        "version": "13.0 - FIX LINE BOT", 

        "status": status_message,


        "handling_strategy": [


            "🎯 4 trường hợp kết thúc phiên được đồng bộ hoàn toàn",


            "🎯 Server reset phiên ngay khi nhận yêu cầu từ client",


            "✅ Đảm bảo trạng thái luôn chính xác giữa client và server"


        ],


        "line_bot": {


            "webhook": "✅ Active",


            "reply_method": "✅ Using replyToken",


            "group_id": LINE_GROUP_ID,


            "commands": [".login", ".thoát web", ".status", ".help"]


        },

        "active_session": active_session,

        "pending_commands": list(user_commands.keys())

    })

@@ -692,26 +728,30 @@ def home():



    print(f"""

🚀 ========================================================


🚀 SERVER START - ĐỒNG BỘ CLIENT-SERVER


🚀 SERVER START - FIX LINE BOT KHÔNG TRẢ LỜI

🚀 ========================================================

🌐 Server URL: {SERVER_URL}

👥 LINE Group ID: {LINE_GROUP_ID}

🛡️ Keep-alive: ACTIVE

🧹 Auto-cleanup: ENABLED




🎯 QUY TẮC HOẠT ĐỘNG:


• CHỈ 1 PHIÊN tại thời điểm


• KHÔNG cho login mới khi có phiên đang chạy


🎯 LINE BOT FIXES:


• ✅ Dùng replyToken thay vì push message


• ✅ Xử lý cả group và private chat


• ✅ Trả lời ngay khi nhận lệnh


• ✅ Có log debug chi tiết




🔴 4 TRƯỜNG HỢP KẾT THÚC (ĐỒNG BỘ):


🔴 4 TRƯỜNG HỢP KẾT THÚC:

  1. .thoát web → Server tự kết thúc + Gửi LINE → STANDBY

  2. Đăng nhập lỗi → Client gửi LINE → Server reset NGAY → STANDBY  

  3. Tắt web đột ngột → Client gửi LINE → Server reset NGAY → STANDBY

  4. Đến mốc thời gian → Client gửi LINE → Server reset NGAY → STANDBY




✅ API RESET HOẠT ĐỘNG:


• /api/end_session → Reset với username verify


• /api/force_end_session → Reset không cần verify


📋 LỆNH LINE BOT:


• .login username:password


• .thoát web


• .status


• .help



📊 TRẠNG THÁI HIỆN TẠI: {get_session_info()['status']}

👤 USER ACTIVE: {get_session_info()['username'] if get_session_info()['is_active'] else 'None'}
