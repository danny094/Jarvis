from pathlib import Path
from typing import Tuple, Optional
import os


def _resolve_default_safe_base() -> str:
    # Explicit override wins.
    explicit = str(os.environ.get("TRION_HOME_SAFE_BASE", "")).strip()
    if explicit:
        return explicit
    # Fallback to configured home identity.
    try:
        from utils.trion_home_identity import load_home_identity

        identity = load_home_identity(create_if_missing=False)
        configured = str(identity.get("home_path", "")).strip()
        if configured:
            return configured
    except Exception:
        pass
    # Safe fallback compatible with current deployment.
    return "/trion-home"

class SecurePathValidator:
    """
    SECURE Path Validation with Symlink Protection & Path Traversal Prevention.
    
    This class ensures that any file access is strictly confined within a safe base directory.
    It protects against:
    1. Path Traversal Attacks (e.g., "../../etc/passwd")
    2. Symlink Attacks (e.g., a symlink inside safe_base pointing to /etc/passwd)
    3. Access to hidden files (optional, enabled by default)
    """
    
    def __init__(self, safe_base: Optional[str] = None):
        """
        Initialize the validator with a safe base directory.
        
        Args:
            safe_base: The absolute path to the directory where file access is allowed.
        """
        resolved_base = str(safe_base or _resolve_default_safe_base()).strip() or "/trion-home"
        self.safe_base = Path(resolved_base).resolve()
    
    def validate(self, user_path: str) -> Tuple[bool, str, str]:
        """
        Validates the requested path against security rules.
        
        Args:
            user_path: The path requested by the user/tool (relative or absolute).
            
        Returns:
            A tuple containing:
            - is_valid (bool): True if the path is safe to access.
            - resolved_path (str): The absolute, resolved path (if valid) or empty string.
            - error_message (str): Description of the security violation (if invalid).
        """
        try:
            # 1. Construct the full requested path
            # If user_path is relative, it joins with safe_base.
            # If user_path is absolute, join ignores safe_base, but we check containment later.
            # To be safe and support "relative to safe_base" behavior:
            if os.path.isabs(user_path):
                 # If absolute, check if it starts with safe_base, otherwise treat as relative
                 # access is only allowed inside safe_base anyway.
                 requested = Path(user_path)
            else:
                 requested = self.safe_base / user_path
            
            # 2. Resolve the path to get the canonical path (following symlinks!)
            # We use strict=False because the file might not exist yet (e.g. writing a new file)
            # However, for existing components of the path, we MUST resolve symlinks.
            resolved = requested.resolve()
            
            # 3. CRITICAL CHECK: Is the resolved path still inside the safe_base?
            # This is the primary defense against Symlink Attacks and Path Traversal.
            try:
                resolved.relative_to(self.safe_base)
            except ValueError:
                return (
                    False, 
                    "", 
                    f"Security: Path escapes safe directory ({self.safe_base}): {user_path}"
                )
            
            # 4. Check for hidden files (files starting with .)
            # We check specific parts relative to safe_base to avoid flagging safe_base itself if it's hidden
            rel_parts = resolved.relative_to(self.safe_base).parts
            if any(part.startswith('.') for part in rel_parts):
                return (
                    False, 
                    "", 
                    f"Security: Access to hidden files is forbidden: {user_path}"
                )
                
            # 5. Success
            return (True, str(resolved), "")
            
        except Exception as e:
            return (False, "", f"Security: Path validation failed: {str(e)}")
