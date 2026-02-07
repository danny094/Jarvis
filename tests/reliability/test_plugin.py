import pytest
import subprocess
import re
from pathlib import Path

PLUGIN_DIR = Path('/DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/js/plugins')
PLUGIN_MANAGER = Path('/DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/js/plugin-manager.js')
INDEX_HTML = Path('/DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/index.html')


class TestPluginSyntax:
    
    @pytest.mark.parametrize('plugin_file', [
        'sequential-thinking.js',
        'code-beautifier.js',
        'image-upload.js'
    ])
    def test_plugin_syntax_valid(self, plugin_file):
        filepath = PLUGIN_DIR / plugin_file
        if not filepath.exists():
            pytest.skip(f'{plugin_file} not found')
        
        result = subprocess.run(
            ['node', '--check', str(filepath)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f'Syntax error in {plugin_file}: {result.stderr}'


class TestPluginStructure:
    
    @pytest.mark.parametrize('plugin_file,class_name', [
        ('sequential-thinking.js', 'SequentialThinkingPlugin'),
        ('code-beautifier.js', 'CodeBeautifierPlugin'),
        ('image-upload.js', 'ImageUploadPlugin')
    ])
    def test_plugin_extends_base(self, plugin_file, class_name):
        filepath = PLUGIN_DIR / plugin_file
        if not filepath.exists():
            pytest.skip(f'{plugin_file} not found')
        
        content = filepath.read_text()
        pattern = rf'class\s+{class_name}\s+extends\s+PluginBase'
        assert re.search(pattern, content), f'{class_name} should extend PluginBase'
    
    @pytest.mark.parametrize('plugin_file', [
        'sequential-thinking.js',
        'code-beautifier.js',
        'image-upload.js'
    ])
    def test_plugin_registers(self, plugin_file):
        filepath = PLUGIN_DIR / plugin_file
        if not filepath.exists():
            pytest.skip(f'{plugin_file} not found')
        
        content = filepath.read_text()
        assert 'registerBuiltIn' in content, f'{plugin_file} should call registerBuiltIn'
    
    @pytest.mark.parametrize('plugin_file', [
        'sequential-thinking.js',
        'code-beautifier.js', 
        'image-upload.js'
    ])
    def test_plugin_has_init_method(self, plugin_file):
        filepath = PLUGIN_DIR / plugin_file
        if not filepath.exists():
            pytest.skip(f'{plugin_file} not found')
        
        content = filepath.read_text()
        assert 'init()' in content, f'{plugin_file} should have init() method'
    
    @pytest.mark.parametrize('plugin_file', [
        'sequential-thinking.js',
        'code-beautifier.js',
        'image-upload.js'
    ])
    def test_plugin_has_destroy_method(self, plugin_file):
        filepath = PLUGIN_DIR / plugin_file
        if not filepath.exists():
            pytest.skip(f'{plugin_file} not found')
        
        content = filepath.read_text()
        assert 'destroy()' in content, f'{plugin_file} should have destroy() method'


class TestPluginManagerIntegration:
    
    def test_plugin_manager_exists(self):
        assert PLUGIN_MANAGER.exists(), 'plugin-manager.js not found'
    
    def test_plugin_manager_has_init_all(self):
        content = PLUGIN_MANAGER.read_text()
        assert 'initAll()' in content, 'PluginManager missing initAll method'
    
    def test_index_loads_plugin_manager(self):
        content = INDEX_HTML.read_text()
        assert 'plugin-manager.js' in content, 'index.html should load plugin-manager.js'
    
    @pytest.mark.parametrize('plugin_file', [
        'sequential-thinking.js',
        'code-beautifier.js',
        'image-upload.js'
    ])
    def test_index_loads_plugin(self, plugin_file):
        content = INDEX_HTML.read_text()
        assert plugin_file in content, f'index.html should load {plugin_file}'
    
    def test_index_calls_init_all(self):
        content = INDEX_HTML.read_text()
        assert 'initAll()' in content, 'index.html should call initAll()'


class TestPluginLoadOrder:
    
    def test_plugin_manager_loaded_before_plugins(self):
        content = INDEX_HTML.read_text()
        
        pm_pos = content.find('plugin-manager.js')
        seq_pos = content.find('sequential-thinking.js')
        code_pos = content.find('code-beautifier.js')
        img_pos = content.find('image-upload.js')
        
        assert pm_pos < seq_pos, 'plugin-manager.js should load before sequential-thinking.js'
        assert pm_pos < code_pos, 'plugin-manager.js should load before code-beautifier.js'
        if img_pos != -1:
            assert pm_pos < img_pos, 'plugin-manager.js should load before image-upload.js'
    
    def test_trion_panel_loaded_before_plugins(self):
        content = INDEX_HTML.read_text()
        
        trion_pos = content.find('trion-panel.js')
        seq_pos = content.find('sequential-thinking.js')
        
        assert trion_pos != -1, 'trion-panel.js should be loaded'
        assert trion_pos < seq_pos, 'trion-panel.js should load before plugins'


class TestPluginBaseClass:
    
    def test_plugin_base_defined(self):
        content = PLUGIN_MANAGER.read_text()
        assert 'class PluginBase' in content, 'PluginBase class not defined'
    
    def test_plugin_base_exported(self):
        content = PLUGIN_MANAGER.read_text()
        assert 'window.PluginBase' in content, 'PluginBase not exported to window'
    
    def test_plugin_manager_exported(self):
        content = PLUGIN_MANAGER.read_text()
        assert 'window.PluginManager' in content, 'PluginManager not exported to window'


class TestPluginManifestIds:
    
    @pytest.mark.parametrize('plugin_file,expected_id', [
        ('sequential-thinking.js', 'sequential-thinking'),
        ('code-beautifier.js', 'code-beautifier'),
        ('image-upload.js', 'image-upload')
    ])
    def test_plugin_has_correct_id(self, plugin_file, expected_id):
        filepath = PLUGIN_DIR / plugin_file
        if not filepath.exists():
            pytest.skip(f'{plugin_file} not found')
        
        content = filepath.read_text()
        # Check if expected_id appears in content
        assert expected_id in content, f'{plugin_file} should have id: {expected_id}'
