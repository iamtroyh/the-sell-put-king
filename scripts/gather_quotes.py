import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
from ticker_config import atomic_write_json

def get_active_brain_dir():
    base = os.path.expanduser("~/.gemini/jetski/brain")
    conv_id = os.environ.get("CONVERSATION_ID")
    if conv_id and os.path.exists(os.path.join(base, conv_id)):
        return os.path.join(base, conv_id)
    if os.path.exists(base):
        subdirs = [
            (os.path.join(base, d), os.path.getmtime(os.path.join(base, d)))
            for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d)) and os.path.exists(os.path.join(base, d, ".system_generated"))
        ]
        if subdirs:
            subdirs.sort(key=lambda x: x[1], reverse=True)
            return subdirs[0][0]
    return base

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.exists(arg):
            brain_dir = arg
        else:
            brain_dir = os.path.expanduser(f"~/.gemini/jetski/brain/{arg}")
    else:
        brain_dir = get_active_brain_dir()
        
    print(f"Using brain directory: {brain_dir}")
    steps_dir = os.path.join(brain_dir, ".system_generated", "steps")
    merged_quotes = []
    
    if os.path.exists(steps_dir):
        for step_name in sorted(os.listdir(steps_dir), key=lambda x: int(x) if x.isdigit() else 999999):
            if not step_name.isdigit():
                continue
            
            output_file = os.path.join(steps_dir, step_name, "output.txt")
            if not os.path.exists(output_file):
                continue
                
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    
                if not content.startswith("{"):
                    continue
                    
                data = json.loads(content)
                if "data" in data and isinstance(data["data"], dict) and "results" in data["data"]:
                    results = data["data"]["results"]
                    print(f"Step {step_name}: found {len(results)} quotes")
                    for item in results:
                        if "quote" in item and item["quote"]:
                            merged_quotes.append(item["quote"])
            except Exception:
                pass
            
    print(f"Total merged quotes: {len(merged_quotes)}")
    
    out_path = os.path.join(BASE_DIR, "data", "raw_quotes.json")
    atomic_write_json(out_path, merged_quotes)
    print(f"Successfully wrote merged quotes to {out_path}")

if __name__ == "__main__":
    main()
