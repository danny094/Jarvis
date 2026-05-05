[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2?logo=discord&logoColor=white)](https://discord.gg/HDsSbSQaC)


## I'd like to point out that trion/jarvis has ended the testing phase in this repository.

Chaotic code, trial and error, and monolithic designs have technically demonstrated in the alpha version what works and what doesn't.

The new, clean, functional trion 1.0 will be completely refactored and linked soon.


# TRION


TRION is a local-first autonomous AI system with a real runtime stack.
It combines chat, tools, memory, container execution, and safety controls in one platform.

## 🚀 Quick Install & First Steps

**Note:** Make sure you have **Docker** installed and running on your machine before running the install script!

```bash
curl -fsSL https://raw.githubusercontent.com/danny094/Jarvis/main/install.sh | bash
```

**Next Steps:**

1. Open your browser and go to `http://localhost:8400` to access the TRION Web UI.
2. Go to settings and add your preferred AI API Key securely to the Vault.
3. Start a chat and ask TRION to write a simple script or test the home container!

## ✨ What You Get

- **Integrated Web Environment:** Full Docker integration directly within the web interface.
- **Interactive Web Shell:** Work seamlessly with TRION via a built-in web shell connected to its container.
- **Expandable Skills:** Easily create, manage, and execute custom SKILLS.
- **MCP Integration:** Native support for the Model Context Protocol (MCP).
- **Automation / Cronjobs:** Schedule autonomous tasks and recurring operations.
- **Model Agnostic:** TRION can be powered by local AIs (like Ollama) as well as external API-based AIs.
- **Advanced Memory System:** Features a complex multi-layered memory architecture, including Graph-based STM (Short-Term), MTM, and LTM (Long-Term Memory).
- **Smart Context Storage:** Automatically saves context based on your chat activity.
- **Daily Reflection ("Dreaming"):** TRION "dreams" every day at 4 a.m. – meaning it autonomously summarizes and consolidates the daily conversation logs.

## 🏠 TRION HOME CONTAINER

TRION lives in its own dedicated, sandboxed container—its home. 
Inside this secure environment, TRION can test projects, run code, and try out new things automatically. You can completely customize this workspace and even trigger autonomous container tasks using cron jobs.

## 🔒 Security First

- **Encrypted API Keys:** Your API keys are entered once and securely stored using strict encryption.
- **Zero Raw Access:** When working in the sandbox, TRION only has access to the *names* associated with the keys—never the raw keys themselves. It cannot accidentally expose or leak your API credentials.
---

Would you like to help build TRION?  [Here you can find more information](https://github.com/danny094/Jarvis/discussions/38)

## 📸 Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center" width="50%">
        <b>🎨 Agents' Workspace</b><br><br>
        <img src="https://github.com/user-attachments/assets/261cca35-c815-474a-bcda-a3c89438ae60" width="100%" />
        <br><i>Displays the daily summary & reflections.</i>
      </td>
      <td align="center" width="50%">
        <b>⚙️ Backend Control Layer</b><br><br>
        <img src="https://github.com/user-attachments/assets/e9a7242c-f9f9-4c88-abdb-fc01035ad325" width="100%" />
        <br><i>Visualizes the strict multi-tier intelligence flow.</i>
      </td>
    </tr>
    <tr>
      <td align="center" width="50%">
        <b>🧩 Web UI Plugins</b><br><br>
        <img src="https://github.com/user-attachments/assets/e421a6c7-4b57-4704-be23-e3d04525ecfe" width="100%" />
        <br><i>Extending functionality via web-based integrations.</i>
      </td>
      <td align="center" width="50%">
        <b>🔒 Security Vault</b><br><br>
        <img src="https://github.com/user-attachments/assets/3c562338-9499-41a9-8da6-f1224a305d4b" width="100%" />
        <br><i>Fully encrypted API keys isolated from the sandbox.</i>
      </td>
    </tr>
    <tr>
      <td align="center" width="50%">
        <b>📦 Container Sandbox</b><br><br>
        <img src="https://github.com/user-attachments/assets/15f48ae5-8d55-46e8-beac-e4a4f4c3a26b" width="100%" />
        <br><i>Safe local execution environment for skills.</i>
      </td>
      <td align="center" width="50%">
        <b>💬 Main Interface</b><br><br>
        <img src="https://github.com/user-attachments/assets/153f44d8-ea25-465a-8b36-8d51e1de7395" width="100%" />
        <br><i>Seamless and beautiful chat interaction.</i>
      </td>
    </tr>
  </table>
</div>

## 🤝 Support

If this project helps you, consider supporting development:

[![Sponsor danny094](https://img.shields.io/badge/Sponsor-danny094-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/danny094)

Kontakt: trlon.devs.dk@gmail.com
