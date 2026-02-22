from flask import Flask, jsonify, render_template, request, redirect, url_for
import sys
import subprocess
import datetime
import uuid  # Do generowania unikalnego ID historii

# Importujemy Solver
from Solver import BridgeSolver

app = Flask(__name__)

# --- BAZA DANYCH (W PAMIĘCI) ---
TABLE_STATE = {"N": None, "S": None, "E": None, "W": None}
GLOBAL_CONFIG = {"round": 1}
HISTORY_LOG = [] # Tutaj będziemy zapisywać wyniki z unikalnym ID

CURRENT_HANDS = {
    'N': ['AS', 'KS', 'QS', 'JS', 'TS', '9S', '8S', '7S', '6S', '5S', '4S', '3S', '2S'],
    'E': ['AH', 'KH', 'QH', 'JH', 'TH', '9H', '8H', '7H', '6H', '5H', '4H', '3H', '2H'],
    'S': ['AD', 'KD', 'QD', 'JD', 'TD', '9D', '8D', '7D', '6D', '5D', '4D', '3D', '2D'],
    'W': ['AC', 'KC', 'QC', 'JC', 'TC', '9C', '8C', '7C', '6C', '5C', '4C', '3C', '2C'],
}

try:
    bridge_solver = BridgeSolver("./libdds.so")
    print("Silnik DDS załadowany.")
except Exception as e:
    print(f"Błąd silnika DDS: {e}")

# --- TRASY HTML (Tylko rendering, bez logiki widoków tutaj) ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analyzer')
def analyzer():
    skip_check = request.args.get('mode') == 'solo'
    seats_taken = sum(1 for x in TABLE_STATE.values() if x is not None)
    if not skip_check and seats_taken < 4:
        return redirect(url_for('home'))
    return render_template('analyzer.html', round_num=GLOBAL_CONFIG["round"])

@app.route('/api/get_hands', methods=['GET'])
def get_hands_api():
    return jsonify(CURRENT_HANDS)

@app.route('/history')
def history():
    return render_template('history.html', history=list(reversed(HISTORY_LOG)))

@app.route('/settings')
def settings():
    return render_template('settings.html', current_round=GLOBAL_CONFIG["round"])

@app.route('/help')
def help_page():
    return render_template('help.html')

# --- API LOBBY ---

@app.route('/api/lobby_status', methods=['GET'])
def get_lobby_status():
    user_ip = request.remote_addr
    seats_info = {}
    seats_filled_count = 0
    
    for seat, occupant_ip in TABLE_STATE.items():
        if occupant_ip is None:
            seats_info[seat] = "free"
        elif occupant_ip == user_ip:
            seats_info[seat] = "mine"
            seats_filled_count += 1
        elif occupant_ip == "DEV_BOT":
            seats_info[seat] = "taken"
            seats_filled_count += 1
        else:
            seats_info[seat] = "taken"
            seats_filled_count += 1

    ready = (seats_filled_count == 4)
    current_round = GLOBAL_CONFIG["round"]
    
    dealer_map = ["N", "E", "S", "W"]
    dealer = dealer_map[(current_round - 1) % 4]
    
    vul_code = bridge_solver.get_vulnerability(current_round)
    vul_map = {0: "None", 1: "NS", 2: "EW", 3: "Both"}
    vulnerability = vul_map.get(vul_code, "None")

    return jsonify({
        "seats": seats_info,
        "round": current_round,
        "ready_to_play": ready,
        "dealer": dealer,
        "vulnerability": vulnerability
    })

@app.route('/api/toggle_seat/<seat>', methods=['POST'])
def toggle_seat(seat):
    user_ip = request.remote_addr
    if seat not in TABLE_STATE: return jsonify({"status": "error"})
    
    current = TABLE_STATE[seat]
    
    if current == user_ip:
        TABLE_STATE[seat] = None
        return jsonify({"status": "ok"})
    
    if current is None:
        for s, occ in TABLE_STATE.items():
            if occ == user_ip: TABLE_STATE[s] = None
        TABLE_STATE[seat] = user_ip
        return jsonify({"status": "ok"})

    return jsonify({"status": "busy"})

@app.route('/api/set_round', methods=['POST'])
def set_round():
    # POPRAWKA: get_json(silent=True)
    data = request.get_json(silent=True) or {}
    GLOBAL_CONFIG["round"] = int(data.get('round', GLOBAL_CONFIG["round"]))
    return jsonify({"status": "ok"})

# --- API DEVELOPERSKIE ---

@app.route('/api/dev/fill_seats', methods=['POST'])
def dev_fill_seats():
    for seat in TABLE_STATE:
        if TABLE_STATE[seat] is None:
            TABLE_STATE[seat] = "DEV_BOT"
    return jsonify({"status": "ok"})

@app.route('/api/dev/clear_seats', methods=['POST'])
def dev_clear_seats():
    for seat in TABLE_STATE:
        TABLE_STATE[seat] = None
    return jsonify({"status": "ok"})

@app.route('/api/dev/shutdown', methods=['POST'])
def dev_shutdown():
    try:
        subprocess.run(["sudo", "poweroff"])
        return jsonify({"status": "ok", "message": "System shutting down..."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- API SOLVERA I HISTORII ---

@app.route('/api/solve', methods=['POST'])
def solve_api():
    try:
        # POPRAWKA: get_json(silent=True)
        data = request.get_json(silent=True) or {}
        current_round = GLOBAL_CONFIG["round"]
        bid_contract = data.get("bid_contract", "none")
        
        # Wywołanie solvera
        result = bridge_solver.solve(CURRENT_HANDS, current_round)
        
        # Zapis do historii
        if result.get("status") == "ok":
            entry = {
                "id": str(uuid.uuid4()),
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "round": current_round,
                "contract": result.get("par_result", {}).get("optimal_contract", "N/A"),
                "score": result.get("par_result", {}).get("score", "N/A"),
                "bid_contract": bid_contract
            }
            HISTORY_LOG.append(entry)
            
        return jsonify(result)

    except Exception as e:
        # Tłumienie błędu Flaska i wymuszenie zwrotu JSON
        return jsonify({
            "status": "error",
            "message": f"Błąd po stronie serwera: {str(e)}"
        }), 500

@app.route('/api/edit_history/<entry_id>', methods=['POST'])
def edit_history(entry_id):
    """
    Pozwala na poprawę numeru rundy i wylicytowanego kontraktu w historii.
    """
    # POPRAWKA: get_json(silent=True)
    data = request.get_json(silent=True) or {}
    new_round = data.get("round")
    new_bid_contract = data.get("bid_contract")

    for entry in HISTORY_LOG:
        if entry["id"] == entry_id:
            if new_round is not None:
                entry["round"] = int(new_round)
            if new_bid_contract is not None:
                entry["bid_contract"] = str(new_bid_contract)
            return jsonify({"status": "ok", "entry": entry})
            
    return jsonify({"status": "error", "message": "History entry not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
