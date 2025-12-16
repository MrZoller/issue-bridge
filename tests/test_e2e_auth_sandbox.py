import subprocess
import sys
import unittest


class AuthSandboxE2ETests(unittest.TestCase):
    def test_e2e_auth_sandbox_runner(self):
        """Hermetic E2E smoke test for built-in Basic Auth middleware."""
        cmd = [sys.executable, "scripts/e2e_auth_sandbox.py"]
        proc = subprocess.run(  # noqa: S603,S607 (intentional controlled subprocess)
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.returncode != 0:
            self.fail(f"E2E auth sandbox runner failed (rc={proc.returncode}):\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()
