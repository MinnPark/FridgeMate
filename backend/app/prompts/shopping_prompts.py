REACT_PROMPT = """
Use ReAct.
Thought: identify missing ingredients and constraints.
Action: call shopping tools.
Observation: inspect product price, quantity, and budget result.
Repeat until the cart is valid or retry limit is reached.
Each loop must be logged as JSON-compatible Thought/Action/Observation records.
"""

REFLEXION_PROMPT = """
Use Reflexion after failed shopping attempts.
Explain why the previous attempt failed and add that lesson to the next loop context.
Avoid repeating the same search strategy.
Return a short Korean reflection and one changed search strategy.
"""
