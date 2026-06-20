from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid

app = Flask(__name__)
# リアルタイム同期およびロビー招待システム用の設定
socketio = SocketIO(app, cors_allowed_origins="*")

# 接続中のオンラインプレイヤー管理
# { sid: { id, name, room, status: 'lobby'|'playing' } }
online_players = {}

@app.route('/')
def index():
    # ゲーム画面を表示
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    # 初期状態のユーザーを作成
    online_players[sid] = {
        "sid": sid,
        "id": str(uuid.uuid4())[:8],
        "name": "ブローラー",
        "room": "public",
        "status": "lobby"
    }
    # 初期状態としてpublic部屋に参加させる
    join_room("public")
    # 自分に個人情報を伝える
    emit('me', online_players[sid])
    # 全員に最新のオンラインリストを同期
    send_online_list()

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in online_players:
        player = online_players[sid]
        room = player["room"]
        leave_room(room)
        # 部屋の他のメンバーにスロット退室通知
        emit('player_left', {"sid": sid, "id": player["id"]}, to=room)
        del online_players[sid]
    send_online_list()

@socketio.on('set_name')
def handle_set_name(data):
    sid = request.sid
    if sid in online_players:
        online_players[sid]["name"] = data.get("name", "ブローラー")[:12]
        # 自分の情報を再送信
        emit('me', online_players[sid])
        # 全員に通知
        send_online_list()
        # 同じロビーの仲間にも同期
        room = online_players[sid]["room"]
        emit('room_sync_trigger', to=room)

# --- ロビー・同期システム ---
@socketio.on('join_lobby')
def handle_join_lobby(data):
    sid = request.sid
    if sid not in online_players: return
    
    old_room = online_players[sid]["room"]
    leave_room(old_room)
    emit('player_left', {"sid": sid, "id": online_players[sid]["id"]}, to=old_room)

    new_room = data.get("room", "public")
    online_players[sid]["room"] = new_room
    join_room(new_room)
    
    # ロビー内の全員に通知
    emit('player_joined', {
        "sid": sid,
        "id": online_players[sid]["id"],
        "name": online_players[sid]["name"]
    }, to=new_room)
    
    send_online_list()

# スロットの状態変更（キャラクター設定、ガジェット、スターパワー、スロットの選択）を部屋メンバーにブロードキャスト
@socketio.on('update_slot')
def handle_update_slot(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        # スロット変更データをロビーの全員（自分以外）に伝える
        emit('slot_updated', {
            "sid": sid,
            "id": online_players[sid]["id"],
            "name": online_players[sid]["name"],
            "slotIndex": data.get("slotIndex"),
            "brawler": data.get("brawler"),
            "gadget": data.get("gadget"),
            "sp": data.get("sp"),
            "enabled": data.get("enabled"),
            "isPlayer": data.get("isPlayer")
        }, to=room, include_self=False)

# ゲームモードの変更同期
@socketio.on('update_mode')
def handle_update_mode(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        emit('mode_updated', {"mode": data.get("mode")}, to=room, include_self=False)

# 誰かがゲームスタートを押したとき
@socketio.on('start_game')
def handle_start_game(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        # 全員をプレイ中ステータスにする
        for s, p in online_players.items():
            if p["room"] == room:
                p["status"] = "playing"
        emit('game_started', data, to=room)
        send_online_list()

# ゲームが終了してメニューに戻ったとき
@socketio.on('back_to_lobby')
def handle_back_to_lobby():
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        online_players[sid]["status"] = "lobby"
        emit('lobby_returned', to=room)
        send_online_list()

# --- 招待システム ---
@socketio.on('send_invite')
def handle_send_invite(data):
    # data: { targetSid: '...' }
    sid = request.sid
    target_sid = data.get("targetSid")
    if sid in online_players and target_sid in online_players:
        sender = online_players[sid]
        # ターゲットに招待通知を送る
        emit('invite_received', {
            "senderSid": sid,
            "senderName": sender["name"],
            "senderRoom": sender["room"]
        }, to=target_sid)

@socketio.on('respond_invite')
def handle_respond_invite(data):
    # data: { senderSid: '...', accept: true/false, senderRoom: '...' }
    sid = request.sid
    sender_sid = data.get("senderSid")
    accept = data.get("accept")
    
    if sid in online_players and sender_sid in online_players:
        receiver_name = online_players[sid]["name"]
        if accept:
            # 招待を承諾した場合、送り主のルームに移動
            room_to_join = data.get("senderRoom")
            old_room = online_players[sid]["room"]
            leave_room(old_room)
            emit('player_left', {"sid": sid, "id": online_players[sid]["id"]}, to=old_room)
            
            online_players[sid]["room"] = room_to_join
            join_room(room_to_join)
            
            # 招待承諾を送り主に伝える
            emit('invite_response', {
                "receiverName": receiver_name,
                "accept": True,
                "room": room_to_join
            }, to=sender_sid)
            
            # ロビー同期発火
            emit('room_sync_trigger', to=room_to_join)
        else:
            # 拒否を伝える
            emit('invite_response', {
                "receiverName": receiver_name,
                "accept": False
            }, to=sender_sid)
            
        send_online_list()

# --- リアルタイム対戦同期パケット ---
# 同一のロビー部屋内でプレイ中のプレイヤー同士の位置・行動を同期
@socketio.on('sync_pos')
def handle_sync_pos(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        data["sid"] = sid
        emit('sync_pos', data, to=room, include_self=False)

@socketio.on('sync_attack')
def handle_sync_attack(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        data["sid"] = sid
        emit('sync_attack', data, to=room, include_self=False)

@socketio.on('sync_damage')
def handle_sync_damage(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        emit('sync_damage', data, to=room, include_self=False)

@socketio.on('sync_die')
def handle_sync_die(data):
    sid = request.sid
    if sid in online_players:
        room = online_players[sid]["room"]
        data["sid"] = sid
        emit('sync_die', data, to=room, include_self=False)

def send_online_list():
    # 接続中の全員の情報をシリアライズして一括送信
    plist = list(online_players.values())
    socketio.emit('online_list', plist)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)