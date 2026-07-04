import sqlite3
import datetime
import json

db_path = '/home/lario/Shared/personal/lario-llms/bifrost/config.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Models to add
new_models = [
    'minimax-m2:latest',
    'minimax',
    'llama-3.2-11b-vision',
    'llama3.2-vision:latest',
    'qwen-3.6',
    'qwen-3.6:latest',
    'qwen3.6-coder',
    'gemma4:latest'
]

print("Adding models to config_models table...")
for model_id in new_models:
    # Check if model already exists
    c.execute("SELECT id FROM config_models WHERE id = ?", (model_id,))
    row = c.fetchone()
    if not row:
        c.execute("""
            INSERT INTO config_models (id, provider_id, name, created_at, updated_at)
            VALUES (?, 1, ?, ?, ?)
        """, (model_id, model_id, now, now))
        print(f"  + Registered: {model_id}")
    else:
        print(f"  (already registered): {model_id}")

# Fetch local_llm_key record to update models_json
print("\nUpdating models_json in config_keys table...")
c.execute("SELECT id, models_json FROM config_keys WHERE key_id = 'local_llm_key'")
key_row = c.fetchone()

if key_row:
    key_db_id, models_json_str = key_row
    try:
        models_list = json.loads(models_json_str) if models_json_str else []
    except Exception as e:
        print(f"  Error parsing current models_json: {e}. Starting with empty list.")
        models_list = []

    print(f"  Current models: {models_list}")
    
    updated = False
    for model_id in new_models:
        if model_id not in models_list:
            models_list.append(model_id)
            updated = True
            print(f"  + Added to key: {model_id}")
            
    if updated:
        new_models_json = json.dumps(models_list)
        c.execute("UPDATE config_keys SET models_json = ? WHERE id = ?", (new_models_json, key_db_id))
        print("  Successfully updated key configuration.")
    else:
        print("  Key configuration already contains all models.")
else:
    print("  WARNING: local_llm_key not found in config_keys table!")

conn.commit()
conn.close()
print("\nBifrost database update completed successfully!")
