import subprocess
import os
import sys

# --- CONFIGURATION ---
# Mapping of directories to docker-compose service names
# Based on docker-compose.yml content and directory structure
SERVICE_MAPPING = {
    "sql-memory": "mcp-sql-memory",
    "mcp-servers/cim-server": "cim-server",
    "mcp-servers/sequential-thinking": "sequential-thinking",
    "adapters/lobechat": "lobechat-adapter",
    "adapters/Jarvis": "jarvis-webui",
    "adapters/admin-api": "jarvis-admin-api",
    "validator-service": "validator-service",
    # Core directories that might affect multiple or specific services
    # For now, if core changes, we might want to warn or restart all, 
    # but let's map 'core' to the main consumers if possible or just leave as general update
    "core": "lobechat-adapter", # lobechat-adapter mounts core
    "intelligence_modules": "cim-server" # cim-server mounts intelligence_modules
}

# Critical files that trigger a backup warning
CRITICAL_FILES = [
    "sql_memory/data/memory.db", # Path based on docker-compose volume mapping
    "docker-compose.yml",
    ".env"
]

def run_command(cmd):
    """Executes a system command and returns output."""
    try:
        # Using check=True to raise exception on failure
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {cmd}")
        print(f"Error output: {e.stderr}")
        return ""

def check_updates():
    print("\n🔍 Checking for updates...")
    run_command("git fetch")
    
    # Check if local is behind remote
    status = run_command("git status -uno")
    if "Your branch is behind" not in status:
        print("✅ TRION is up to date.")
        return False, [], False

    # Get list of changed files
    # HEAD..@{u} checks diff between current local HEAD and the upstream branch
    changed_files_output = run_command("git diff --name-only HEAD..@{u}")
    if not changed_files_output:
        # Fallback if status says behind but diff shows nothing
        return True, [], False
        
    changed_files = changed_files_output.split('\n')
    
    affected_services = set()
    critical_changes = False
    
    print(f"\n📝 Changed files ({len(changed_files)}):")
    for file in changed_files:
        print(f"  - {file}")
        
        # Check for service mapping
        for path, service in SERVICE_MAPPING.items():
            if path in file:
                affected_services.add(service)
        
        # Check for critical files
        for critical in CRITICAL_FILES:
            if critical in file:
                critical_changes = True
                print(f"  ⚠️  CRITICAL CHANGE DETECTED: {file}")

    return True, list(affected_services), critical_changes

def perform_update(services):
    print("\n🚀 Starting update process...")
    
    # 1. Pull new code
    print("📥 Pulling latest changes from Git...")
    pull_output = run_command("git pull")
    print(pull_output)
    
    if "Already up to date" in pull_output and not services:
        print("Everything looks correct.")
        return

    # 2. Restart affected services
    if services:
        print(f"\n🔄 Services to be restarted: {', '.join(services)}")
        for service in services:
            print(f"   Restarting {service}...")
            # Using --no-deps to only restart the specific service
            result = run_command(f"docker-compose restart {service}")
            print(f"   ✅ {service} updated.")
    else:
        print("No specific services matched for restart. (Only core/doc files changed?)")

def main():
    print("--- TRION UPDATE MANAGER ---")
    
    try:
        update_available, services, critical_changes = check_updates()
        
        if update_available:
            print(f"\n📢 New updates found!")
            if services:
                unique_services = list(set(services)) # Deduplicate
                print(f"📦 Affected services: {', '.join(unique_services)}")
            else:
                print("📝 Only documentation or core files changed (No service restart required).")
            
            if critical_changes:
                print("\n" + "!"*50)
                print("⚠️  CAUTION: Database schema or core configuration changes detected!")
                print("   Please verify migrations or backups before proceeding.")
                print("!"*50 + "\n")
            
            choice = input("Do you want to apply updates and restart services? [y/N]: ").lower()
            if choice == 'y':
                perform_update(list(set(services)))
                print("\n✨ All systems operational and up to date.")
            else:
                print("\n❌ Update cancelled by user.")
        else:
            print("\nKeep on thinking! 🧠")

    except KeyboardInterrupt:
        print("\n\n❌ Script aborted by user.")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
