MEAL_PLAN_PROMPT = """
Plan-and-Execute planning step.
Create a weekly meal plan before selecting recipes.
Prioritize expiring pantry ingredients, nutrition goals, and ingredient reuse.
"""

MEAL_EXECUTE_PROMPT = """
Plan-and-Execute execution step.
For each planned meal, retrieve candidate recipes and verify nutrition using tools.
Do not estimate nutrition when a tool value is available.
"""
