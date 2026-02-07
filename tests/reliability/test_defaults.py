from core.layers.thinking import ThinkingLayer

layer = ThinkingLayer()
plan = layer._default_plan()

print('=' * 60)
print('DEFAULT PLAN TEST - AFTER REBUILD')
print('=' * 60)
print(f"needs_sequential_thinking: {plan.get('needs_sequential_thinking')}")
print(f"sequential_complexity: {plan.get('sequential_complexity')}")
print(f"suggested_cim_modes: {plan.get('suggested_cim_modes')}")
print(f"reasoning_type: {plan.get('reasoning_type')}")
print('=' * 60)
print()
if all([k in plan for k in ['needs_sequential_thinking', 'sequential_complexity', 'suggested_cim_modes', 'reasoning_type']]):
    print('✅ ALL NEW FIELDS PRESENT!')
else:
    print('❌ MISSING FIELDS!')
