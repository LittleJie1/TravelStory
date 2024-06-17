from flask import Flask, request, jsonify, abort
from flask_cors import CORS
import json
from time import strftime
from pymongo.mongo_client import MongoClient
import itertools
import requests  
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    UnfollowEvent,
)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# 讀取環境變數
with open('env.json') as f:
    env = json.load(f)

configuration = Configuration(access_token=env['CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(env['CHANNEL_SECRET'])

# 設置 MongoDB 連接
uri = "mongodb+srv://jiejieupup:1qaz2wsx@funtravelmap.nw4tnce.mongodb.net/?retryWrites=true&w=majority&appName=funtravelmap&tls=true&tlsAllowInvalidCertificates=true"
mongo_client = MongoClient(uri)

try:
    mongo_client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

db = mongo_client['web']
users = db['travel']

GOOGLE_MAPS_API_KEY = env['GOOGLE_MAPS_API_KEY']

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=event.message.text)]
            )
        )

@handler.add(FollowEvent)
def handle_follow(event):
    userid = event.source.user_id
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        profile = line_bot_api.get_profile(userid)
        existing_user = users.find_one({"_id": userid})

        if not existing_user:
            # insert into MongoDB
            u = {
                "_id": userid,
                "display_name": profile.display_name,
                "picture_url": profile.picture_url,
                "status_message": profile.status_message,
                "language": profile.language,
                "follow": strftime('%Y/%m/%d-%H:%M:%S'),
                "unfollow": None,
                "itineraries": []
            }
            users.insert_one(u)
        else:
            users.update_one(
                {"_id": userid},
                {"$set": {"follow": strftime('%Y/%m/%d-%H:%M:%S'), "unfollow": None}}
            )

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    userid = event.source.user_id
    users.update_one(
        {"_id": userid},
        {"$set": {"unfollow": strftime('%Y/%m/%d-%H:%M:%S')}}
    )

@app.route('/get_itineraries', methods=['POST']) #-------------------------查看行程
def get_itineraries():
    user_id = request.json.get('user_id')
    
    if not user_id:
        return jsonify({'status': 'error', 'message': '需要提供使用者ID'}), 400

    try:
        user = users.find_one({"_id": user_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到使用者'}), 404

        itineraries = user.get('itineraries', [])
        return jsonify({'status': 'success', 'itineraries': itineraries})
    except Exception as e:
        print(f'獲取使用者行程時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'獲取使用者行程時發生錯誤: {str(e)}'}), 500


@app.route('/add_itinerary', methods=['POST'])  # -------------------------新建行程
def add_itinerary():
    data = request.json
    user_id = data.get('user_id')
    itinerary = data.get('itinerary')
    itinerary_id = itinerary.get('itinerary_id')
    itinerary_name = itinerary.get('name')
    days = itinerary.get('days')

    # 檢查必要的字段是否存在
    if not all([user_id, itinerary_id, itinerary_name, days]):
        print("Missing required fields")
        return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
    # 確保 days 是整數
    try:
        days = int(days)
    except ValueError:
        print("Invalid days value")
        return jsonify({'status': 'error', 'message': 'Invalid days value'}), 400
    # 初始化行程，每天的景點列表为空
    itinerary = {
        "itinerary_id": itinerary_id,
        "name": itinerary_name,
        "days": days,
        "places": [[] for _ in range(days)]
    }
    # 更新用戶的行程列表，添加新的行程
    result = users.update_one(
        {"_id": user_id},
        {"$push": {"itineraries": itinerary}}
    )

    # 檢查更新操作是否成功
    if result.modified_count > 0:
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to add itinerary'}), 500
    
@app.route('/delete_itinerary', methods=['POST']) #--------------------刪除行程
def delete_itinerary():
    user_id = request.json.get('user_id')
    itinerary_id = request.json.get('itinerary_id')
    print(f"接收到的 user_id: {user_id}, itinerary_id: {itinerary_id}")

    if not user_id or not itinerary_id:
        return jsonify({'status': 'error', 'message': '需要提供使用者ID和行程ID'}), 400

    try:
        user = users.find_one({"_id": user_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到使用者'}), 404

        # 找到並刪除對應的行程
        updated_itineraries = [it for it in user.get('itineraries', []) if it['itinerary_id'] != itinerary_id]
        users.update_one({"_id": user_id}, {"$set": {"itineraries": updated_itineraries}})
        return jsonify({'status': 'success', 'message': '行程已刪除'})
    except Exception as e:
        print(f'刪除行程時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'刪除行程時發生錯誤: {str(e)}'}), 500
    
@app.route('/add_place', methods=['POST'])  # --------------------加入行程
def add_place():
    data = request.json
    itinerary_id = data.get('itinerary_id')
    day_index = data.get('day_index')
    place = data.get('place')
    if not itinerary_id or day_index is None or not place:
        return jsonify({'status': 'error', 'message': '缺少行程ID或地點信息或天數索引'}), 400
    try:
        user = users.find_one({"itineraries.itinerary_id": itinerary_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404
        # 查找具體的行程
        itinerary = None
        for it in user['itineraries']:
            if it['itinerary_id'] == itinerary_id:
                itinerary = it
                break
        if not itinerary:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404
        # 確保 'places' 是一個包含多個子數組的列表，每個子數組代表一天的行程
        if not isinstance(itinerary['places'], list):
            itinerary['places'] = []

        # 初始化每一天的行程為一個列表
        while len(itinerary['places']) <= day_index:
            itinerary['places'].append([])

        # 將新的地點添加到指定的天數
        itinerary['places'][day_index].append(place)

        # 更新 MongoDB 中的用戶文檔
        users.update_one(
            {"_id": user['_id'], "itineraries.itinerary_id": itinerary_id},
            {"$set": {"itineraries.$.places": itinerary['places']}}
        )
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        print(f'添加地點時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'添加地點時發生錯誤: {str(e)}'}), 500
    
@app.route('/remove_day', methods=['POST']) # --------------------減天數
def remove_day():
    data = request.json
    itinerary_id = data.get('itinerary_id')

    if not itinerary_id:
        return jsonify({'status': 'error', 'message': '缺少行程ID'}), 400

    try:
        user = users.find_one({"itineraries.itinerary_id": itinerary_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404

        itinerary = next(it for it in user['itineraries'] if it['itinerary_id'] == itinerary_id)
        if itinerary['days'] <= 1:
            return jsonify({'status': 'error', 'message': '行程天數不能少於1天'}), 400

        users.update_one(
            {"itineraries.itinerary_id": itinerary_id},
            {"$inc": {"itineraries.$.days": -1}, "$pop": {"itineraries.$.places": 1}}
        )
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        print(f'刪除天數時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'刪除天數時發生錯誤: {str(e)}'}), 500
    
@app.route('/add_day', methods=['POST']) # ------------------------加天數
def add_day():
    data = request.json
    itinerary_id = data.get('itinerary_id')

    if not itinerary_id:
        return jsonify({'status': 'error', 'message': '缺少行程ID'}), 400

    try:
        user = users.find_one({"itineraries.itinerary_id": itinerary_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404

        users.update_one(
            {"itineraries.itinerary_id": itinerary_id},
            {"$inc": {"itineraries.$.days": 1}, "$push": {"itineraries.$.places": []}}
        )
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        print(f'添加天數時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'添加天數時發生錯誤: {str(e)}'}), 500

@app.route('/move_place', methods=['POST'])  # --------------------移動景點順序
def move_place():
    data = request.json
    itinerary_id = data.get('itinerary_id')
    day_index = data.get('day_index')
    place_index = data.get('place_index')
    direction = data.get('direction')

    if not all([itinerary_id, day_index is not None, place_index is not None, direction]):
        return jsonify({'status': 'error', 'message': '缺少必要的字段'}), 400

    try:
        user = users.find_one({"itineraries.itinerary_id": itinerary_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404

        itinerary = next(it for it in user['itineraries'] if it['itinerary_id'] == itinerary_id)
        places = itinerary['places'][day_index]

        if direction == 'up' and place_index > 0:
            places.insert(place_index - 1, places.pop(place_index))
        elif direction == 'down' and place_index < len(places) - 1:
            places.insert(place_index + 1, places.pop(place_index))
        else:
            return jsonify({'status': 'error', 'message': '移動方向無效或位置錯誤'}), 400

        users.update_one(
            {"_id": user['_id'], "itineraries.itinerary_id": itinerary_id},
            {"$set": {"itineraries.$.places": itinerary['places']}}
        )
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        print(f'移動地點時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'移動地點時發生錯誤: {str(e)}'}), 500

@app.route('/delete_place', methods=['POST'])  # --------------------移動景點順序
def delete_place():
    data = request.json
    itinerary_id = data.get('itinerary_id')
    day_index = data.get('day_index')
    place_index = data.get('place_index')

    if not all([itinerary_id, day_index is not None, place_index is not None]):
        return jsonify({'status': 'error', 'message': '缺少必要的字段'}), 400

    try:
        user = users.find_one({"itineraries.itinerary_id": itinerary_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404

        itinerary = next(it for it in user['itineraries'] if it['itinerary_id'] == itinerary_id)
        places = itinerary['places'][day_index]

        if place_index < 0 or place_index >= len(places):
            return jsonify({'status': 'error', 'message': '地點索引無效'}), 400

        places.pop(place_index)

        users.update_one(
            {"_id": user['_id'], "itineraries.itinerary_id": itinerary_id},
            {"$set": {"itineraries.$.places": itinerary['places']}}
        )
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        print(f'刪除地點時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'刪除地點時發生錯誤: {str(e)}'}), 500
    
 
@app.route('/optimize_route', methods=['POST']) # ------------------------------------------實現最短路徑按鈕
def optimize_route():
    data = request.json
    itinerary_id = data.get('itinerary_id')
    day_index = data.get('day_index')

    if not all([itinerary_id, day_index is not None]):
        return jsonify({'status': 'error', 'message': '缺少必要的字段'}), 400

    user = users.find_one({"itineraries.itinerary_id": itinerary_id})
    if not user:
        return jsonify({'status': 'error', 'message': '找不到行程'}), 404

    itinerary = next(it for it in user['itineraries'] if it['itinerary_id'] == itinerary_id)
    places = itinerary['places'][day_index]

    if len(places) < 2:
        return jsonify({'status': 'error', 'message': '地點數量不足'}), 400

    origins = '|'.join([f"{place['latitude']},{place['longitude']}" for place in places])

    try:
        response_data = calculate_distance_matrix(origins)
        if response_data['status'] != 'OK':
            return jsonify({'status': 'error', 'message': 'Google API錯誤'}), 500

        distances = [[element['distance']['value'] for element in row['elements']] for row in response_data['rows']]
        sorted_places = find_best_route(distances, places)

        # 更新 MongoDB 中的行程順序
        users.update_one(
            {"_id": user['_id'], "itineraries.itinerary_id": itinerary_id},
            {"$set": {f"itineraries.$.places.{day_index}": sorted_places}}
        )
        return jsonify({'status': 'success', 'route': sorted_places}), 200

    except Exception as e:
        print(f'優化路徑時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'優化路徑時發生錯誤: {str(e)}'}), 500
    
def calculate_distance_matrix(origins): #-----------------------------------計算景點之間距離矩陣
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={origins}&destinations={origins}&key={GOOGLE_MAPS_API_KEY}"
    response = requests.get(url)
    response_data = response.json()
    return response_data

def find_best_route(distances, places): #-----------------------------------計算查找最佳路線
    num_places = len(places)  # 獲取地點數量
    indices = list(range(num_places))  # 創建一個地點索引的列表 [0, 1, 2, ...]
    min_distance = float('inf')  # 初始化最小距離為正無窮大
    best_permutation = indices  # 初始化最佳排列為地點的原始順序
    cache = {}  # 初始化一個字典用來緩存計算過的排列組合的總距離

    def calculate_total_distance(permutation):
        # 如果該排列組合的距離已經計算過，直接從緩存中獲取
        if permutation in cache:
            return cache[permutation]
        
        # 計算該排列組合的總距離
        total_distance = sum(distances[permutation[i]][permutation[i+1]] for i in range(len(permutation) - 1))
        
        # 將計算結果存入緩存中
        cache[permutation] = total_distance
        return total_distance

    # 遍歷所有地點的所有排列組合
    for permutation in itertools.permutations(indices):
        total_distance = calculate_total_distance(permutation)  # 計算當前排列的總距離
        
        # 如果當前排列的總距離小於已知最小距離，則更新最小距離和最佳排列
        if total_distance < min_distance:
            min_distance = total_distance
            best_permutation = permutation

    # 根據最佳排列重新排序地點
    sorted_places = [places[i] for i in best_permutation]
    return sorted_places

@app.route('/update_place_order', methods=['POST'])# ------------------------------------------拖曳方式移動景點順序
def update_place_order():
    data = request.json
    itinerary_id = data.get('itinerary_id')
    day_index = data.get('day_index')
    places = data.get('places')

    if not all([itinerary_id, day_index is not None, places]):
        return jsonify({'status': 'error', 'message': '缺少必要的字段'}), 400

    try:
        user = users.find_one({"itineraries.itinerary_id": itinerary_id})
        if not user:
            return jsonify({'status': 'error', 'message': '找不到行程'}), 404

        itinerary = next(it for it in user['itineraries'] if it['itinerary_id'] == itinerary_id)
        itinerary['places'][day_index] = places

        users.update_one(
            {"_id": user['_id'], "itineraries.itinerary_id": itinerary_id},
            {"$set": {f"itineraries.$.places.{day_index}": places}}
        )
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        print(f'更新地點順序時發生錯誤: {e}')
        return jsonify({'status': 'error', 'message': f'更新地點順序時發生錯誤: {str(e)}'}), 500


if __name__ == '__main__':
    app.run()
