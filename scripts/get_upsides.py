import requests
import json

def main():
    try:
        resp = requests.get("http://127.0.0.1:8000/state", timeout=5)
        if resp.status_code != 200:
            print(f"Error: status code {resp.status_code}")
            return
        state = resp.json()
    except Exception as e:
        print(f"Failed to connect to engine: {e}")
        return

    metrics = state.get("metrics", {})
    print("Metrics keys and values:")
    for k, v in metrics.items():
        print(f"{k}: {v}")

if __name__ == '__main__':
    main()
