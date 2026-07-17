import sqlite3

conn = sqlite3.connect('/home/lario/lario-llms/bifrost/config.db')
c = conn.cursor()

c.execute("DELETE FROM routing_rules WHERE id LIKE 'test_%'")

tests = [
    ('test_req', 'req.body.messages.size() > 0'),
    ('test_body', 'body.messages.size() > 0'),
    ('test_payload', 'payload.messages.size() > 0'),
    ('test_messages', 'messages.size() > 0'),
    ('test_request', 'request.messages.size() > 0'),
    ('test_prompt', 'prompt.size() > 0')
]

for t in tests:
    c.execute("""
    INSERT INTO routing_rules (
        id, name, description, enabled, cel_expression, scope, chain_rule, priority, created_at, updated_at
    ) VALUES (?, ?, ?, 1, ?, 'global', 0, 10, datetime('now'), datetime('now'))
    """, (t[0], t[0], '', t[1]))

conn.commit()
conn.close()
