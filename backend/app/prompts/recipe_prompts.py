HYDE_PROMPT = """
Use HyDE for short recipe queries.
Generate a hypothetical recipe document, embed that document, then search VectorDB.
"""

RAG_FUSION_PROMPT = """
Use RAG-Fusion for complex food constraints.
Rewrite the query into multiple perspectives, retrieve independently, then combine rankings with RRF.
"""
