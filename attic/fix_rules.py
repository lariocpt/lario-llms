import sqlite3

conn = sqlite3.connect('/home/lario/lario-llms/bifrost/config.db')
c = conn.cursor()

# Fix Simple Prompts
c.execute("""
UPDATE routing_rules 
SET cel_expression = 'body.messages.size() > 0 && body.messages[body.messages.size() - 1].content.size() < 200' 
WHERE id = 'simple_rule'
""")

# Fix Vision Rule
c.execute("""
UPDATE routing_rules 
SET cel_expression = 'body.messages.exists(m, type(m.content) == list) || (body.model != null && body.model.contains("vision"))' 
WHERE id = 'vision_rule'
""")

# Delete tests
c.execute("DELETE FROM routing_rules WHERE id LIKE 'test_%'")

conn.commit()
conn.close()
print("Rules fixed!")
