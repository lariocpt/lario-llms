import os
from sentence_transformers import SentenceTransformer
from emm.pipeline.pipeline import Pipeline
import pandas as pd

print("Loading BAAI/bge-m3 embedding model...")
# Load the BGE-M3 model for semantic matching
embedder = SentenceTransformer("BAAI/bge-m3")

# Example data
queries = ["Global Widget Inc.", "SpaceX Corp"]
targets = ["Global Widget Incorporated", "Space Exploration Technologies Corp.", "Some Random Company"]

print("Generating embeddings...")
query_embeddings = embedder.encode(queries)
target_embeddings = embedder.encode(targets)

print("Semantic Match Results (Cosine Similarity):")
from sentence_transformers.util import cos_sim
similarity = cos_sim(query_embeddings, target_embeddings)
for i, query in enumerate(queries):
    for j, target in enumerate(targets):
        print(f"'{query}' vs '{target}' -> {similarity[i][j]:.4f}")

print("\n--- Testing ING's Entity Matching Model (EMM) ---")
# Create synthetic pandas dataframes
df_queries = pd.DataFrame({"id": [1, 2], "name": queries})
df_targets = pd.DataFrame({"id": [1, 2, 3], "name": targets})

# Set up a basic EMM pipeline
p = Pipeline([
    ('name_tfidf', {
        'type': 'tfidf',
        'col': 'name',
        'analyzer': 'char',
        'ngram_range': (2, 4)
    })
])

print("Fitting EMM pipeline...")
p.fit(df_targets)
matches = p.transform(df_queries)

print("EMM Matching Candidates:")
print(matches.head())
