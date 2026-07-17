import sqlite3
import datetime

conn = sqlite3.connect('/home/lario/Shared/personal/lario-llms/bifrost/config.db')
c = conn.cursor()

# Insert the rule
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Delete existing vision_rule if any
c.execute("DELETE FROM routing_rules WHERE id='vision_rule'")
c.execute("DELETE FROM routing_targets WHERE rule_id='vision_rule'")

# Expression checks if any message content is a list (which implies multimodal blocks in OpenAI format) 
# OR if the model explicitly requested contains 'vision'.
cel_expr = "request.body.messages.exists(m, type(m.content) == list) || (request.body.model != null && request.body.model.contains('vision'))"

c.execute("""
INSERT INTO routing_rules (
    id, name, description, enabled, cel_expression, scope, chain_rule, priority, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    'vision_rule',
    'Vision Fallback',
    'Routes multimodal image requests to Llama 3.2 Vision',
    1,
    cel_expr,
    'global',
    0,
    200, # High priority to catch images before others
    now,
    now
))

c.execute("""
INSERT INTO routing_targets (
    rule_id, provider, model, key_id, weight
) VALUES (?, ?, ?, ?, ?)
""", (
    'vision_rule',
    'llamacpp',
    'llama3.2-vision:latest',
    'local_llm_key',
    1.0
))

conn.commit()
conn.close()
print("Successfully added vision rule to Bifrost!")
