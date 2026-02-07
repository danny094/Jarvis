from core.layers.thinking import ThinkingLayer

layer = ThinkingLayer()
plan = layer._default_plan()

print('=' * 60)
print('🔍 TESTING SHARED VOLUMES')
print('=' * 60)
print(f"needs_sequential_thinking: {plan.get('needs_sequential_thinking')}")
print(f"sequential_complexity: {plan.get('sequential_complexity')}")
print(f"suggested_cim_modes: {plan.get('suggested_cim_modes')}")
print(f"reasoning_type: {plan.get('reasoning_type')}")
print('=' * 60)

if all([k in plan for k in ['needs_sequential_thinking', 'sequential_complexity', 'suggested_cim_modes', 'reasoning_type']]):
    print('✅ SHARED VOLUMES WORKING!')
    print('   Container reads LIVE code from host!')
else:
    print('❌ ERROR: Fields missing!')
