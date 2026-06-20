from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# リアルタイム通信を行うための設定
socketio = SocketIO(app, cors_allowed_origins="*")

# 接続中のユーザーを管理する辞書 { sid: username }
online_users = {}
# 現在進行中のゲームセッション { game_id: { player1: sid, player2: sid } }
active_games = {}

@app.route('/')
def index():
    # メインのHTMLを表示する
    return render_template('index.html')

# クライアントが接続したとき
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    # 初期ユーザー名（後からクライアント側で変更可能）
    username = f"プレイヤー_{sid[:5]}"
    online_users[sid] = username
    
    # 全員に最新のオンラインユーザーリストを送信
    emit('update_users', {
        'users': online_users,
        'my_id': sid
    }, broadcast=True)

# ユーザー名が設定・変更されたとき
@socketio.on('set_username')
def handle_set_username(data):
    sid = request.sid
    new_name = data.get('username', f"プレイヤー_{sid[:5]}")
    online_users[sid] = new_name
    
    # ユーザーリストを更新
    emit('update_users', {
        'users': online_users,
        'my_id': sid
    }, broadcast=True)

# クライアントが切断したとき
@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in online_users:
        del online_users[sid]
    
    # 関連する対戦中ゲームがあれば削除し、対戦相手に通知
    game_to_remove = None
    for game_id, players in active_games.items():
        if players['p1'] == sid or players['p2'] == sid:
            opponent_sid = players['p2'] if players['p1'] == sid else players['p1']
            emit('opponent_disconnected', room=opponent_sid)
            game_to_remove = game_id
            break
            
    if game_to_remove:
        del active_games[game_to_remove]

    # 全員に最新のオンラインユーザーリストを送信
    emit('update_users', {
        'users': online_users,
        'my_id': ''
    }, broadcast=True)

# 誰かに挑戦状を送る
@socketio.on('challenge_send')
def handle_challenge_send(data):
    sender_sid = request.sid
    target_sid = data.get('target_sid')
    
    if target_sid in online_users:
        # 挑戦相手にのみ、挑戦者の名前とIDを送る
        emit('challenge_received', {
            'challenger_id': sender_sid,
            'challenger_name': online_users[sender_sid]
        }, room=target_sid)

# 挑戦を承諾する
@socketio.on('challenge_accept')
def handle_challenge_accept(data):
    p2_sid = request.sid # 承諾した人
    p1_sid = data.get('challenger_id') # 挑んだ人
    
    if p1_sid in online_users and p2_sid in online_users:
        # ユニークなゲームIDを作成
        game_id = f"game_{p1_sid[:4]}_{p2_sid[:4]}"
        active_games[game_id] = {'p1': p1_sid, 'p2': p2_sid}
        
        # 双方にゲーム開始を通知
        # p1（ホスト側）
        emit('game_start', {
            'game_id': game_id,
            'role': 'p1',
            'opponent_name': online_users[p2_sid],
            'opponent_id': p2_sid
        }, room=p1_sid)
        
        # p2（ゲスト側）
        emit('game_start', {
            'game_id': game_id,
            'role': 'p2',
            'opponent_name': online_users[p1_sid],
            'opponent_id': p1_sid
        }, room=p2_sid)

# 挑戦を拒否する
@socketio.on('challenge_decline')
def handle_challenge_decline(data):
    p1_sid = data.get('challenger_id')
    if p1_sid in online_users:
        emit('challenge_declined', {
            'declined_by': online_users[request.sid]
        }, room=p1_sid)

# 対戦中のアクション（位置移動、弾発射、被弾、勝利判定など）を中継
@socketio.on('game_action')
def handle_game_action(data):
    sender_sid = request.sid
    opponent_sid = data.get('opponent_id')
    action_type = data.get('type')
    action_data = data.get('data')
    
    if opponent_sid in online_users:
        # 相手プレイヤーにアクションデータをそのまま転送する
        emit('opponent_action', {
            'type': action_type,
            'data': action_data
        }, room=opponent_sid)

if __name__ == '__main__':
    # サーバーを起動（ポート番号5000）
    socketio.run(app, debug=True, port=5000)
