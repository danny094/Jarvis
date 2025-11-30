VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://validator-service:8000")
ENABLE_VALIDATION = os.getenv("ENABLE_VALIDATION", "true").lower() == "true"
VALIDATION_THRESHOLD = float(os.getenv("VALIDATION_THRESHOLD", "0.70"))
VALIDATION_HARD_FAIL = os.getenv("VALIDATION_HARD_FAIL", "true").lower() == "true"