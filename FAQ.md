# Frequently Asked Questions (FAQ)

Common questions, known issues, and workarounds for TRION.

## 📚 General Questions

### What is TRION?

TRION is a local-first AI system with a 3-layer architecture designed to reduce hallucinations and provide reliable AI reasoning. It runs entirely on consumer hardware with zero API costs.

### Why "local-first"?

**Benefits:**
- 🔒 Complete data privacy (nothing leaves your machine)
- 💰 Zero API costs (no per-token fees)
- ⚡ No rate limits
- 🏠 Full control over your data
- 🌐 Works offline

### What hardware do I need?

**Minimum:**
- CPU: Modern multi-core (4+ cores)
- RAM: 16GB
- GPU: NVIDIA GPU with 5GB+ VRAM (or CPU-only mode)
- Storage: 20GB+ free

**Recommended:**
- CPU: 8+ cores
- RAM: 32GB
- GPU: RTX 3060 or better (8GB+ VRAM)
- Storage: 50GB+ (for models)

**Danny's Setup:**
- RTX 2060 SUPER (5GB VRAM)
- Works great for 8B models!

### Can I run this without a GPU?

Yes! But it will be slower. Use CPU-only mode in config.

### What models are supported?

Any Ollama-compatible model:
- DeepSeek-R1 (recommended for Layer 1)
- Qwen3 (recommended for Layer 2)
- Llama3.1 (recommended for Layer 3)
- Many others!

## 🐛 Known Issues & Workarounds

### Issue: Docker container won't start

**Symptoms:**
```
Error: Cannot connect to Docker daemon
```

**Solution:**
```bash
# Start Docker daemon
sudo systemctl start docker

# Check Docker status
sudo systemctl status docker

# Add your user to docker group (then logout/login)
sudo usermod -aG docker $USER
```

---

### Issue: Ollama connection refused

**Symptoms:**
```
ConnectionError: [Errno 111] Connection refused
```

**Solutions:**

**1. Check Ollama is running:**
```bash
curl http://localhost:11434/api/tags
```

**2. If not running, start Ollama:**
```bash
ollama serve
```

**3. Check port configuration:**
```yaml
# In config.yaml
ollama:
  base_url: "http://localhost:11434"  # Check this matches
```

**4. If using Docker:**
```yaml
# Use host.docker.internal instead of localhost
ollama:
  base_url: "http://host.docker.internal:11434"
```

---

### Issue: Out of memory / CUDA OOM

**Symptoms:**
```
RuntimeError: CUDA out of memory
```

**Solutions:**

**1. Use smaller models:**
```bash
# Instead of 13B, use 8B
ollama pull deepseek-r1:8b
```

**2. Reduce context window:**
```yaml
# In config.yaml
models:
  layer1:
    num_ctx: 4096  # Reduce from 8192
```

**3. Run models sequentially (not parallel):**
```yaml
execution:
  mode: "sequential"  # Not "parallel"
```

**4. Enable offloading:**
```yaml
models:
  layer1:
    num_gpu: 25  # Reduce layers in GPU, rest in RAM
```

---

### Issue: Slow inference speed

**Symptoms:**
Responses take >30 seconds for simple queries

**Solutions:**

**1. Check model size:**
```bash
# Use smaller models
ollama pull qwen3:4b  # Not 13b or 32b
```

**2. Check GPU utilization:**
```bash
nvidia-smi
# GPU should be at 80-100% during inference
```

**3. Enable GPU for all models:**
```yaml
models:
  layer1:
    num_gpu: -1  # Use all GPU layers
```

**4. Reduce context window:**
```yaml
models:
  layer1:
    num_ctx: 2048  # Smaller = faster
```

---

### Issue: Memory graph not updating

**Symptoms:**
New facts not appearing in graph visualization

**Solutions:**

**1. Check memory system is enabled:**
```yaml
memory:
  enabled: true
```

**2. Force memory refresh:**
```bash
# Restart the system
docker-compose restart
```

**3. Check database connection:**
```bash
# In container
psql -U postgres -d jarvis
\dt  # Should see memory tables
```

**4. Clear and rebuild:**
```bash
# Nuclear option - rebuilds graph
python scripts/rebuild_memory.py
```

---

### Issue: Persona not loading

**Symptoms:**
```
FileNotFoundError: Persona 'X' not found
```

**Solutions:**

**1. Check persona files exist:**
```bash
ls DATA/Persona/
# Should see: assistant.txt, coder.txt, etc.
```

**2. Check persona syntax:**
```yaml
# In persona YAML file
name: "Assistant"
version: "1.0.0"
behavior_file: "assistant.txt"  # This file must exist!
```

**3. Check file permissions:**
```bash
sudo chmod 644 DATA/Persona/*.txt
sudo chmod 644 DATA/Persona/*.yaml
```

**4. Restart system:**
```bash
docker-compose restart
```

---

### Issue: WebUI not accessible

**Symptoms:**
Cannot access http://localhost:8000

**Solutions:**

**1. Check if running:**
```bash
docker ps | grep jarvis
# Should see container running
```

**2. Check port binding:**
```yaml
# In docker-compose.yml
ports:
  - "8000:8000"  # Host:Container
```

**3. Check firewall:**
```bash
sudo ufw allow 8000
```

**4. Try different port:**
```yaml
ports:
  - "8080:8000"  # Use 8080 instead
```

---

### Issue: Tests failing

**Symptoms:**
```
10/12 tests passing, 2 failing
```

**Common causes:**

**1. Missing dependencies:**
```bash
pip install -r requirements-dev.txt
```

**2. Database not initialized:**
```bash
python scripts/init_db.py
```

**3. Environment variables:**
```bash
# Check .env file exists
cp .env.example .env
# Fill in your values
```

**4. Port conflicts:**
```bash
# Check nothing else using ports
lsof -i :8000
lsof -i :5432
```

## 🔧 Configuration Issues

### How do I change the default model?

Edit `config.yaml`:
```yaml
models:
  layer1:
    model: "deepseek-r1:8b"  # Change this
    temperature: 0.7
```

Then restart:
```bash
docker-compose restart
```

### How do I add more memory?

Edit `config.yaml`:
```yaml
memory:
  short_term:
    max_facts: 50  # Increase from 25
  long_term:
    max_nodes: 200  # Increase from 100
```

### How do I disable a layer?

You can't disable layers (they're core to architecture), but you can:
```yaml
layers:
  layer3_output:
    persona: "minimal"  # Use minimal persona
```

## 🚀 Performance Tips

### How to optimize for speed?

1. **Use smaller models** (8B instead of 13B)
2. **Reduce context windows** (4096 instead of 8192)
3. **Enable GPU fully** (`num_gpu: -1`)
4. **Sequential execution** (not parallel)
5. **Disable unused features** (if any)

### How to optimize for quality?

1. **Use larger models** (13B or 32B if GPU allows)
2. **Increase context windows** (8192 or more)
3. **Enable memory system fully**
4. **Use protocols** (Intelligence Modules when ready)
5. **Enable cognitive budget** (prevents rushing)

### How to optimize for memory?

1. **Smaller models**
2. **Reduce context windows**
3. **Limit graph size** (`max_nodes: 50`)
4. **Offload to CPU** (`num_gpu: 25` instead of `-1`)
5. **Clear old conversations regularly**

## 📱 Usage Questions

### How do I create a custom persona?

1. **Create behavior file:**
```bash
nano DATA/Persona/my_persona.txt
```

2. **Write behavior rules:**
```
You are a helpful data scientist.
- Explain statistical concepts clearly
- Use Python examples
- Recommend best practices
```

3. **Create YAML config:**
```bash
nano DATA/Persona/my_persona.yaml
```

```yaml
name: "Data Scientist"
version: "1.0.0"
description: "Statistical analysis expert"
behavior_file: "my_persona.txt"
active: true
```

4. **Restart & select in UI**

### How do I backup my data?

```bash
# Backup everything
tar -czf trion_backup.tar.gz DATA/

# Backup just database
pg_dump jarvis > backup.sql
```

### How do I migrate to new version?

```bash
# Backup first!
tar -czf backup_$(date +%Y%m%d).tar.gz DATA/

# Pull new version
git pull origin main

# Rebuild containers
docker-compose down
docker-compose build
docker-compose up -d

# Run migrations (if any)
python scripts/migrate.py
```

## 🤝 Contributing Questions

### How can I contribute?

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guide!

**Quick options:**
- 🐛 Report bugs
- ✨ Suggest features
- 📝 Improve docs
- 💻 Submit PRs
- 💬 Join discussions

### I found a bug, what now?

1. Check if already reported (Issues tab)
2. If not, create Bug Report issue
3. Include reproduction steps
4. Add logs/screenshots
5. We'll investigate!

### I want to add a feature, where do I start?

1. Check existing Feature Requests
2. Open Discussion to propose it
3. Get feedback
4. Create Feature Request issue
5. We'll help you implement!

## ❓ Still Have Questions?

**Can't find your answer here?**

1. 🔍 **Search existing issues** - Might be answered already
2. 💬 **Start a Discussion** - For open-ended questions
3. 📝 **Open a Question issue** - For specific problems
4. 📧 **Contact maintainer** - For private matters

**This FAQ is a living document!** If you found a solution to a problem not listed here, please contribute by:
- Opening a PR to add it
- Suggesting in Discussions
- Commenting on issues

---

**Last Updated:** 2026-01-10  
**Contributions:** Welcome! Help us improve this FAQ.
