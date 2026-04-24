from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/metrics/json")
def metrics():
    return jsonify({
        "cpu_usage": 42.5,
        "memory_usage": 68.2,
        "disk_usage": 71.9,
        "status": 1
    })

@app.route("/")
def index():
    return jsonify({"message": "mock api is running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)