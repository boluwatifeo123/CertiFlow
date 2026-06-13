from flask import Flask, request, jsonify
import json
import os

# Ensure project root is in sys.path for imports
import sys
sys.path.append(os.path.dirname(__file__))

from main import run_pipeline

app = Flask(__name__)

@app.route('/run', methods=['POST'])
def run():
    # Accept JSON payload; fall back to sample_request.json if none provided
    if request.is_json:
        payload = request.get_json()
    else:
        # Load sample request file
        sample_path = os.path.join(os.path.dirname(__file__), 'sample_request.json')
        with open(sample_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    try:
        result = run_pipeline(payload)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run on port 5000, enable debug for quick iteration
    app.run(host='0.0.0.0', port=5000, debug=True)
