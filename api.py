from flask import Flask, jsonify, send_from_directory
import os

app = Flask(__name__)

# مسیر فایل جیسونی که توسط worker ساخته می‌شود
JSON_FILE = "signals.json"

@app.route('/signals', methods=['GET'])
def get_signals():
    """فایل جیسون را خوانده و محتوای آن را برمی‌گرداند"""
    if not os.path.exists(JSON_FILE):
        return jsonify({"status": "error", "message": "Signal file not found. Please run the worker first."}), 404
    
    # با send_from_directory فایل جیسون به درستی و با هدرهای صحیح ارسال می‌شود
    return send_from_directory('.', JSON_FILE, mimetype='application/json')

if __name__ == "__main__":
    print("🚀 Starting LIGHTWEIGHT Flask API server...")
    print("API is ready to serve data from signals.json")
    app.run(host='0.0.0.0', port=5000, debug=False)
