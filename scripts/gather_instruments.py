import json
import os
import sys
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
from ticker_config import normalize_symbol, atomic_write_json

def prune_instrument(inst: dict) -> dict:
    """
    Prune redundant fields and keep essential keys for option calculation.
    """
    chain_sym = normalize_symbol(inst.get("chain_symbol"))
    return {
        "id": inst.get("id"),
        "chain_symbol": chain_sym,
        "expiration_date": inst.get("expiration_date"),
        "strike_price": str(inst.get("strike_price")),
        "type": inst.get("type")
    }

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
    parser = argparse.ArgumentParser(description="Gather option instruments from step outputs.")
    parser.add_argument("steps", nargs="+", help="Step numbers containing the get_option_instruments outputs.")
    args = parser.parse_args()

    brain_dir = get_active_brain_dir()
    instruments = []
    seen_ids = set()
    
    print(f"Processing {len(args.steps)} steps using brain directory: {brain_dir}")
    
    for step in args.steps:
        content = None
        f_path = os.path.join(brain_dir, ".system_generated", "steps", str(step), "output.txt")
        if os.path.exists(f_path):
            try:
                with open(f_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
            except Exception as e:
                print(f"Error reading {f_path}: {e}")
        if not content:
            transcript_path = os.path.join(brain_dir, ".system_generated", "logs", "transcript_full.jsonl")
            if os.path.exists(transcript_path):
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            step_data = json.loads(line)
                            if str(step_data.get("step_index")) == str(step):
                                content = step_data.get("content")
                                break
                        except Exception:
                            pass
        if not content:
            print(f"Warning: Step output file {f_path} not found.")
            continue
        try:
            data = json.loads(content) if isinstance(content, str) else content
            insts = None
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], dict):
                    insts = data["data"].get("instruments")
                else:
                    insts = data.get("instruments")
            
            if insts:
                for inst in insts:
                    inst_id = inst.get("id")
                    if inst_id and inst_id not in seen_ids:
                        instruments.append(prune_instrument(inst))
                        seen_ids.add(inst_id)
                print(f"Processed {len(insts)} instruments from step {step}")
        except Exception as e:
            print(f"Error processing step {step}: {e}")
            
    raw_inst_file = os.path.join(BASE_DIR, "data", "raw_instruments.json")
    if os.path.exists(raw_inst_file):
        try:
            with open(raw_inst_file, 'r', encoding='utf-8') as f:
                existing_insts = json.load(f)
            for inst in existing_insts:
                inst_id = inst.get("id")
                if inst_id and inst_id not in seen_ids:
                    instruments.append(prune_instrument(inst))
                    seen_ids.add(inst_id)
            print(f"Merged {len(existing_insts)} existing instruments.")
        except Exception as e:
            print(f"Error loading existing instruments: {e}")

    atomic_write_json(raw_inst_file, instruments)
    print(f"Successfully gathered and pruned {len(instruments)} unique instruments to {raw_inst_file}")

if __name__ == "__main__":
    main()
