# Contributing to TRION

First off, thank you for considering contributing to TRION! 🎉

Whether you're fixing a bug, adding a feature, improving documentation, or just asking questions - all contributions are welcome and appreciated!

## 🤝 Code of Conduct

Be respectful, be kind, be constructive. We're all here to build something cool together.

## 🎯 Ways to Contribute

### 💬 **Join the Discussion**
The easiest way to contribute! Share your ideas, use cases, or feedback in [Discussions](https://github.com/danny094/Jarvis/discussions).

### 🐛 **Report Bugs**
Found a bug? Please create an issue using the Bug Report template. Include:
- Clear description of the problem
- Steps to reproduce
- Expected vs. actual behavior
- Your environment (OS, GPU, versions)
- Relevant logs or screenshots

### ✨ **Suggest Features**
Have an idea? Create an issue using the Feature Request template. Explain:
- What problem it solves
- How it would work
- Who would benefit

### 📝 **Improve Documentation**
Documentation can always be better! You can:
- Fix typos or unclear explanations
- Add examples
- Write tutorials or guides
- Improve code comments

### 🧪 **Test & Provide Feedback**
Try TRION and let us know:
- What works well
- What's confusing
- What's missing
- What could be better

### 💻 **Write Code**
Ready to code? Check out:
- [Good First Issues](https://github.com/danny094/Jarvis/labels/good%20first%20issue) - Great for beginners
- [Help Wanted](https://github.com/danny094/Jarvis/labels/help%20wanted) - We'd love help with these
- Open issues without assignees

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Docker & Docker Compose
- NVIDIA GPU (for local inference) or API access
- Basic understanding of AI/LLM concepts (helpful but not required)

### Setup Development Environment

1. **Fork & Clone**
```bash
git clone https://github.com/danny094/Jarvis.git
cd Jarvis
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Testing & development tools
```

3. **Run Tests**
```bash
python run_tests_pretty.sh
```

4. **Start Development Server**
```bash
docker-compose up -d
python main.py
```

## 📋 Development Workflow

### 1. **Create a Branch**
```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. **Make Changes**
- Write clear, documented code
- Follow existing code style
- Add tests for new features
- Update documentation if needed

### 3. **Test Your Changes**
```bash
# Run all tests
python run_tests_pretty.sh

# Run specific tests
pytest tests/test_your_feature.py -v
```

### 4. **Commit**
```bash
git add .
git commit -m "Description of your changes"
```

**Good commit messages:**
- ✅ "Add retry logic to Ollama connection"
- ✅ "Fix memory leak in graph traversal"
- ✅ "Update README with Docker setup instructions"

**Bad commit messages:**
- ❌ "Fixed stuff"
- ❌ "Update"
- ❌ "WIP"

### 5. **Push & Create Pull Request**
```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub with:
- Clear description of changes
- Link to related issue (if any)
- Screenshots (if UI changes)
- Any breaking changes noted

## 🎨 Code Style

### Python
- Follow PEP 8
- Use type hints where possible
- Write docstrings for functions/classes
- Keep functions focused and small

**Example:**
```python
def calculate_complexity(task: Task) -> int:
    """
    Estimate task complexity on scale of 1-10.
    
    Args:
        task: Task to analyze
        
    Returns:
        Complexity score (1 = simple, 10 = very complex)
    """
    # Implementation
    pass
```

### Documentation
- Clear and concise
- Examples where helpful
- Explain "why" not just "what"

## 🧪 Testing

All code should have tests! We use pytest.

**Test Structure:**
```python
def test_feature_name():
    """Test that feature does X when Y happens."""
    # Arrange
    setup = create_test_setup()
    
    # Act
    result = feature_under_test(setup)
    
    # Assert
    assert result == expected_value
```

**Run tests before submitting:**
```bash
pytest tests/ -v --cov=modules --cov-report=html
```

Target: >80% code coverage

## 📁 Project Structure

```
Jarvis/
├── modules/              # Core system modules
│   ├── layer1_thinking/  # Intent recognition & planning
│   ├── layer2_control/   # Execution & validation
│   ├── layer3_output/    # Response generation
│   └── memory/           # Memory system & graphs
├── intelligence-modules/ # Frank's cognitive components
│   ├── cognitive-bias/   # Bias detection
│   ├── context-graphs/   # Graph building
│   ├── procedural-rag/   # Reasoning protocols
│   └── executable-rag/   # Dynamic execution
├── tests/                # Test suite
├── docs/                 # Documentation
└── docker/               # Docker configs
```

## 🏷️ Issue Labels

- `bug` - Something isn't working
- `enhancement` - New feature or request
- `documentation` - Documentation improvements
- `good first issue` - Great for beginners
- `help wanted` - We'd love help with this
- `question` - Questions or support needed
- `wontfix` - Not planned for now

## ❓ Questions?

**Not sure where to start?**
- Check [Good First Issues](https://github.com/danny094/Jarvis/labels/good%20first%20issue)
- Ask in [Discussions](https://github.com/danny094/Jarvis/discussions)
- Open a Question issue

**Having trouble with setup?**
- Check existing issues
- Ask in Discussions
- Open a Question issue with your error logs

**Want to work on something specific?**
- Comment on the issue first
- We'll help you get started
- Ask questions anytime

## 🎉 Recognition

Contributors are recognized in:
- README.md contributors section
- Release notes
- Commit history

Significant contributors may be invited as collaborators!

## 📞 Contact

- **GitHub Issues:** For bugs, features, questions
- **Discussions:** For general chat, ideas, show & tell
- **Reddit:** u/danny094 (for longer discussions)

## 🙏 Thank You!

Every contribution, no matter how small, makes TRION better. Whether you're:
- Reporting a bug 🐛
- Fixing a typo 📝
- Adding a feature ✨
- Improving docs 📚
- Sharing ideas 💡
- Testing changes 🧪

**You're making a difference!** Thank you for being part of this project. 🚀

---

**New to Open Source?** Welcome! This is a great place to start. Don't be intimidated - everyone was new once. We're here to help! 😊

**Questions about this guide?** Open a Discussion or Issue. We'll improve this based on your feedback!
