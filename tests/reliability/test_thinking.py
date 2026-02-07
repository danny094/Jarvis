from core.layers.thinking import ThinkingLayer

layer = ThinkingLayer()
plan = layer._default_plan()

print('=' * 50)
print('DEFAULT PLAN TEST')
print('=' * 50)
print(f"needs_sequential_thinking: {plan.get('needs_sequential_thinking')}")
print(f"sequential_complexity: {plan.get('sequential_complexity')}")
print(f"suggested_cim_modes: {plan.get('suggested_cim_modes')}")
print(f"reasoning_type: {plan.get('reasoning_type')}")
print('=' * 50)
