import sqlite3
import datetime

conn = sqlite3.connect('/home/lario/Shared/personal/lario-llms/bifrost/config.db')
c = conn.cursor()

# 1. Rename key
c.execute("UPDATE config_keys SET key_id = 'local_llm_key' WHERE key_id = 'ollama_key'")
c.execute("UPDATE config_keys SET name = 'Local LLM Key' WHERE key_id = 'local_llm_key'")

# 2. Update routing targets
c.execute("UPDATE routing_targets SET provider = 'llamacpp' WHERE provider = 'ollama'")
c.execute("UPDATE routing_targets SET key_id = 'local_llm_key' WHERE key_id = 'ollama_key'")

# 3. Delete old models we don't need
c.execute("DELETE FROM config_models WHERE id IN ('glm-4.7-flash', 'glm-4.7-flash:bf16', 'qwen3-coder:30b', 'qwen3-coder-next', 'Qwen3-Coder-Next')")

# 4. Insert smart gateway rule (default routing to qwen-3.6)
# Lower priority than vision rule so vision can catch images first
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
cel_expr_default = "true" # Fallback rule if no other rules match
c.execute("DELETE FROM routing_rules WHERE id='smart_gateway_default'")
c.execute("DELETE FROM routing_targets WHERE rule_id='smart_gateway_default'")

c.execute("""
INSERT INTO routing_rules (
    id, name, description, enabled, cel_expression, scope, chain_rule, priority, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    'smart_gateway_default', 'Smart Gateway (Qwen Fallback)', 'Routes default traffic to Qwen 3.6',
    1, cel_expr_default, 'global', 0, 50, now, now
))

c.execute("""
INSERT INTO routing_targets (rule_id, provider, model, key_id, weight) 
VALUES (?, ?, ?, ?, ?)
""", ('smart_gateway_default', 'llamacpp', 'qwen-routing', 'local_llm_key', 1.0))

conn.commit()
conn.close()
print("Database migrated successfully.")
